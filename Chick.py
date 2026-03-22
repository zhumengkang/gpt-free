import json
import re
import time
import secrets
import hashlib
import base64
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, Optional
from dataclasses import dataclass

from curl_cffi import requests

# Tempmail.lol API v2
TEMPMAIL_BASE = "https://api.tempmail.lol/v2"

# OAuth 配置
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _log_step(name, info=""):
    print(f"[{time.strftime('%H:%M:%S')}] [*] {name}: {info}")


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _decode_jwt_segment(seg: str) -> Dict[str, Any]:
    """解码 JWT segment"""
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    """从 ID token 中提取 claims"""
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _parse_callback_url(callback_url: str) -> Dict[str, str]:
    """解析 OAuth callback URL"""
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)

    if not error and error_description:
        error, error_description = error_description, ""

    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    """POST 表单数据"""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(
                    f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(
            f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}"
        ) from exc


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> str:
    """提交 callback URL 并交换 token"""
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())

    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": cb["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
    )
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url() -> OAuthStart:
    """生成 OAuth 授权 URL"""
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": DEFAULT_REDIRECT_URI,
        "scope": DEFAULT_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=DEFAULT_REDIRECT_URI,
    )


def get_email_and_token(proxies: Any = None) -> tuple[str, str]:
    """创建 Tempmail.lol 邮箱"""
    try:
        resp = requests.post(
            f"{TEMPMAIL_BASE}/inbox/create",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={},
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )

        if resp.status_code not in (200, 201):
            print(f"[-] Tempmail.lol 请求失败，状态码: {resp.status_code}")
            return "", ""

        data = resp.json()
        email = str(data.get("address", "")).strip()
        token = str(data.get("token", "")).strip()

        if not email or not token:
            print("[-] Tempmail.lol 返回数据不完整")
            return "", ""

        return email, token

    except Exception as e:
        print(f"[-] 创建 Tempmail.lol 邮箱出错: {e}")
        return "", ""


def get_oai_code(token: str, email: str, proxies: Any = None) -> str:
    """轮询获取验证码"""
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[int] = set()

    _log_step("开始监听邮件", f"邮箱: {email}")

    for i in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                f"{TEMPMAIL_BASE}/inbox",
                params={"token": token},
                headers={"Accept": "application/json"},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )

            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()

            if data is None or (isinstance(data, dict) and not data):
                print("\n[-] 邮箱已过期")
                return ""

            email_list = data.get("emails", []) if isinstance(data, dict) else []

            if not isinstance(email_list, list):
                time.sleep(3)
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

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                m = re.search(regex, content)
                if m:
                    print(f"\n[+] 验证码: {m.group(1)}")
                    return m.group(1)

        except Exception as e:
            pass

        time.sleep(3)

    print("\n[-] 超时，未收到验证码")
    return ""


