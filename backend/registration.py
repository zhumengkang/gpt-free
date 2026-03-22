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


def _mask_secret(value: Any, kind: str = "secret") -> str:
    raw = str(value or "").strip()
    if not raw:
        return "(空)"

    if kind == "password":
        return f"len={len(raw)}"
    if kind == "jwt":
        return f"len={len(raw)}, segments={len(raw.split('.'))}"
    if kind == "cookie":
        return f"len={len(raw)}, segments={len(raw.split('.'))}"

    if kind in {"otp", "code"}:
        if len(raw) <= 2:
            return "*" * len(raw)
        if len(raw) <= 4:
            return f"{raw[:1]}...{raw[-1:]}"
        return f"{raw[:2]}...{raw[-2:]}"

    if len(raw) <= 4:
        return "*" * len(raw)
    if len(raw) <= 8:
        return f"{raw[:2]}...{raw[-2:]}"
    return f"{raw[:4]}...{raw[-4:]}"


def _summarize_url(url: str) -> str:
    if not url:
        return "(空 URL)"

    parsed = urllib.parse.urlparse(url)
    query_keys = list(urllib.parse.parse_qs(parsed.query, keep_blank_values=True).keys())
    fragment_keys = list(urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True).keys())

    parts: list[str] = []
    if parsed.netloc:
        parts.append(f"host={parsed.netloc}")
    if parsed.path:
        parts.append(f"path={parsed.path}")
    if query_keys:
        parts.append(f"query_keys={query_keys[:10]}")
    if fragment_keys:
        parts.append(f"fragment_keys={fragment_keys[:10]}")

    return ", ".join(parts) if parts else url[:120]


def _summarize_response(resp: Any) -> str:
    parts = [f"status={getattr(resp, 'status_code', '?')}"]

    headers = getattr(resp, "headers", {}) or {}
    location = headers.get("Location") or headers.get("location") or ""
    if location:
        parts.append(f"location={_summarize_url(location)}")

    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        parts.append(f"keys={list(payload.keys())[:10]}")
    elif isinstance(payload, list):
        parts.append(f"json_type=list,len={len(payload)}")
    elif payload is not None:
        parts.append(f"json_type={type(payload).__name__}")
    else:
        text = re.sub(r"\s+", " ", str(getattr(resp, "text", "") or "")).strip()
        parts.append(f"text_len={len(text)}" if text else "body=empty")

    return ", ".join(parts)


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


def _post_form(url: str, data: dict, proxy: str | None = None, timeout: int = 30, log=None) -> dict:
    """Token exchange — 使用 curl_cffi 走代理"""
    if log:
        log(f"token exchange 请求: {_summarize_url(url)}")
    resp = curl_requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        proxies={"http": proxy, "https": proxy} if proxy else None,
        impersonate="chrome",
        timeout=timeout,
    )
    if log:
        log(f"token exchange 响应: {_summarize_response(resp)}")
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


def submit_callback_url(*, callback_url: str, expected_state: str, code_verifier: str, redirect_uri: str = DEFAULT_REDIRECT_URI, proxy: str | None = None, log=None, raw_log=None) -> dict:
    cb = _parse_callback_url(callback_url)
    if log:
        log(
            "callback 参数摘要: "
            f"code={_mask_secret(cb['code'], 'code')}, "
            f"state={_mask_secret(cb['state'])}, "
            f"error={cb['error'] or '(空)'}"
        )
    if raw_log:
        raw_log(f"callback 参数原文: {cb}")
    if cb["error"]:
        raise RuntimeError(f"oauth error: {cb['error']}: {cb['error_description']}".strip())
    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")
    if log:
        log("callback 参数校验通过")

    token_resp = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": cb["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }, proxy=proxy, log=log)

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

    if log:
        log(
            "token 字段摘要: "
            f"access_token={_mask_secret(access_token)}, "
            f"refresh_token={_mask_secret(refresh_token)}, "
            f"id_token={_mask_secret(id_token, 'jwt')}"
        )
        log(
            "token 解析完成: "
            f"email={email or '(空)'}, "
            f"account_id={_mask_secret(account_id)}, "
            f"expired_at={expired_rfc3339}"
        )
    if raw_log:
        raw_log(f"token exchange 响应原文: {token_resp}")
        raw_log(f"id_token claims 原文: {claims}")
        raw_log(f"auth claims 原文: {auth_claims}")

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


