"""注册逻辑 - 改造自 Chick.py，使用新邮箱池替换 Tempmail.lol"""
import json
import re
import time
import secrets
import hashlib
import base64
import urllib.parse
from typing import Any, Optional
from dataclasses import dataclass

from curl_cffi import requests as curl_requests

from backend.config import AUTH_URL, TOKEN_URL, CLIENT_ID, DEFAULT_REDIRECT_URI, DEFAULT_SCOPE
from backend.temp_mail import TempMailClient


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


def _decode_jwt_segment(seg: str) -> dict:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _jwt_claims_no_verify(id_token: str) -> dict:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _parse_callback_url(callback_url: str) -> dict:
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

    return {"code": code, "state": state, "error": error, "error_description": error_description}


def _post_form(url: str, data: dict, proxy: str | None = None, timeout: int = 30) -> dict:
    """Token exchange — 使用 curl_cffi 走代理"""
    resp = curl_requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        proxies={"http": proxy, "https": proxy} if proxy else None,
        impersonate="chrome",
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"token exchange failed: {resp.status_code}: {resp.text[:300]}")
    return resp.json()


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url() -> OAuthStart:
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
    return OAuthStart(auth_url=auth_url, state=state, code_verifier=code_verifier, redirect_uri=DEFAULT_REDIRECT_URI)


def submit_callback_url(*, callback_url: str, expected_state: str, code_verifier: str, redirect_uri: str = DEFAULT_REDIRECT_URI, proxy: str | None = None) -> dict:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        raise RuntimeError(f"oauth error: {cb['error']}: {cb['error_description']}".strip())
    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": cb["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }, proxy=proxy)

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0)))

    return {
        "email": email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": account_id,
        "token_expired_at": expired_rfc3339,
    }


_RETRYABLE_CURL_ERRORS = [
    "curl: (6)",   # Could not resolve host
    "curl: (7)",   # Failed to connect
    "curl: (16)",  # HTTP/2 error
    "curl: (18)",  # Transfer closed
    "curl: (28)",  # Operation timed out
    "curl: (35)",  # SSL connect error / Connection was reset
    "curl: (47)",  # Too many redirects
    "curl: (52)",  # Empty reply from server
    "curl: (55)",  # Send failure
    "curl: (56)",  # Recv failure
    "Connection was reset",
    "SSL_connect",
    "Connection refused",
    "Connection aborted",
    "RemoteDisconnected",
    "ConnectionResetError",
    "TimeoutError",
    "timed out",
]


def _is_retryable_error(err_str: str) -> bool:
    """判断错误是否可重试"""
    return any(x in err_str for x in _RETRYABLE_CURL_ERRORS)


def _safe_request(label: str, fn, log, retries: int = 3):
    """带重试的请求包装，网络瞬时错误自动重试"""
    last_err = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            err_str = str(e)
            if _is_retryable_error(err_str):
                if attempt + 1 < retries:
                    wait = 3 * (attempt + 1)
                    log(f"[{label}] 网络错误: {err_str[:80]}，{wait}s 后重试 ({attempt+2}/{retries})...")
                    time.sleep(wait)
                    continue
            raise
    raise last_err


