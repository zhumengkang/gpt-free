"""Tempmail.lol 邮箱客户端 - 从 Chick.py 移植"""
import re
import time
from typing import Any

from curl_cffi import requests


TEMPMAIL_BASE = "https://api.tempmail.lol/v2"


class TempMailLolClient:
    """Tempmail.lol 客户端，接口兼容 TempMailClient"""

    def __init__(self, proxy: str | None = None):
        self._proxy = proxy
        self._proxies: Any = {"http": proxy, "https": proxy} if proxy else None
        self._token: str | None = None
        self.email_address: str | None = None
        self._log_fn = None
        # 兼容 TempMailClient 的 provider 属性
        self.provider = {"name": "Tempmail.lol", "base_url": TEMPMAIL_BASE, "origin": "https://tempmail.lol"}

    def set_log_fn(self, fn):
        self._log_fn = fn

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(f"[邮箱] {msg}")

    def create_email(self) -> str:
        """创建 Tempmail.lol 邮箱，429 限流时自动等待重试"""
        self._log("使用 Tempmail.lol 创建邮箱...")
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{TEMPMAIL_BASE}/inbox/create",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={},
                    proxies=self._proxies,
                    impersonate="chrome",
                    timeout=15,
                )

                if resp.status_code == 429:
                    wait = 5 + attempt * 5  # 5s, 10s, 15s, 20s, 25s
                    self._log(f"Tempmail.lol 限流 (429)，{wait}s 后重试 ({attempt+2}/{max_retries})...")
                    time.sleep(wait)
                    continue

                if resp.status_code not in (200, 201):
                    raise RuntimeError(f"Tempmail.lol 请求失败: HTTP {resp.status_code} {resp.text[:200]}")

                data = resp.json()
                email = str(data.get("address", "")).strip()
                token = str(data.get("token", "")).strip()

                if not email or not token:
                    raise RuntimeError(f"Tempmail.lol 返回数据不完整: {data}")

                self._token = token
                self.email_address = email
                self._log(f"邮箱创建成功: {email} (Tempmail.lol)")
                return email

            except RuntimeError:
                raise
            except Exception as e:
                if attempt + 1 < max_retries:
                    self._log(f"Tempmail.lol 请求出错: {e}，重试中...")
                    time.sleep(3)
                    continue
                raise RuntimeError(f"Tempmail.lol 创建邮箱失败: {e}")

        raise RuntimeError("Tempmail.lol 创建邮箱失败: 多次限流 (429)")

    def wait_for_code(self, timeout: int = 120, keyword: str = "openai") -> str:
        """轮询获取验证码 - 和 Chick.py 原版逻辑一致"""
        if not self._token:
            raise RuntimeError("没有 token，请先创建邮箱")

        regex = r"(?<!\d)(\d{6})(?!\d)"
        seen_ids: set = set()

        self._log(f"等待验证码 (超时: {timeout}s, 邮箱: {self.email_address})")
        self._log(f"Tempmail.lol token: {self._token}")

        # 先等 5 秒
        self._log("等待 5s 后开始查收邮件...")
        time.sleep(5)

        start = time.time()
        attempt = 0

        while True:
            attempt += 1
            elapsed = time.time() - start
            remaining = timeout - elapsed

            if elapsed >= timeout:
                raise RuntimeError(f"获取验证码超时 ({timeout}s)")

            if attempt > 1:
                time.sleep(3)

            if attempt > 1 and attempt % 5 == 0:
                self._log(f"轮询 #{attempt} (已用 {int(elapsed)}s, 剩余 {int(remaining)}s)")

            try:
                resp = requests.get(
                    f"{TEMPMAIL_BASE}/inbox",
                    params={"token": self._token},
                    headers={"Accept": "application/json"},
                    proxies=self._proxies,
                    impersonate="chrome",
                    timeout=15,
                )

                if resp.status_code != 200:
                    self._log(f"API 返回 {resp.status_code}")
                    continue

                data = resp.json()

                if data is None or (isinstance(data, dict) and not data):
                    self._log("邮箱已过期")
                    raise RuntimeError("Tempmail.lol 邮箱已过期")

                email_list = data.get("emails", []) if isinstance(data, dict) else []

                if not isinstance(email_list, list):
                    continue

                if not email_list:
                    if attempt == 1:
                        self._log("邮箱为空，等待邮件到达...")
                    continue

                for msg in email_list:
                    if not isinstance(msg, dict):
                        continue

                    msg_date = msg.get("date", 0)
                    if not msg_date or msg_date in seen_ids:
                        continue
                    seen_ids.add(msg_date)

                    sender = str(msg.get("from", "")).lower()
                    subject = str(msg.get("subject", ""))
                    body = str(msg.get("body", ""))
                    html = str(msg.get("html") or "")

                    content = "\n".join([sender, subject, body, html])

                    if keyword and keyword.lower() not in content.lower():
                        continue

                    self._log(f"收到匹配邮件: from={sender}, subject={subject}")

                    m = re.search(regex, content)
                    if m:
                        code = m.group(1)
                        self._log(f"验证码: {code}")
                        return code

            except requests.errors.RequestsError as e:
                self._log(f"请求错误: {str(e)[:100]}")
            except RuntimeError:
                raise
            except Exception as e:
                self._log(f"轮询错误: {str(e)[:100]}")

        raise RuntimeError(f"获取验证码超时 ({timeout}s)")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