def _request_sentinel_token(
    did: str,
    flow: str,
    proxies: Any,
    log,
    raw_log=None,
    log_prefix: str = "",
) -> str:
    prefix = str(log_prefix or "")
    log(f"{prefix}Sentinel 请求: did={_mask_secret(did)}, flow={flow}")
    sen_req_body = f'{{"p":"","id":"{did}","flow":"{flow}"}}'

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

    sen_resp = _safe_request(f"Sentinel[{flow}]", _get_sentinel, log)
    log(f"{prefix}Sentinel 响应: flow={flow}, {_summarize_response(sen_resp)}")
    if sen_resp.status_code != 200:
        raise RuntimeError(f"Sentinel 请求失败({flow}): {sen_resp.status_code} {sen_resp.text[:200]}")

    try:
        sen_payload = sen_resp.json() or {}
    except Exception as e:
        raise RuntimeError(f"Sentinel 响应不是有效 JSON({flow}): {str(e)[:160]}")

    if raw_log:
        raw_log(f"{prefix}Sentinel 响应原文: flow={flow}, payload={sen_payload}")

    sen_token = str(sen_payload.get("token") or "").strip()
    if not sen_token:
        raise RuntimeError(f"Sentinel 响应缺少 token({flow})")

    return f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "{flow}"}}'


