"""线程池 + 日志队列管理"""
import asyncio
import json
import random
import secrets
import string
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from backend.temp_mail import TempMailClient
from backend.registration import run_register


def _generate_password(length: int = 16) -> str:
    """生成随机密码：至少包含大小写字母、数字、特殊字符"""
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%&*"
    # 确保每类至少一个
    pwd = [
        secrets.choice(lower),
        secrets.choice(upper),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    all_chars = lower + upper + digits + special
    pwd += [secrets.choice(all_chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


class TaskManager:
    def __init__(self):
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._total = 0
        self._completed = 0
        self._success = 0
        self._failed = 0
        self._log_queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # 由外部注入
        self._db_create_account = None
        self._db_update_account = None

    def set_log_queue(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self._log_queue = queue
        self._loop = loop

    def set_db_callbacks(self, create_fn, update_fn):
        self._db_create_account = create_fn
        self._db_update_account = update_fn

    def _push_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = json.dumps({"time": ts, "message": msg}, ensure_ascii=False)
        if self._log_queue and self._loop:
            self._loop.call_soon_threadsafe(self._log_queue.put_nowait, line)

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "total": self._total,
            "completed": self._completed,
            "success": self._success,
            "failed": self._failed,
        }

    def start(
        self,
        count: int,
        thread_count: int,
        password: str,
        default_proxy: str,
        providers: list[dict],
        proxies: list[dict],
        email_poll_timeout: int,
        delay_min: int,
        delay_max: int,
    ):
        if self._running:
            raise RuntimeError("注册任务已在运行中")

        self._stop_event.clear()
        self._running = True
        self._total = count
        self._completed = 0
        self._success = 0
        self._failed = 0

        self._executor = ThreadPoolExecutor(max_workers=thread_count)

        proxy_desc = default_proxy if default_proxy else ("代理池" if proxies else "直连")
        self._push_log(f"启动注册任务: {count} 个账号, {thread_count} 线程, 网络: {proxy_desc}")

        for i in range(count):
            self._executor.submit(
                self._register_one,
                i + 1,
                password,
                default_proxy,
                providers,
                proxies,
                email_poll_timeout,
                delay_min,
                delay_max,
            )

    def stop(self):
        if not self._running:
            return
        self._push_log("正在停止注册任务...")
        self._stop_event.set()
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._push_log("注册任务已停止")

    def _register_one(
        self,
        index: int,
        password: str,
        default_proxy: str,
        providers: list[dict],
        proxies: list[dict],
        email_poll_timeout: int,
        delay_min: int,
        delay_max: int,
    ):
        if self._stop_event.is_set():
            return

        self._push_log(f"[#{index}] 开始注册...")

        # 密码：为空则随机生成16位
        actual_password = password if password else _generate_password()
        if not password:
            self._push_log(f"[#{index}] 使用随机密码")

        # 可用代理列表
        enabled_proxies = [p for p in proxies if p.get("enabled")]

        # 可用邮箱提供商
        enabled_providers = [p for p in providers if p.get("enabled")]
        if not enabled_providers:
            self._push_log(f"[#{index}] 没有可用的邮箱提供商!")
            with self._lock:
                self._completed += 1
                self._failed += 1
            self._check_done()
            return

        # 可重试的错误关键词
        _retryable = [
            "unsupported_email",
            "oai-did cookie",
            "Device ID",
            "curl: (35)",
            "curl: (56)",
            "curl: (28)",
            "curl: (52)",
            "curl: (55)",
            "Connection was reset",
            "SSL_connect",
            "Cloudflare 拦截",
            "403",
        ]

        max_attempts = 3
        account_id = None
        last_err = ""

        for attempt in range(max_attempts):
            if self._stop_event.is_set():
                return

            if attempt > 0:
                self._push_log(f"[#{index}] 第 {attempt + 1}/{max_attempts} 次尝试...")

            # 选择代理：设置里的 > 代理池随机 > 直连
            proxy_url = None
            if default_proxy:
                proxy_url = default_proxy
            elif enabled_proxies:
                proxy_url = random.choice(enabled_proxies)["url"]

            if proxy_url:
                self._push_log(f"[#{index}] 使用代理: {proxy_url}")
            else:
                self._push_log(f"[#{index}] 使用直连网络")

            # 随机选择邮箱提供商
            random.shuffle(enabled_providers)
            provider = enabled_providers[0]

            # 首次尝试时创建数据库记录
            if attempt == 0:
                if self._db_create_account and self._loop:
                    future = asyncio.run_coroutine_threadsafe(
                        self._db_create_account(
                            email="pending",
                            password=actual_password,
                            status="registering",
                            temp_email_provider=provider["name"],
                            proxy_used=proxy_url or "",
                        ),
                        self._loop,
                    )
                    try:
                        account_id = future.result(timeout=5)
                    except Exception as e:
                        self._push_log(f"[#{index}] DB 写入失败: {str(e)[:100]}")

            mail_client = TempMailClient(provider, enabled_providers)
            mail_client.set_log_fn(lambda msg: self._push_log(f"[#{index}] {msg}"))
            try:
                result = run_register(
                    password=actual_password,
                    proxy=proxy_url,
                    mail_client=mail_client,
                    log_fn=lambda msg: self._push_log(f"[#{index}] {msg}"),
                    email_poll_timeout=email_poll_timeout,
                )

                # 成功 — 更新数据库
                if account_id and self._db_update_account and self._loop:
                    future = asyncio.run_coroutine_threadsafe(
                        self._db_update_account(
                            account_id,
                            email=result.get("email", ""),
                            access_token=result.get("access_token"),
                            refresh_token=result.get("refresh_token"),
                            id_token=result.get("id_token"),
                            account_id=result.get("account_id"),
                            token_expired_at=result.get("token_expired_at"),
                            temp_email_provider=result.get("temp_email_provider"),
                            proxy_used=result.get("proxy_used"),
                            status="success",
                        ),
                        self._loop,
                    )
                    try:
                        future.result(timeout=5)
                    except Exception as e:
                        self._push_log(f"[#{index}] DB 更新失败: {str(e)[:100]}")

                with self._lock:
                    self._completed += 1
                    self._success += 1
                self._push_log(f"[#{index}] 注册成功: {result.get('email')}")
                return  # 成功，退出重试循环

            except Exception as e:
                last_err = str(e)[:300]
                self._push_log(f"[#{index}] 注册失败: {last_err}")

                # 判断是否可重试
                can_retry = attempt + 1 < max_attempts and any(kw in last_err for kw in _retryable)
                if can_retry:
                    self._push_log(f"[#{index}] 将换代理/提供商重试...")
                    wait = 3 * (attempt + 1)
                    self._stop_event.wait(wait)
                    continue
                else:
                    break  # 不可重试，退出循环

            finally:
                mail_client.close()

        # 所有尝试都失败了
        if account_id and self._db_update_account and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._db_update_account(
                    account_id,
                    email="pending",
                    status="failed",
                    error_message=last_err,
                ),
                self._loop,
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass

        with self._lock:
            self._completed += 1
            self._failed += 1
        self._check_done()

        # 延迟
        if not self._stop_event.is_set() and delay_min > 0:
            wait = random.randint(delay_min, delay_max)
            self._push_log(f"[#{index}] 等待 {wait}s...")
            self._stop_event.wait(wait)

    def _check_done(self):
        with self._lock:
            if self._completed >= self._total:
                self._running = False
                self._push_log(
                    f"注册任务完成: 成功 {self._success}, 失败 {self._failed}, 共 {self._total}"
                )


task_manager = TaskManager()
