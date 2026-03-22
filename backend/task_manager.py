"""线程池 + 日志队列管理 - 增强版：智能重试 + 代理健康追踪"""
import asyncio
import json
import os
import random
import secrets
import string
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from backend.temp_mail import TempMailClient
from backend.tempmail_lol import TempMailLolClient
from backend.registration import run_register
from backend.proxy_pool import ProxyPool
from backend.config import RAW_DEBUG_LOG_PATH


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
        # 代理健康追踪
        self._proxy_pool = ProxyPool()
        # 失败的邮箱提供商追踪 {provider_name: fail_count}
        self._provider_fails: dict[str, int] = {}
        self._provider_fails_lock = threading.Lock()
        self._raw_debug_log_path = RAW_DEBUG_LOG_PATH
        self._raw_debug_lock = threading.Lock()

    def _push_raw_debug(self, msg: str):
        if not self._raw_debug_log_path:
            return
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            directory = os.path.dirname(self._raw_debug_log_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with self._raw_debug_lock:
                with open(self._raw_debug_log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

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

    def _mark_provider_fail(self, provider_name: str):
        """记录邮箱提供商失败"""
        with self._provider_fails_lock:
            self._provider_fails[provider_name] = self._provider_fails.get(provider_name, 0) + 1

    def _get_sorted_providers(self, providers: list[dict]) -> list[dict]:
        """按失败次数排序提供商，失败少的优先"""
        with self._provider_fails_lock:
            return sorted(
                providers,
                key=lambda p: self._provider_fails.get(p["name"], 0),
            )

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
        email_mode: str = "tempmail_lol",
    ):
        if self._running:
            raise RuntimeError("注册任务已在运行中")

        self._stop_event.clear()
        self._running = True
        self._total = count
        self._completed = 0
        self._success = 0
        self._failed = 0

        # 初始化代理池
        self._proxy_pool.update(proxies)

        self._executor = ThreadPoolExecutor(max_workers=thread_count)

        proxy_desc = default_proxy if default_proxy else ("代理池" if proxies else "直连")
        email_desc = "Tempmail.lol" if email_mode == "tempmail_lol" else "自建邮箱池"
        self._push_log(f"启动注册任务: {count} 个账号, {thread_count} 线程, 网络: {proxy_desc}, 邮箱: {email_desc}")

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
                email_mode,
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
        email_mode: str = "tempmail_lol",
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

        # 可重试的错误关键词（扩展列表）
        _retryable = [
            "unsupported_email",
            "oai-did cookie",
            "Device ID",
            "curl: (6)",
            "curl: (7)",
            "curl: (16)",
            "curl: (18)",
            "curl: (28)",
            "curl: (35)",
            "curl: (47)",
            "curl: (52)",
            "curl: (55)",
            "curl: (56)",
            "Connection was reset",
            "Connection refused",
            "Connection aborted",
            "RemoteDisconnected",
            "ConnectionResetError",
            "SSL_connect",
            "Cloudflare 拦截",
            "403",
            "timed out",
            "TimeoutError",
            "Sentinel 请求失败",
            "验证码超时",
            "获取验证码超时",
            "invalid_auth_step",
            "Invalid authorization step",
            "代理不可用",
            "多次限流",
            "429",
        ]

        # 需要换代理的错误（代理相关问题）
        _proxy_errors = [
            "oai-did cookie",
            "Device ID",
            "curl: (6)",
            "curl: (7)",
            "curl: (28)",
            "curl: (35)",
            "curl: (56)",
            "Connection was reset",
            "Connection refused",
            "SSL_connect",
            "Cloudflare 拦截",
            "403",
            "timed out",
            "Sentinel 请求失败",
            "代理不可用",
        ]
        _email_errors = [
            "unsupported_email",
            "not supported",
            "验证码超时",
            "获取验证码超时",
            "多次限流",
            "429",
            "创建邮箱失败",
        ]

        max_attempts = 5  # 增加到5次
        account_id = None
        last_err = ""
        used_proxies: set[str] = set()  # 记录本次任务已用过的代理
        used_providers: set[str] = set()  # 记录本次任务已用过的提供商

        for attempt in range(max_attempts):
            if self._stop_event.is_set():
                return

            if attempt > 0:
                self._push_log(f"[#{index}] 第 {attempt + 1}/{max_attempts} 次尝试...")

            # 智能选择代理：代理池优先，default_proxy 只作兜底
            proxy_url = None
            if enabled_proxies:
                proxy_url = self._proxy_pool.get_random_url(exclude=used_proxies)
                if not proxy_url:
                    used_proxies.clear()
                    proxy_url = self._proxy_pool.get_random_url()
            if not proxy_url and default_proxy:
                proxy_url = default_proxy

            if proxy_url:
                self._push_log(f"[#{index}] 使用代理: {proxy_url}")
            else:
                self._push_log(f"[#{index}] 使用直连网络")

            # 智能选择邮箱提供商：优先选失败次数少的，避免重复使用已失败的
            sorted_providers = self._get_sorted_providers(enabled_providers)
            # 优先选没用过的，从中随机选一个
            unused = [p for p in sorted_providers if p["name"] not in used_providers]
            pool = unused if unused else sorted_providers
            provider = random.choice(pool)

            self._push_log(f"[#{index}] 使用邮箱提供商: {provider['name']}")

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

            # 根据 email_mode 选择邮箱客户端
            if email_mode == "tempmail_lol":
                mail_client = TempMailLolClient(proxy=proxy_url)
            else:
                mail_client = TempMailClient(provider, enabled_providers)
            mail_client.set_log_fn(lambda msg: self._push_log(f"[#{index}] {msg}"))
            mail_client.set_raw_log_fn(lambda msg: self._push_raw_debug(f"[#{index}] {msg}"))
            try:
                result = run_register(
                    password=actual_password,
                    proxy=proxy_url,
                    mail_client=mail_client,
                    log_fn=lambda msg: self._push_log(f"[#{index}] {msg}"),
                    raw_log_fn=lambda msg: self._push_raw_debug(f"[#{index}] {msg}"),
                    email_poll_timeout=email_poll_timeout,
                )

                # 成功 — 标记代理健康
                if proxy_url:
                    self._proxy_pool.mark_success(proxy_url)

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
                self._check_done()
                return  # 成功，退出重试循环

            except Exception as e:
                last_err = str(e)[:300]
                self._push_log(f"[#{index}] 注册失败: {last_err}")

                # 根据错误类型做针对性处理
                is_proxy_err = any(kw in last_err for kw in _proxy_errors)
                is_email_err = any(kw in last_err for kw in _email_errors)

                if is_proxy_err and proxy_url:
                    self._proxy_pool.mark_fail(proxy_url)
                    used_proxies.add(proxy_url)
                    health = self._proxy_pool.get_health_summary()
                    self._push_log(
                        f"[#{index}] 代理问题，已标记失败 "
                        f"(可用: {health['total_enabled'] - health['temporarily_disabled']}/{health['total_enabled']})"
                    )

                if is_email_err:
                    self._mark_provider_fail(provider["name"])
                    used_providers.add(provider["name"])
                    self._push_log(f"[#{index}] 邮箱域名被拒，已标记提供商 {provider['name']} 失败")

                # 判断是否可重试
                can_retry = attempt + 1 < max_attempts and any(kw in last_err for kw in _retryable)
                if can_retry:
                    # 根据错误类型给出提示
                    actions = []
                    if is_proxy_err and enabled_proxies:
                        actions.append("换代理")
                    if is_email_err:
                        actions.append("换邮箱提供商")
                    if not actions:
                        actions.append("重试")
                    self._push_log(f"[#{index}] 将{'+'.join(actions)}重试...")

                    wait = 2 + attempt * 2  # 2s, 4s, 6s, 8s
                    self._stop_event.wait(wait)
                    continue
                else:
                    self._push_log(f"[#{index}] 错误不可重试，放弃")
                    break

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