def _passwordless_login(
    email: str,
    proxies: Any,
    mail_client: TempMailClient,
    log,
    raw_log=None,
    email_poll_timeout: int = 120,
) -> tuple[Any, Any]:
    log("检测到 add_phone，开始 passwordless 登录绕过...")
    login_oauth = generate_oauth_url()
    log(f"passwordless OAuth 参数已生成: redirect_uri={login_oauth.redirect_uri}, scope={DEFAULT_SCOPE}")
    if raw_log:
        raw_log(
            f"passwordless OAuth 原始参数: auth_url={login_oauth.auth_url}, state={login_oauth.state}, "
            f"code_verifier={login_oauth.code_verifier}, redirect_uri={login_oauth.redirect_uri}"
        )

    login_s = curl_requests.Session(proxies=proxies, impersonate="chrome", timeout=45)

    try:
        log("passwordless 访问授权页面...")
        log(f"passwordless 授权页面请求: {_summarize_url(login_oauth.auth_url)}")
        auth_resp = _safe_request("passwordless 授权页面", lambda: login_s.get(login_oauth.auth_url, timeout=30), log)
        log(f"passwordless 授权页响应: {_summarize_response(auth_resp)}")
        raw_log and raw_log(f"passwordless 授权页 cookie 原文: {dict(login_s.cookies.items())}")

        login_did = login_s.cookies.get("oai-did")
        if not login_did:
            raise RuntimeError("passwordless 未获取到 Device ID (oai-did cookie)")
        log(f"passwordless 已获取 oai-did: {_mask_secret(login_did)}")

        sentinel = _request_sentinel_token(
            login_did,
            "authorize_continue",
            proxies,
            log,
            raw_log=raw_log,
            log_prefix="passwordless ",
        )

        login_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"login"}}'

        def _submit_login_email():
            return login_s.post(
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers={
                    "referer": "https://auth.openai.com/authorize",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": sentinel,
                },
                data=login_body,
                timeout=30,
            )

        login_resp = _safe_request("passwordless 邮箱提交", _submit_login_email, log)
        log(f"passwordless 邮箱提交响应: {_summarize_response(login_resp)}")
        try:
            login_payload = login_resp.json() or {}
            if raw_log:
                raw_log(f"passwordless 邮箱提交响应原文: {login_payload}")
        except Exception:
            login_payload = {}
            if raw_log:
                raw_log(f"passwordless 邮箱提交响应原文(text): {login_resp.text}")

        if login_resp.status_code == 403:
            raise RuntimeError("passwordless 邮箱提交被 Cloudflare 拦截 (403)，请更换代理 IP")
        if login_resp.status_code not in (200, 201, 302):
            raise RuntimeError(f"passwordless 邮箱提交失败: {login_resp.status_code} {login_resp.text[:200]}")

        login_continue_url = str(login_payload.get("continue_url") or "").strip()
        if not login_continue_url:
            raise RuntimeError("passwordless 邮箱提交响应缺少 continue_url")
        log(f"passwordless continue_url: {_summarize_url(login_continue_url)}")

        def _follow_login_continue():
            return login_s.get(login_continue_url, timeout=30)

        login_continue_resp = _safe_request("passwordless continue_url", _follow_login_continue, log)
        log(f"passwordless continue_url 响应: {_summarize_response(login_continue_resp)}")
        if raw_log:
            try:
                raw_log(f"passwordless continue_url 响应原文: {login_continue_resp.json()}")
            except Exception:
                raw_log(f"passwordless continue_url 响应原文(text): {login_continue_resp.text}")

        if login_continue_resp.status_code not in (200, 201, 302):
            raise RuntimeError(
                f"passwordless continue_url 请求失败: {login_continue_resp.status_code} {login_continue_resp.text[:200]}"
            )

        def _send_passwordless_otp():
            return login_s.post(
                "https://auth.openai.com/api/accounts/passwordless/send-otp",
                headers={
                    "referer": login_continue_url,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data="{}",
                timeout=30,
            )

        otp_resp = _safe_request("passwordless 发送登录验证码", _send_passwordless_otp, log)
        log(f"passwordless 登录验证码发送响应: {_summarize_response(otp_resp)}")
        try:
            otp_payload = otp_resp.json() or {}
            if raw_log:
                raw_log(f"passwordless 登录验证码发送响应原文: {otp_payload}")
        except Exception:
            if raw_log:
                raw_log(f"passwordless 登录验证码发送响应原文(text): {otp_resp.text}")

        if otp_resp.status_code not in (200, 201, 302):
            raise RuntimeError(f"passwordless 登录验证码发送失败: {otp_resp.status_code} {otp_resp.text[:200]}")

        log(f"passwordless 等待登录验证码邮件 (最长 {email_poll_timeout}s)...")
        login_code = mail_client.wait_for_code(timeout=email_poll_timeout, keyword="openai")
        log(f"passwordless 登录验证码已获取: {_mask_secret(login_code, 'otp')}")
        if raw_log:
            raw_log(f"passwordless 登录验证码原文: {login_code}")

        validate_body = f'{{"code":"{login_code}"}}'

        def _validate_login_otp():
            return login_s.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers={
                    "referer": "https://auth.openai.com/email-verification",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=validate_body,
                timeout=30,
            )

        validate_resp = _safe_request("passwordless 登录验证码校验", _validate_login_otp, log)
        log(f"passwordless 登录验证码校验响应: {_summarize_response(validate_resp)}")
        try:
            if raw_log:
                raw_log(f"passwordless 登录验证码校验响应原文: {validate_resp.json()}")
        except Exception:
            if raw_log:
                raw_log(f"passwordless 登录验证码校验响应原文(text): {validate_resp.text}")

        if validate_resp.status_code != 200:
            raise RuntimeError(f"passwordless 登录验证码校验失败: {validate_resp.status_code} {validate_resp.text[:200]}")

        return login_s, login_oauth
    except Exception:
        login_s.close()
        raise


def _workspace_candidates_from_payload(payload: Any, source: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return candidates

    workspaces = payload.get("workspaces") or []
    if not isinstance(workspaces, list):
        return candidates

    for workspace in workspaces:
        if not isinstance(workspace, dict):
            continue
        workspace_id = str(workspace.get("id") or "").strip()
        if workspace_id:
            candidates.append({"id": workspace_id, "source": source})

    return candidates


def _stage_prefix(stage: str) -> str:
    stage_name = str(stage or "").strip()
    return f"{stage_name} " if stage_name else ""


def _qualify_workspace_source(source: str, stage: str) -> str:
    source_name = str(source or "").strip()
    stage_name = str(stage or "").strip()
    if not source_name:
        return stage_name
    if not stage_name or source_name.startswith(f"{stage_name}."):
        return source_name
    return f"{stage_name}.{source_name}"


def _append_workspace_candidates(
    workspace_candidates: list[dict[str, str]],
    seen_candidate_ids: set[str],
    candidates: list[dict[str, str]],
    log,
    raw_log=None,
    stage: str = "",
) -> None:
    prefix = _stage_prefix(stage)
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "").strip()
        source = str(candidate.get("source") or "").strip()
        if not candidate_id or not source or candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate_id)
        workspace_candidates.append({"id": candidate_id, "source": source})
        log(f"{prefix}workspace 候选: source={source}, id={_mask_secret(candidate_id)}")
        if raw_log:
            raw_log(f"{prefix}workspace 候选原文: source={source}, id={candidate_id}")