def run_register(proxy: Optional[str], password: str) -> Optional[str]:
    """执行注册流程并返回 token JSON"""
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    s = requests.Session(proxies=proxies, impersonate="chrome")

    try:
        # 检查网络
        _log_step("检查网络连接")
        trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
        loc_match = re.search(r"^loc=(.+)$", trace.text, re.MULTILINE)
        loc = loc_match.group(1) if loc_match else "未知"
        _log_step("当前 IP 所在地", loc)

        # 创建临时邮箱
        email, dev_token = get_email_and_token(proxies)
        if not email or not dev_token:
            return None
        _log_step("临时邮箱创建成功", email)

        # 生成 OAuth URL
        oauth = generate_oauth_url()

        # 访问授权页面获取 Device ID
        _log_step("访问授权页面")
        resp = s.get(oauth.auth_url, timeout=15)
        did = s.cookies.get("oai-did")
        _log_step("Device ID", did)

        # 调用 Sentinel API
        _log_step("获取 Sentinel Token")
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'
        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )

        if sen_resp.status_code != 200:
            print(f"[-] Sentinel 请求失败: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        # 提交注册表单
        _log_step("提交注册表单", email)
        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
        )
        _log_step("注册表单状态", signup_resp.status_code)

        # 提交密码
        _log_step("提交密码", password)
        register_body = json.dumps({"password": password, "username": email})
        pwd_resp = s.post(
            "https://auth.openai.com/api/accounts/user/register",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=register_body,
        )
        _log_step("密码提交状态", pwd_resp.status_code)

        # 发送验证码
        _log_step("请求发送验证码")
        otp_resp = s.get(
            "https://auth.openai.com/api/accounts/email-otp/send",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
            },
        )
        _log_step("验证码发送状态", otp_resp.status_code)

        # 获取验证码
        code = get_oai_code(dev_token, email, proxies)
        if not code:
            return None

        # 验证验证码
        _log_step("提交验证码", code)
        code_body = f'{{"code":"{code}"}}'
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
        )
        _log_step("验证码校验状态", code_resp.status_code)

        # 创建账户
        _log_step("创建账户")
        create_account_body = '{"name":"Neo","birthdate":"2000-02-20"}'
        create_account_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
        )
        _log_step("账户创建状态", create_account_resp.status_code)

        if create_account_resp.status_code != 200:
            print(f"[-] 账户创建失败: {create_account_resp.text}")
            return None

        # 获取 workspace
        _log_step("获取 workspace 信息")
        auth_cookie = s.cookies.get("oai-client-auth-session")

        if not auth_cookie:
            print("[-] 未能获取到授权 Cookie")
            print(auth_cookie)
            return None

        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        print(auth_json)
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[-] 授权 Cookie 里没有 workspace 信息")
            return None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        if not workspace_id:
            print("[-] 无法解析 workspace_id")
            return None

        # 选择 workspace
        _log_step("选择 workspace", workspace_id)
        select_body = f'{{"workspace_id":"{workspace_id}"}}'
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
        )

        if select_resp.status_code != 200:
            print(f"[-] 选择 workspace 失败: {select_resp.status_code}")
            return None

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[-] workspace/select 响应里缺少 continue_url")
            return None

        # 跟随重定向链获取 callback URL
        _log_step("跟随重定向链")
        current_url = continue_url
        for _ in range(6):
            final_resp = s.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                _log_step("获取到 callback URL")
                token_json = submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                )

                print("\n" + "="*60)
                print("✅ 注册成功！")
                print(f"邮箱: {email}")
                print(f"密码: {password}")
                print("="*60)

                return token_json
            current_url = next_url

        print("[-] 未能在重定向链中捕获到最终 Callback URL")
        return None

    except Exception as e:
        print(f"[-] 运行时错误: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import os
    import random

    print("="*60)
    print("   OpenAI 全自动注册工具")
    print("="*60)

    MY_PROXY = "http://127.0.0.1:7897"
    MY_PWD = "StrongPassword123!"

    # 循环配置
    SLEEP_MIN = 5  # 最短等待秒数
    SLEEP_MAX = 30  # 最长等待秒数

    count = 0

    while True:
        count += 1
        print(f"\n{'='*60}")
        print(f">>> 开始第 {count} 次注册流程 <<<")
        print(f"{'='*60}\n")

        try:
            token_json = run_register(MY_PROXY, MY_PWD)

            if token_json:
                try:
                    t_data = json.loads(token_json)
                    fname_email = t_data.get("email", "unknown").replace("@", "_")
                except Exception:
                    fname_email = "unknown"

                # 在脚本所在目录创建 tokens 文件夹
                script_dir = os.path.dirname(os.path.abspath(__file__))
                tokens_dir = os.path.join(script_dir, "tokens")
                os.makedirs(tokens_dir, exist_ok=True)

                file_name = os.path.join(tokens_dir, f"token_{fname_email}_{int(time.time())}.json")

                with open(file_name, "w", encoding="utf-8") as f:
                    f.write(token_json)

                print(f"\n[+] Token 已保存至: {file_name}")
            else:
                print("\n[-] 本次注册失败")

        except Exception as e:
            print(f"[-] 发生未捕获异常: {e}")

        # 随机等待
        wait_time = random.randint(SLEEP_MIN, SLEEP_MAX)
        print(f"\n[*] 休息 {wait_time} 秒后继续下一次注册...")
        time.sleep(wait_time)