def run_register(
    password: str,
    proxy: Optional[str],
    mail_client: TempMailClient,
    log_fn=None,
    email_poll_timeout: int = 120,
) -> dict:
    """
    执行完整注册流程。
    返回包含 token 信息的 dict，失败抛出异常。
    """
    def log(msg: str):
        if log_fn:
            log_fn(msg)

    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    s = curl_requests.Session(proxies=proxies, impersonate="chrome", timeout=45)

    try:
        # 1. 检查网络
        log("[1/14] 检查网络连接...")
        trace = _safe_request("网络检查", lambda: s.get("https://cloudflare.com/cdn-cgi/trace", timeout=30), log)
        loc_match = re.search(r"^loc=(.+)$", trace.text, re.MULTILINE)
        loc = loc_match.group(1) if loc_match else "未知"
        log(f"当前 IP 所在地: {loc}")

        # 2. 创建临时邮箱
        log(f"[2/14] 创建临时邮箱 (提供商: {mail_client.provider['name']})...")
        email = mail_client.create_email()
        log(f"临时邮箱: {email}")

        # 3. 生成 OAuth URL
        oauth = generate_oauth_url()

        # 4. 访问授权页面
        log("[3/14] 访问授权页面...")
        auth_resp = _safe_request("授权页面", lambda: s.get(oauth.auth_url, timeout=30), log)
        log(f"授权页面状态: {auth_resp.status_code}")

        did = s.cookies.get("oai-did")
        if not did:
            # 打印所有 cookie 帮助调试
            all_cookies = "; ".join([f"{k}={v[:20]}..." for k, v in s.cookies.items()])
            log(f"收到的 cookies: {all_cookies if all_cookies else '(空)'}")
            raise RuntimeError("未获取到 Device ID (oai-did cookie)，可能是代理被 Cloudflare 拦截")
        log(f"Device ID: {did}")

        # 5. Sentinel Token
        log("[4/14] 获取 Sentinel Token...")
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

        def _get_sentinel():
            return curl_requests.post(
                "https://sentinel.openai.com/backend-api/sentinel/req",
                headers={
                    "origin": "https://sentinel.openai.com",
                    "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                    "content-type": "text/plain;charset=UTF-8",
                },
                data=sen_req_body,
                proxies=proxies,
                impersonate="chrome",
                timeout=30,
            )

        sen_resp = _safe_request("Sentinel", _get_sentinel, log)
        if sen_resp.status_code != 200:
            raise RuntimeError(f"Sentinel 请求失败: {sen_resp.status_code} {sen_resp.text[:200]}")

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        # 6. 提交注册表单
        log(f"[5/14] 提交注册表单: {email}")
        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'

        def _signup():
            return s.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers={
                    "referer": "https://auth.openai.com/create-account",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": sentinel,
                },
                data=signup_body,
                timeout=30,
            )

        signup_resp = _safe_request("注册表单", _signup, log)
        log(f"注册表单状态: {signup_resp.status_code}")
        if signup_resp.status_code == 403:
            raise RuntimeError("被 Cloudflare 拦截 (403)，请更换代理 IP")
        # 原版不检查状态码直接继续，这里只对 403 报错，其他状态码记录但不中断
        if signup_resp.status_code not in (200, 201, 302):
            log(f"注册表单返回非200: {signup_resp.status_code} {signup_resp.text[:200]}（继续尝试）")

        # 7. 提交密码
        log("[6/14] 提交密码...")
        register_body = json.dumps({"password": password, "username": email})

        def _register():
            return s.post(
                "https://auth.openai.com/api/accounts/user/register",
                headers={
                    "referer": "https://auth.openai.com/create-account/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=register_body,
                timeout=30,
            )

        pwd_resp = _safe_request("密码提交", _register, log)
        log(f"密码提交状态: {pwd_resp.status_code}")
        if pwd_resp.status_code == 403:
            raise RuntimeError("被 Cloudflare 拦截 (403)，请更换代理 IP")
        if pwd_resp.status_code not in (200, 201, 302):
            log(f"密码提交返回非200: {pwd_resp.status_code} {pwd_resp.text[:200]}（继续尝试）")

        # 8. 发送验证码
        log("[7/14] 请求发送验证码...")

        def _send_otp():
            return s.get(
                "https://auth.openai.com/api/accounts/email-otp/send",
                headers={
                    "referer": "https://auth.openai.com/create-account/password",
                    "accept": "application/json",
                },
                timeout=30,
            )

        otp_resp = _safe_request("发送验证码", _send_otp, log)
        log(f"验证码发送状态: {otp_resp.status_code}")
        if otp_resp.status_code not in (200, 201, 302):
            log(f"验证码发送返回非200: {otp_resp.status_code} {otp_resp.text[:200]}（继续尝试）")

        # 9. 获取验证码
        log(f"[8/14] 等待验证码 (超时: {email_poll_timeout}s)...")
        code = mail_client.wait_for_code(timeout=email_poll_timeout, keyword="openai")
        log(f"验证码: {code}")

        # 10. 验证验证码
        log("[9/14] 提交验证码...")
        code_body = f'{{"code":"{code}"}}'

        def _validate_otp():
            return s.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers={
                    "referer": "https://auth.openai.com/email-verification",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=code_body,
                timeout=30,
            )

        code_resp = _safe_request("验证码校验", _validate_otp, log)
        log(f"验证码校验状态: {code_resp.status_code}")
        if code_resp.status_code != 200:
            raise RuntimeError(f"验证码校验失败 ({code_resp.status_code}): {code_resp.text[:200]}")

        # 11. 创建账户
        log("[10/14] 创建账户...")
        create_body = '{"name":"Neo","birthdate":"2000-02-20"}'

        def _create_account():
            return s.post(
                "https://auth.openai.com/api/accounts/create_account",
                headers={
                    "referer": "https://auth.openai.com/about-you",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=create_body,
                timeout=30,
            )

        create_resp = _safe_request("创建账户", _create_account, log)
        log(f"账户创建状态: {create_resp.status_code}")
        if create_resp.status_code != 200:
            raise RuntimeError(f"账户创建失败: {create_resp.text[:200]}")

        # 12. 获取 workspace
        log("[11/14] 获取 workspace...")
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            raise RuntimeError("未能获取到授权 Cookie")

        # 尝试解析 JWT 的每个段来找 workspaces
        parts = auth_cookie.split(".")
        workspaces = []
        for idx, part in enumerate(parts):
            decoded = _decode_jwt_segment(part)
            if decoded:
                log(f"Cookie 段#{idx} 字段: {list(decoded.keys())}")
            ws = decoded.get("workspaces") or []
            if ws:
                workspaces = ws
                break
        if not workspaces:
            # 打印 cookie 前200字符帮助调试
            log(f"Cookie 内容 (前200字): {auth_cookie[:200]}")
            raise RuntimeError("授权 Cookie 里没有 workspace 信息")
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        if not workspace_id:
            raise RuntimeError("无法解析 workspace_id")

        # 13. 选择 workspace
        log(f"[12/14] 选择 workspace: {workspace_id}")
        select_body = f'{{"workspace_id":"{workspace_id}"}}'

        def _select_workspace():
            return s.post(
                "https://auth.openai.com/api/accounts/workspace/select",
                headers={
                    "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    "content-type": "application/json",
                },
                data=select_body,
                timeout=30,
            )

        select_resp = _safe_request("选择workspace", _select_workspace, log)
        if select_resp.status_code != 200:
            raise RuntimeError(f"选择 workspace 失败: {select_resp.status_code}")

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            raise RuntimeError("workspace/select 响应里缺少 continue_url")

        # 14. 跟随重定向链
        log("[13/14] 跟随重定向链...")
        current_url = continue_url
        for redir_i in range(8):
            def _follow_redirect(url=current_url):
                return s.get(url, allow_redirects=False, timeout=30)

            final_resp = _safe_request(f"重定向#{redir_i+1}", _follow_redirect, log)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                log("[14/14] 获取到 callback URL，交换 token...")
                token_info = submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                    proxy=proxy,
                )
                token_info["email"] = email
                token_info["password"] = password
                token_info["temp_email_provider"] = mail_client.provider["name"]
                token_info["proxy_used"] = proxy or ""
                log(f"注册成功: {email}")
                return token_info
            current_url = next_url

        raise RuntimeError("未能在重定向链中捕获到最终 Callback URL")

    finally:
        s.close()