def _extract_workspace_candidates_from_auth_cookie(auth_cookie: str, log, stage: str = "") -> list[dict[str, str]]:
    prefix = _stage_prefix(stage)
    if not auth_cookie:
        return []

    parts = auth_cookie.split(".")
    log(f"{prefix}授权 Cookie 段数: {len(parts)}")

    for idx, part in enumerate(parts):
        decoded = _decode_jwt_segment(part)
        if not isinstance(decoded, dict) or not decoded:
            continue

        candidates = _workspace_candidates_from_payload(decoded, "cookie.workspaces")
        if candidates:
            log(f"{prefix}授权 Cookie 段#{idx} 命中 workspace，字段: {list(decoded.keys())[:12]}")
            log(f"{prefix}从授权 Cookie 提取到 {len(candidates)} 个 workspace 候选")
            return candidates

    log(f"{prefix}授权 Cookie 未直接提供可解析的 workspace")
    return []


def _fetch_client_auth_session_workspaces(session, log, raw_log=None, stage: str = "") -> list[dict[str, str]]:
    prefix = _stage_prefix(stage)

    def _get_client_auth_session_dump():
        return session.get(
            "https://auth.openai.com/api/accounts/client_auth_session_dump",
            headers={
                "accept": "application/json",
                "referer": "https://auth.openai.com/",
            },
            timeout=30,
        )

    resp = _safe_request("client_auth_session_dump", _get_client_auth_session_dump, log)
    log(f"{prefix}client_auth_session_dump 状态: {resp.status_code}")
    if resp.status_code != 200:
        if raw_log:
            raw_log(f"{prefix}client_auth_session_dump 原文(text): status={resp.status_code}, body={resp.text}")
        raise RuntimeError(f"client_auth_session_dump 请求失败: {resp.status_code} {resp.text[:200]}")

    try:
        payload = resp.json() or {}
    except Exception as e:
        if raw_log:
            raw_log(f"{prefix}client_auth_session_dump 原文(text): {resp.text}")
        raise RuntimeError(f"client_auth_session_dump 响应不是有效 JSON: {str(e)[:160]}")

    if not isinstance(payload, dict):
        raise RuntimeError("client_auth_session_dump 响应不是对象")

    client_auth_session = payload.get("client_auth_session")
    if client_auth_session is None and "workspaces" in payload:
        client_auth_session = payload

    if not isinstance(client_auth_session, dict):
        raise RuntimeError(
            f"client_auth_session_dump 缺少 client_auth_session，响应字段: {list(payload.keys())[:10]}"
        )

    log(f"{prefix}client_auth_session_dump 字段: {list(payload.keys())[:8]}")
    log(f"{prefix}client_auth_session 字段: {list(client_auth_session.keys())[:12]}")
    if raw_log:
        raw_log(f"{prefix}client_auth_session_dump 原文: {payload}")
        raw_log(f"{prefix}client_auth_session 原文字段值: {client_auth_session}")

    candidates = _workspace_candidates_from_payload(client_auth_session, "client_auth_session_dump.workspaces")
    log(f"{prefix}从 client_auth_session_dump 提取到 {len(candidates)} 个 workspace 候选")
    return candidates


def _collect_workspace_candidates(
    session,
    auth_cookie: str,
    log,
    raw_log=None,
    stage: str = "",
    prefer_dump: bool = False,
) -> dict[str, Any]:
    prefix = _stage_prefix(stage)
    tried_sources: list[str] = []
    workspace_candidates: list[dict[str, str]] = []
    seen_candidate_ids: set[str] = set()
    client_auth_session_error = ""

    def _record_tried(source: str):
        if source not in tried_sources:
            tried_sources.append(source)

    def _collect_from_cookie():
        _record_tried("cookie.workspaces")
        cookie_candidates = _extract_workspace_candidates_from_auth_cookie(auth_cookie, log, stage=stage)
        _append_workspace_candidates(
            workspace_candidates,
            seen_candidate_ids,
            cookie_candidates,
            log,
            raw_log=raw_log,
            stage=stage,
        )

    def _collect_from_dump():
        nonlocal client_auth_session_error
        _record_tried("client_auth_session_dump.workspaces")
        try:
            dump_candidates = _fetch_client_auth_session_workspaces(session, log, raw_log=raw_log, stage=stage)
        except Exception as e:
            client_auth_session_error = str(e)[:240]
            log(f"{prefix}获取 client_auth_session_dump 失败: {client_auth_session_error}")
            dump_candidates = []
        _append_workspace_candidates(
            workspace_candidates,
            seen_candidate_ids,
            dump_candidates,
            log,
            raw_log=raw_log,
            stage=stage,
        )

    if prefer_dump:
        _collect_from_dump()
        if not workspace_candidates:
            log(f"{prefix}client_auth_session_dump 未提取到可用 workspace，回退到授权 Cookie")
            _collect_from_cookie()
    else:
        _collect_from_cookie()
        if not workspace_candidates:
            log(f"{prefix}授权 Cookie 未提取到可用 workspace，回退到 client_auth_session_dump")
            _collect_from_dump()

    return {
        "candidates": workspace_candidates,
        "tried_sources": tried_sources,
        "client_auth_session_error": client_auth_session_error,
    }


