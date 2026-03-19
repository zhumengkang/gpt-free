"""临时邮箱池客户端 - 从 Rust temp_mail_client.rs 移植"""
import json
import re
import random
import string
import time
import httpx


class TempMailClient:
    """临时邮箱客户端，支持自动切换提供商"""

    def __init__(self, provider: dict, all_providers: list[dict] | None = None):
        self.provider = provider
        self.all_providers = all_providers or [provider]
        self.client = httpx.Client(verify=False, timeout=15)
        self.jwt: str | None = None
        self.email_address: str | None = None
        self._log_fn = None

    def set_log_fn(self, fn):
        self._log_fn = fn

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(f"[邮箱] {msg}")

    def _headers(self) -> dict:
        return {
            "accept": "application/json, text/plain, */*",
            "origin": self.provider["origin"],
            "referer": f"{self.provider['origin']}/",
        }

    def switch_provider(self) -> bool:
        """切换到下一个可用提供商"""
        if len(self.all_providers) <= 1:
            return False
        idx = next(
            (i for i, p in enumerate(self.all_providers) if p["name"] == self.provider["name"]),
            0,
        )
        next_idx = (idx + 1) % len(self.all_providers)
        self.provider = self.all_providers[next_idx]
        self.jwt = None
        self.email_address = None
        self._log(f"切换到提供商: {self.provider['name']}")
        return True

    def get_domains(self) -> list[str]:
        """获取可用域名列表"""
        url = f"{self.provider['base_url']}/open_api/settings"
        try:
            resp = self.client.get(url, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                domains = data.get("defaultDomains") or data.get("default_domains") or []
                if domains:
                    return domains
        except Exception as e:
            self._log(f"获取域名失败: {e}")
        return ["mail.002620.xyz"]

    def create_email(self) -> str:
        """创建临时邮箱，失败自动切换提供商"""
        max_retries = min(len(self.all_providers), 10)
        last_err = None

        for attempt in range(max_retries):
            try:
                return self._create_email_once()
            except Exception as e:
                last_err = e
                self._log(f"创建邮箱失败: {e}")
                if attempt + 1 < max_retries:
                    if not self.switch_provider():
                        break
                    time.sleep(1)

        raise RuntimeError(f"创建邮箱失败（已尝试 {max_retries} 个提供商）: {last_err}")

    def _create_email_once(self) -> str:
        domains = self.get_domains()
        if not domains:
            raise RuntimeError("没有可用域名")

        domain = random.choice(domains)
        name = "".join(random.choices(string.ascii_lowercase, k=random.randint(8, 12)))

        url = f"{self.provider['base_url']}/api/new_address"
        payload = {"name": name, "domain": domain, "cf_token": ""}

        headers = self._headers()
        headers["content-type"] = "application/json"

        resp = self.client.post(url, json=payload, headers=headers)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"创建邮箱失败 ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        self.jwt = data.get("jwt") or data.get("token")
        self.email_address = data.get("address") or data.get("email")

        if not self.jwt:
            raise RuntimeError(f"创建邮箱响应缺少 JWT: {json.dumps(data)[:200]}")
        if not self.email_address:
            raise RuntimeError(f"创建邮箱响应缺少地址: {json.dumps(data)[:200]}")

        self._log(f"邮箱创建成功: {self.email_address} (提供商: {self.provider['name']})")
        return self.email_address

    def wait_for_code(self, timeout: int = 120, keyword: str = "openai") -> str:
        """轮询等待验证码 - 参考 Rust 版本实现"""
        if not self.jwt:
            raise RuntimeError("没有 JWT，请先创建邮箱")

        url = f"{self.provider['base_url']}/api/mails?limit=20&offset=0"
        headers = self._headers()
        headers["authorization"] = f"Bearer {self.jwt}"

        self._log(f"等待验证码 (超时: {timeout}s)")
        self._log(f"邮箱: {self.email_address}")
        self._log(f"提供商: {self.provider['name']} ({self.provider['base_url']})")

        start = time.time()
        attempt = 0
        last_error: str | None = None
        seen_ids: set[str] = set()

        # 第一次轮询记录已有邮件 ID，跳过旧邮件
        first_poll = True

        while True:
            attempt += 1
            elapsed = time.time() - start
            remaining = timeout - elapsed

            if elapsed >= timeout:
                err = f"获取验证码超时 ({timeout}s)"
                if last_error:
                    err += f"。最后错误: {last_error}"
                self._log(err)
                raise RuntimeError(err)

            # 第一次立即检查，之后每 3 秒
            if attempt > 1:
                time.sleep(3)

            if attempt > 1 and attempt % 5 == 0:
                self._log(f"轮询 #{attempt} (已用 {int(elapsed)}s, 剩余 {int(remaining)}s)")

            try:
                resp = self.client.get(url, headers=headers)

                if resp.status_code != 200:
                    last_error = f"API 返回 {resp.status_code}: {resp.text[:100]}"
                    self._log(last_error)
                    continue

                data = resp.json()
                results = data.get("results") or data.get("data") or []

                if not results:
                    if attempt == 1:
                        self._log("邮箱为空，等待邮件到达...")
                    first_poll = False
                    continue

                # 第一次轮询：记录已有邮件 ID，标记为旧邮件
                if first_poll:
                    for mail in results:
                        mail_id = mail.get("id") or mail.get("_id") or mail.get("messageId") or ""
                        if mail_id:
                            seen_ids.add(str(mail_id))
                    if seen_ids:
                        self._log(f"跳过 {len(seen_ids)} 封旧邮件")
                    first_poll = False
                    continue

                # 遍历新邮件
                new_mails = []
                for mail in results:
                    mail_id = mail.get("id") or mail.get("_id") or mail.get("messageId") or ""
                    if mail_id and str(mail_id) in seen_ids:
                        continue
                    new_mails.append(mail)
                    if mail_id:
                        seen_ids.add(str(mail_id))

                if not new_mails:
                    continue

                self._log(f"收到 {len(new_mails)} 封新邮件")

                for mail_idx, mail in enumerate(new_mails):
                    # 打印邮件基本信息
                    subject = mail.get("subject", "")
                    from_addr = mail.get("from", mail.get("sender", ""))
                    self._log(f"邮件#{mail_idx+1}: from={from_addr}, subject={subject}")

                    # 提取邮件内容 - 尝试多个字段（和 Rust 版本一致）
                    content = ""
                    used_field = ""
                    for field in ("raw", "message", "body", "html", "text"):
                        val = mail.get(field)
                        if val and isinstance(val, str) and val.strip():
                            content = val
                            used_field = field
                            break

                    # 如果所有字段都为空，用整个 JSON
                    if not content:
                        content = json.dumps(mail, ensure_ascii=False)
                        used_field = "json_fallback"

                    self._log(f"邮件#{mail_idx+1}: 使用字段={used_field}, 长度={len(content)}")

                    # 先检查关键词
                    content_lower = content.lower()
                    has_keyword = keyword.lower() in content_lower if keyword else True

                    if has_keyword:
                        self._log(f"收到匹配邮件 (含 '{keyword}')")
                        code = self._extract_code(content)
                        if code:
                            self._log(f"验证码: {code}")
                            return code
                        else:
                            last_error = "邮件中未找到验证码"
                            self._log(f"邮件匹配但未提取到验证码，内容前200字: {content[:200]}")
                    else:
                        # 兜底：即使没有关键词，也尝试提取（和 Rust 版本一致）
                        code = self._extract_code(content)
                        if code:
                            self._log(f"未检测到关键词，但提取到疑似验证码: {code}")
                            return code

            except httpx.TimeoutException:
                last_error = "请求超时"
                self._log(f"轮询请求超时")
            except Exception as e:
                last_error = str(e)[:150]
                self._log(f"轮询错误: {last_error}")

    @staticmethod
    def _extract_code(content: str) -> str | None:
        """提取6位验证码 - 优化匹配顺序，避免误匹配"""
        # 先解码 quoted-printable
        decoded = content.replace("=3D", "=").replace("=\r\n", "").replace("=20", " ")

        # 排除常见干扰数字（颜色值、尺寸等）
        _noise = {"000000", "111111", "222222", "333333", "444444", "555555",
                   "666666", "777777", "888888", "999999", "ffffff", "100000"}

        patterns = [
            # OpenAI 特有格式：大字号验证码通常在 font-size:32px 或类似样式的标签里
            r'font-size:\s*3\dpx[^>]*>[\s\S]{0,20}?(\d{6})',
            # HTML code div
            r'<div class="code"[^>]*>(\d{6})</div>',
            r'class="code"[^>]*>(\d{6})',
            # <code> 标签
            r'<code[^>]*>\s*(\d{6})\s*</code>',
            # <td> 里独立的6位数字（OpenAI 邮件常见）
            r'<td[^>]*>\s*(\d{6})\s*</td>',
            # Verification code 后跟的数字
            r'[Vv]erification\s+code[:\s]*(\d{6})',
            r'[Vv]erification\s+code.*?>(\d{6})<',
            r'验证码[：:]\s*(\d{6})',
            # Your code is / Your verification code
            r'[Yy]our\s+(?:verification\s+)?code\s+is[:\s]*(\d{6})',
            # 标签之间独立的6位数字（排除属性值里的）
            r'>[\s]*(\d{6})[\s]*<',
        ]
        for pat in patterns:
            m = re.search(pat, decoded)
            if m:
                code = m.group(1)
                if code.lower() not in _noise:
                    return code

        # 兜底：独立的6位数字，但排除更多干扰
        # 不能紧跟在 # (颜色)、: (CSS值)、= (属性) 后面
        fallback = re.findall(r'(?<![#:=@\w\d])(\d{6})(?![;@\w\d])', decoded)
        for code in fallback:
            if code.lower() not in _noise:
                return code

        return None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