def _extract_postauth_workspaces(
    session,
    auth_cookie: str,
    preauth_workspace_id: str,
    log,
    raw_log=None,
) -> dict[str, Any]:
    log("token 已获取，开始提取最终 workspace 信息...")
    if auth_cookie:
        log(f"postauth 授权 Cookie 摘要: {_mask_secret(auth_cookie, 'cookie')}")
        if raw_log:
            raw_log(f"postauth 授权 Cookie 原文: {auth_cookie}")

    extraction = _collect_workspace_candidates(
        session,
        auth_cookie,
        log,
        raw_log=raw_log,
        stage="postauth",
        prefer_dump=True,
    )
    candidates = extraction["candidates"]
    client_auth_session_error = extraction["client_auth_session_error"]
    tried_sources = extraction["tried_sources"]

    if not candidates:
        attempted = ", ".join(tried_sources) if tried_sources else "无"
        detail = (
            f"；client_auth_session_dump 失败: {client_auth_session_error}"
            if client_auth_session_error else ""
        )
        raise RuntimeError(f"无法提取 postauth workspace，已尝试来源: {attempted}{detail}")

    workspace_ids = [candidate["id"] for candidate in candidates]
    final_candidate = next(
        (candidate for candidate in candidates if candidate["id"] == preauth_workspace_id),
        None,
    )
    if final_candidate is None:
        final_candidate = candidates[0]

    workspace_source = _qualify_workspace_source(final_candidate["source"], "postauth")
    log(f"postauth workspace 提取来源: {workspace_source}")
    log(f"postauth workspace 数量: {len(workspace_ids)}")
    log(f"postauth 最终 workspace: {_mask_secret(final_candidate['id'])}")
    if raw_log:
        raw_log(f"postauth workspace_ids 原文: {workspace_ids}")
        raw_log(f"postauth 最终 workspace 原文: {final_candidate['id']}")

    return {
        "workspace_ids": workspace_ids,
        "workspace_id": final_candidate["id"],
        "workspace_source": workspace_source,
        "workspace_extraction_stage": "postauth",
    }


def _try_select_workspace(session, candidate_id: str, source: str, log, stage: str = "") -> dict | None:
    prefix = _stage_prefix(stage)
    log(f"{prefix}尝试 workspace/select，候选来源: {source}")
    select_body = json.dumps({"workspace_id": candidate_id})

    def _select_workspace():
        return session.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
            timeout=30,
        )

    try:
        resp = _safe_request(f"选择workspace[{source}]", _select_workspace, log)
    except Exception as e:
        log(f"{prefix}workspace/select 状态: 请求异常，来源: {source}，摘要: {str(e)[:160]}")
        return None

    payload: Any = None
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        summary_bits = [f"keys={list(payload.keys())[:5]}"]
        summary_bits.append(f"continue_url={'yes' if payload.get('continue_url') else 'no'}")
        brief_message = str(payload.get("error") or payload.get("message") or "").strip()
        if brief_message:
            summary_bits.append(f"msg={brief_message[:120]}")
        summary = ", ".join(summary_bits)
    else:
        summary = re.sub(r"\s+", " ", (resp.text or "")).strip()[:160] or "(空响应)"

    log(f"{prefix}workspace/select 状态: {resp.status_code}，来源: {source}，摘要: {summary}")
    if resp.status_code != 200 or not isinstance(payload, dict):
        return None

    continue_url = str(payload.get("continue_url") or "").strip()
    if not continue_url:
        return None

    return {
        "continue_url": continue_url,
        "source": source,
        "workspace_id": candidate_id,
    }


def run_register(
    password: str,
    proxy: Optional[str],
    mail_client: TempMailClient,
    log_fn=None,
    raw_log_fn=None,
    email_poll_timeout: int = 120,
) -> dict:
    """
    执行完整注册流程。
    返回包含 token 信息的 dict，失败抛出异常。
    """
    def log(msg: str):
        if log_fn:
            log_fn(msg)

    def raw_log(msg: str):
        if raw_log_fn:
            raw_log_fn(msg)

    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    s = curl_requests.Session(proxies=proxies, impersonate="chrome", timeout=45)

    try:
        # 0. 预检代理连通性
        if proxy:
            log("[0/14] 预检代理连通性...")
            try:
                trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=15)
                if trace.status_code != 200:
                    raise RuntimeError(f"代理预检失败: HTTP {trace.status_code}")
                loc_match = re.search(r"^loc=(.+)$", trace.text, re.MULTILINE)
                loc = loc_match.group(1) if loc_match else "未知"
                log(f"代理可用，IP 所在地: {loc}")
            except Exception as e:
                raise RuntimeError(f"代理不可用: {str(e)[:150]}")
        else:
            log("[0/14] 直连模式，跳过代理预检")

        # 1. 创建临时邮箱
        log(f"[1/14] 创建临时邮箱 (提供商: {mail_client.provider['name']})...")
        email = mail_client.create_email()
        log(f"临时邮箱: {email}")

        # 2. 生成 OAuth URL
        oauth = generate_oauth_url()
        log(f"[2/14] OAuth 参数已生成: redirect_uri={oauth.redirect_uri}, scope={DEFAULT_SCOPE}")
        raw_log(
            f"OAuth 原始参数: auth_url={oauth.auth_url}, state={oauth.state}, "
            f"code_verifier={oauth.code_verifier}, redirect_uri={oauth.redirect_uri}"
        )

        # 3. 访问授权页面
        log("[3/14] 访问授权页面...")
        log(f"授权页面请求: {_summarize_url(oauth.auth_url)}")
        auth_resp = _safe_request("授权页面", lambda: s.get(oauth.auth_url, timeout=30), log)
        log(f"授权页响应: {_summarize_response(auth_resp)}")
        cookie_keys = list(s.cookies.keys())
        log(f"授权页 cookies: keys={cookie_keys[:20]}")
        raw_log(f"授权页 cookie 原文: {dict(s.cookies.items())}")

        did = s.cookies.get("oai-did")
        if not did:
            raise RuntimeError("未获取到 Device ID (oai-did cookie)，可能是代理被 Cloudflare 拦截")
        log(f"已获取 oai-did: {_mask_secret(did)}")

        # 4. Sentinel Token
        log("[4/14] 获取 Sentinel Token...")
        sentinel = _request_sentinel_token(
            did,
            "authorize_continue",
            proxies,
            log,
            raw_log=raw_log,
        )

        # 5. 提交注册表单
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
        log(f"注册表单响应: {_summarize_response(signup_resp)}")
        try:
            raw_log(f"注册表单响应原文: {signup_resp.json()}")
        except Exception:
            raw_log(f"注册表单响应原文(text): {signup_resp.text}")
        if signup_resp.status_code == 403:
            raise RuntimeError("被 Cloudflare 拦截 (403)，请更换代理 IP")
        if signup_resp.status_code not in (200, 201, 302):
            log(f"注册表单返回非预期状态（继续尝试）: {_summarize_response(signup_resp)}")

        # 6. 提交密码
        log(f"[6/14] 提交密码: {_mask_secret(password, 'password')}")
        register_sentinel = _request_sentinel_token(
            did,
            "username_password_create",
            proxies,
            log,
            raw_log=raw_log,
            log_prefix="注册密码阶段 ",
        )
        register_body = json.dumps({"password": password, "username": email})

        def _register():
            return s.post(
                "https://auth.openai.com/api/accounts/user/register",
                headers={
                    "referer": "https://auth.openai.com/create-account/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": register_sentinel,
                },
                data=register_body,
                timeout=30,
            )

        pwd_resp = _safe_request("密码提交", _register, log)
        log(f"密码提交响应: {_summarize_response(pwd_resp)}")
        try:
            pwd_payload = pwd_resp.json() or {}
            raw_log(f"密码提交响应原文: {pwd_payload}")
        except Exception:
            pwd_payload = {}
            raw_log(f"密码提交响应原文(text): {pwd_resp.text}")
        if pwd_resp.status_code == 403:
            raise RuntimeError("被 Cloudflare 拦截 (403)，请更换代理 IP")
        if pwd_resp.status_code not in (200, 201, 302):
            log(f"密码提交返回非预期状态（继续尝试）: {_summarize_response(pwd_resp)}")

        # 7. 发送注册邮箱验证码
        log("[7/14] 请求发送注册邮箱验证码...")
        register_continue_url = str(pwd_payload.get("continue_url") or "").strip()
        otp_resp = None

        if register_continue_url:
            log(f"注册响应解析完成: continue_url={_summarize_url(register_continue_url)}")
            log("优先跟随 register.continue_url 推进状态机...")

            def _follow_register_continue():
                return s.get(register_continue_url, timeout=30)

            try:
                otp_resp = _safe_request("发送注册验证码(continue_url)", _follow_register_continue, log)
                log(f"注册验证码发送响应: {_summarize_response(otp_resp)}")
                try:
                    raw_log(f"注册验证码发送响应原文: {otp_resp.json()}")
                except Exception:
                    raw_log(f"注册验证码发送响应原文(text): {otp_resp.text}")
                if otp_resp.status_code not in (200, 201, 302):
                    log(f"register.continue_url 返回非预期状态，回退旧接口发送注册验证码: {_summarize_response(otp_resp)}")
                    otp_resp = None
            except Exception as e:
                log(f"register.continue_url 请求失败，回退旧接口发送注册验证码: {str(e)[:160]}")
                otp_resp = None
        else:
            log("注册响应没有 continue_url，回退旧接口触发注册验证码发送")

        if otp_resp is None:
            def _send_otp():
                return s.get(
                    "https://auth.openai.com/api/accounts/email-otp/send",
                    headers={
                        "referer": "https://auth.openai.com/create-account/password",
                        "accept": "application/json",
                    },
                    timeout=30,
                )

            otp_resp = _safe_request("发送注册验证码", _send_otp, log)
            log(f"注册验证码发送响应: {_summarize_response(otp_resp)}")
            try:
                raw_log(f"注册验证码发送响应原文: {otp_resp.json()}")
            except Exception:
                raw_log(f"注册验证码发送响应原文(text): {otp_resp.text}")
            if otp_resp.status_code not in (200, 201, 302):
                log(f"注册验证码发送返回非预期状态（继续尝试）: {_summarize_response(otp_resp)}")

        # 8. 获取注册邮箱验证码
        log(f"[8/14] 等待注册邮箱验证码邮件 (最长 {email_poll_timeout}s)...")
        code = mail_client.wait_for_code(timeout=email_poll_timeout, keyword="openai")
        log(f"注册邮箱验证码已获取: {_mask_secret(code, 'otp')}")
        raw_log(f"注册邮箱验证码原文: {code}")

        # 9. 验证注册邮箱验证码
        log("[9/14] 提交注册邮箱验证码...")
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

        code_resp = _safe_request("注册邮箱验证码校验", _validate_otp, log)
        log(f"注册邮箱验证码校验响应: {_summarize_response(code_resp)}")
        try:
            raw_log(f"注册邮箱验证码校验响应原文: {code_resp.json()}")
        except Exception:
            raw_log(f"注册邮箱验证码校验响应原文(text): {code_resp.text}")
        if code_resp.status_code != 200:
            raise RuntimeError(f"注册邮箱验证码校验失败 ({code_resp.status_code}): {code_resp.text[:200]}")

        # 10. 创建账户
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
        log(f"账户创建响应: {_summarize_response(create_resp)}")
        try:
            create_payload = create_resp.json() or {}
            raw_log(f"账户创建响应原文: {create_payload}")
        except Exception:
            create_payload = {}
            raw_log(f"账户创建响应原文(text): {create_resp.text}")
        if create_resp.status_code != 200:
            raise RuntimeError(f"账户创建失败: {create_resp.text[:200]}")

        create_page_type = str(((create_payload.get("page") or {}).get("type")) or "").strip()
        if create_page_type:
            log(f"账户创建 page.type: {create_page_type}")
        if create_page_type == "add_phone":
            log("账号已创建，检测到 add_phone，改用 passwordless OTP 登录绕过")
            original_session = s
            login_session, login_oauth = _passwordless_login(
                email,
                proxies,
                mail_client,
                log,
                raw_log=raw_log,
                email_poll_timeout=email_poll_timeout,
            )
            s = login_session
            oauth = login_oauth
            if original_session is not s:
                original_session.close()
            log("passwordless 登录完成，已切换到新的授权会话")

        # 11. pre-auth workspace bootstrap
        log("[11/14] 准备授权续跳 workspace...")
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            raise RuntimeError("未能获取到授权 Cookie")
        log(f"preauth 授权 Cookie 摘要: {_mask_secret(auth_cookie, 'cookie')}")
        raw_log(f"preauth 授权 Cookie 原文: {auth_cookie}")

        preauth_extraction = _collect_workspace_candidates(
            s,
            auth_cookie,
            log,
            raw_log=raw_log,
            stage="preauth",
            prefer_dump=False,
        )
        workspace_candidates = preauth_extraction["candidates"]
        tried_sources = preauth_extraction["tried_sources"]
        client_auth_session_error = preauth_extraction["client_auth_session_error"]

        if not workspace_candidates:
            attempted = ", ".join(tried_sources) if tried_sources else "无"
            detail = (
                f"；client_auth_session_dump 失败: {client_auth_session_error}"
                if client_auth_session_error else ""
            )
            raise RuntimeError(f"无法获取可用 workspace 候选，已尝试来源: {attempted}{detail}")

        # 12. pre-auth workspace select
        log(f"[12/14] 选择 pre-auth workspace，候选数: {len(workspace_candidates)}")
        select_failures: list[str] = []
        selected_workspace: dict[str, str] | None = None

        for candidate in workspace_candidates:
            source = candidate["source"]
            candidate_id = candidate["id"]
            if source not in tried_sources:
                tried_sources.append(source)

            select_result = _try_select_workspace(s, candidate_id, source, log, stage="preauth")
            if select_result:
                selected_workspace = select_result
                log(f"preauth workspace/select 命中来源: {source}")
                log(f"preauth continue_url: {_summarize_url(select_result['continue_url'])}")
                break

            select_failures.append(source)

        if not selected_workspace:
            attempted = ", ".join(tried_sources) if tried_sources else "无"
            detail = (
                f"；client_auth_session_dump 失败: {client_auth_session_error}"
                if client_auth_session_error else ""
            )
            failed_sources = ", ".join(select_failures) if select_failures else "无"
            raise RuntimeError(
                f"workspace/select 未命中任何候选，已尝试来源: {attempted}；select 失败来源: {failed_sources}{detail}"
            )

        preauth_workspace_id = selected_workspace["workspace_id"]
        preauth_workspace_source = _qualify_workspace_source(selected_workspace["source"], "preauth")
        continue_url = selected_workspace["continue_url"]

        # 13. 跟随重定向链
        log("[13/14] 跟随重定向链...")
        current_url = continue_url
        for redir_i in range(8):
            def _follow_redirect(url=current_url):
                return s.get(url, allow_redirects=False, timeout=30)

            final_resp = _safe_request(f"重定向#{redir_i+1}", _follow_redirect, log)
            location = final_resp.headers.get("Location") or ""
            next_url = urllib.parse.urljoin(current_url, location) if location else ""
            redirect_summary = [
                f"status={final_resp.status_code}",
                f"from={_summarize_url(current_url)}",
                f"has_location={'yes' if bool(location) else 'no'}",
            ]
            if next_url:
                redirect_summary.append(f"to={_summarize_url(next_url)}")
            log(f"重定向#{redir_i+1}: {', '.join(redirect_summary)}")
            raw_log(
                f"重定向#{redir_i+1} 原文: status={final_resp.status_code}, from={current_url}, "
                f"location={location}, to={next_url}"
            )

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            if "code=" in next_url and "state=" in next_url:
                log(f"[14/14] 获取到 callback URL: {_summarize_url(next_url)}")
                log("[14/14] 开始交换 token...")
                token_info = submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                    proxy=proxy,
                    log=log,
                    raw_log=raw_log,
                )
                token_info["email"] = email
                token_info["password"] = password
                token_info["temp_email_provider"] = mail_client.provider["name"]
                token_info["proxy_used"] = proxy or ""

                try:
                    final_workspace = _extract_postauth_workspaces(
                        s,
                        s.cookies.get("oai-client-auth-session") or auth_cookie,
                        preauth_workspace_id,
                        log,
                        raw_log=raw_log,
                    )
                except Exception as e:
                    fallback_reason = str(e)[:240]
                    log(f"postauth workspace 提取失败，回退到 preauth bootstrap: {fallback_reason}")
                    final_workspace = {
                        "workspace_ids": [preauth_workspace_id],
                        "workspace_id": preauth_workspace_id,
                        "workspace_source": preauth_workspace_source,
                        "workspace_extraction_stage": "preauth_fallback",
                    }

                token_info.update(final_workspace)
                token_info["preauth_workspace_id"] = preauth_workspace_id
                token_info["preauth_workspace_source"] = preauth_workspace_source
                token_info["continue_url"] = continue_url
                log(f"注册成功: {email}")
                return token_info
            current_url = next_url

        raise RuntimeError("未能在重定向链中捕获到最终 Callback URL")

    finally:
        s.close()
