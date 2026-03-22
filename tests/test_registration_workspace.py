import base64
import json
import unittest
from unittest import mock

from backend import registration


SENTINEL_URL = "https://sentinel.openai.com/backend-api/sentinel/req"
AUTHORIZE_CONTINUE_URL = "https://auth.openai.com/api/accounts/authorize/continue"
USER_REGISTER_URL = "https://auth.openai.com/api/accounts/user/register"
EMAIL_OTP_SEND_URL = "https://auth.openai.com/api/accounts/email-otp/send"
EMAIL_OTP_VALIDATE_URL = "https://auth.openai.com/api/accounts/email-otp/validate"
CREATE_ACCOUNT_URL = "https://auth.openai.com/api/accounts/create_account"
CLIENT_AUTH_SESSION_DUMP_URL = "https://auth.openai.com/api/accounts/client_auth_session_dump"
WORKSPACE_SELECT_URL = "https://auth.openai.com/api/accounts/workspace/select"
PASSWORDLESS_SEND_OTP_URL = "https://auth.openai.com/api/accounts/passwordless/send-otp"


def _b64url_json(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")



def make_auth_cookie(workspaces: list[str] | None = None) -> str:
    payload: dict = {"sub": "session-user"}
    if workspaces is not None:
        payload["workspaces"] = [{"id": workspace_id} for workspace_id in workspaces]
    return ".".join([
        _b64url_json({"alg": "none", "typ": "JWT"}),
        _b64url_json(payload),
        _b64url_json({"sig": "stub"}),
    ])


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None, json_error: Exception | None = None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error
        self.headers = headers or {}
        if text:
            self.text = text
        elif json_data is not None:
            self.text = json.dumps(json_data, ensure_ascii=False)
        else:
            self.text = ""

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class FakeMailClient:
    def __init__(self):
        self.provider = {"name": "mock-provider"}
        self.closed = False
        self.wait_calls: list[dict[str, object]] = []

    def create_email(self) -> str:
        return "mock@example.com"

    def wait_for_code(self, timeout: int = 120, keyword: str = "openai") -> str:
        self.wait_calls.append({"timeout": timeout, "keyword": keyword})
        return "123456"

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(
        self,
        *,
        auth_cookie: str,
        client_auth_session_dump_responses: list[FakeResponse] | None = None,
        select_responses: dict[str, FakeResponse] | None = None,
        auth_url: str,
        continue_url: str,
        callback_location: str,
        authorize_continue_responses: list[FakeResponse] | None = None,
        register_response: FakeResponse | None = None,
        create_account_response: FakeResponse | None = None,
        email_otp_send_response: FakeResponse | None = None,
        email_otp_validate_response: FakeResponse | None = None,
        passwordless_send_otp_response: FakeResponse | None = None,
        get_responses: dict[str, FakeResponse] | None = None,
        set_auth_cookie_on_create: bool = True,
        set_auth_cookie_on_validate: bool = False,
        did: str = "did-test-123",
    ):
        self.cookies: dict[str, str] = {}
        self._auth_cookie = auth_cookie
        self._client_auth_session_dump_responses = list(client_auth_session_dump_responses or [
            FakeResponse(200, json_data={"client_auth_session": {"workspaces": []}})
        ])
        self._select_responses = select_responses or {}
        self._auth_url = auth_url
        self._continue_url = continue_url
        self._callback_location = callback_location
        self._authorize_continue_responses = list(authorize_continue_responses or [
            FakeResponse(200, json_data={"ok": True})
        ])
        self._register_response = register_response or FakeResponse(200, json_data={"ok": True})
        self._create_account_response = create_account_response or FakeResponse(200, json_data={"account_created": True})
        self._email_otp_send_response = email_otp_send_response or FakeResponse(200, json_data={"sent": True})
        self._email_otp_validate_response = email_otp_validate_response or FakeResponse(200, json_data={"ok": True})
        self._passwordless_send_otp_response = passwordless_send_otp_response or FakeResponse(200, json_data={"sent": True})
        self._get_responses = dict(get_responses or {})
        self._set_auth_cookie_on_create = set_auth_cookie_on_create
        self._set_auth_cookie_on_validate = set_auth_cookie_on_validate
        self._did = did

        self.client_auth_session_dump_called = 0
        self.authorize_continue_calls = 0
        self.workspace_select_calls: list[str] = []
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.closed = False
        self.sentinel_requests: list[dict[str, str]] = []
        self.spawned_sessions: list[FakeSession] = []
        self.passwordless_session: FakeSession | None = None

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, "kwargs": kwargs})
        if url == self._auth_url:
            self.cookies["oai-did"] = self._did
            return FakeResponse(200, text="authorize ok")
        if url in self._get_responses:
            return self._get_responses[url]
        if url == EMAIL_OTP_SEND_URL:
            return self._email_otp_send_response
        if url == CLIENT_AUTH_SESSION_DUMP_URL:
            self.client_auth_session_dump_called += 1
            if self._client_auth_session_dump_responses:
                return self._client_auth_session_dump_responses.pop(0)
            raise AssertionError("Unexpected extra client_auth_session_dump call")
        if url == self._continue_url:
            return FakeResponse(302, headers={"Location": self._callback_location})
        raise AssertionError(f"Unexpected GET {url}")

    def post(self, url: str, data=None, **kwargs):
        self.post_calls.append({
            "url": url,
            "data": data,
            "headers": kwargs.get("headers") or {},
            "kwargs": kwargs,
        })
        if url == AUTHORIZE_CONTINUE_URL:
            self.authorize_continue_calls += 1
            if self._authorize_continue_responses:
                return self._authorize_continue_responses.pop(0)
            return FakeResponse(200, json_data={"ok": True})
        if url == USER_REGISTER_URL:
            return self._register_response
        if url == EMAIL_OTP_VALIDATE_URL:
            if self._set_auth_cookie_on_validate:
                self.cookies["oai-client-auth-session"] = self._auth_cookie
            return self._email_otp_validate_response
        if url == CREATE_ACCOUNT_URL:
            if self._set_auth_cookie_on_create:
                self.cookies["oai-client-auth-session"] = self._auth_cookie
            return self._create_account_response
        if url == PASSWORDLESS_SEND_OTP_URL:
            return self._passwordless_send_otp_response
        if url == WORKSPACE_SELECT_URL:
            payload = json.loads(data)
            workspace_id = payload["workspace_id"]
            self.workspace_select_calls.append(workspace_id)
            return self._select_responses.get(
                workspace_id,
                FakeResponse(400, json_data={"error": "unknown workspace"}),
            )
        raise AssertionError(f"Unexpected POST {url}")

    def close(self):
        self.closed = True


class RunRegisterWorkspaceFallbackTests(unittest.TestCase):
    auth_url = "https://auth.openai.com/authorize?client_id=test-client"
    login_auth_url = "https://auth.openai.com/authorize?client_id=login-client"
    continue_url = "https://auth.openai.com/continue/test"
    oauth = registration.OAuthStart(
        auth_url=auth_url,
        state="test-state",
        code_verifier="test-verifier",
        redirect_uri="com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
    )
    login_oauth = registration.OAuthStart(
        auth_url=login_auth_url,
        state="login-state",
        code_verifier="login-verifier",
        redirect_uri="com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
    )
    callback_location = "/callback?code=test-code&state=test-state"

    def _success_select_response(self) -> FakeResponse:
        return FakeResponse(200, json_data={"continue_url": self.continue_url})

    def _run_scenario(
        self,
        *,
        auth_cookie: str,
        client_auth_session_dump_response: FakeResponse | None = None,
        client_auth_session_dump_responses: list[FakeResponse] | None = None,
        select_responses: dict[str, FakeResponse] | None = None,
        submit_result: dict | None = None,
        authorize_continue_responses: list[FakeResponse] | None = None,
        register_response: FakeResponse | None = None,
        create_account_response: FakeResponse | None = None,
        email_otp_send_response: FakeResponse | None = None,
        get_responses: dict[str, FakeResponse] | None = None,
        passwordless_session: FakeSession | None = None,
        oauths: list[registration.OAuthStart] | None = None,
    ):
        logs: list[str] = []
        raw_logs: list[str] = []
        fake_mail = FakeMailClient()
        dump_responses = client_auth_session_dump_responses or [
            client_auth_session_dump_response
            or FakeResponse(200, json_data={"client_auth_session": {"workspaces": []}})
        ]
        session = FakeSession(
            auth_cookie=auth_cookie,
            client_auth_session_dump_responses=dump_responses,
            select_responses=select_responses,
            auth_url=self.auth_url,
            continue_url=self.continue_url,
            callback_location=self.callback_location,
            authorize_continue_responses=authorize_continue_responses,
            register_response=register_response,
            create_account_response=create_account_response,
            email_otp_send_response=email_otp_send_response,
            get_responses=get_responses,
        )
        session.spawned_sessions = [session] + ([passwordless_session] if passwordless_session else [])
        session.passwordless_session = passwordless_session
        if passwordless_session:
            passwordless_session.spawned_sessions = session.spawned_sessions
            passwordless_session.passwordless_session = passwordless_session

        submit_result = submit_result or {
            "email": "token@example.com",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
            "account_id": "account-from-token",
            "token_expired_at": "2026-03-21T00:00:00Z",
        }

        sentinel_requests: list[dict[str, str]] = []
        session.sentinel_requests = sentinel_requests
        if passwordless_session:
            passwordless_session.sentinel_requests = sentinel_requests

        def fake_post(url: str, **kwargs):
            if url == SENTINEL_URL:
                payload = json.loads(kwargs["data"])
                sentinel_requests.append(payload)
                return FakeResponse(200, json_data={"token": f"token-for-{payload['flow']}"})
            raise AssertionError(f"Unexpected curl POST {url}")

        oauth_values = oauths or [self.oauth, self.login_oauth]
        session_values = [session] + ([passwordless_session] if passwordless_session else [])

        with mock.patch.object(registration.curl_requests, "Session", side_effect=session_values), \
             mock.patch.object(registration.curl_requests, "post", side_effect=fake_post), \
             mock.patch.object(registration, "generate_oauth_url", side_effect=oauth_values), \
             mock.patch.object(registration, "submit_callback_url", return_value=submit_result) as submit_mock:
            result = registration.run_register(
                password="Passw0rd!",
                proxy=None,
                mail_client=fake_mail,
                log_fn=logs.append,
                raw_log_fn=raw_logs.append,
                email_poll_timeout=30,
            )

        return result, logs, raw_logs, session, fake_mail, submit_mock

    def _assert_log_contains(self, logs: list[str], needle: str):
        self.assertTrue(any(needle in line for line in logs), f"missing log: {needle}\nlogs={logs}")

    def _assert_common_success_logs(self, logs: list[str]):
        for needle in [
            "OAuth 参数已生成",
            "授权页 cookies:",
            "已获取 oai-did:",
            "Sentinel 响应:",
            "注册表单响应:",
            "密码提交响应:",
            "注册验证码发送响应:",
            "注册邮箱验证码已获取: 12...56",
            "账户创建响应:",
            "preauth 授权 Cookie 摘要:",
            "preauth workspace 候选:",
            "重定向#1:",
        ]:
            self._assert_log_contains(logs, needle)

    def _assert_no_plaintext_secrets(self, logs: list[str]):
        joined = "\n".join(logs)
        for secret in [
            "Passw0rd!",
            "123456",
            "access-token",
            "refresh-token",
            "id-token",
            "token-for-authorize_continue",
            "token-for-username_password_create",
        ]:
            self.assertNotIn(secret, joined)

    def test_run_register_requests_second_sentinel_for_user_register(self):
        _, logs, _, session, _, _ = self._run_scenario(
            auth_cookie=make_auth_cookie(["ws-cookie"]),
            select_responses={"ws-cookie": self._success_select_response()},
            oauths=[self.oauth],
        )

        flows = [item["flow"] for item in session.sentinel_requests]
        self.assertEqual(flows[:2], ["authorize_continue", "username_password_create"])

        register_call = next(call for call in session.post_calls if call["url"] == USER_REGISTER_URL)
        sentinel_header = register_call["headers"].get("openai-sentinel-token", "")
        self.assertIn('"flow": "username_password_create"', sentinel_header)
        self.assertIn("token-for-username_password_create", sentinel_header)
        self.assertTrue(any("注册密码阶段 Sentinel 请求:" in line for line in logs))
        self.assertTrue(any("注册密码阶段 Sentinel 响应: flow=username_password_create" in line for line in logs))

    def test_run_register_prefers_register_continue_url_before_email_otp_send(self):
        register_continue_url = "https://auth.openai.com/continue/register-otp"
        result, logs, _, session, _, _ = self._run_scenario(
            auth_cookie=make_auth_cookie(["ws-cookie"]),
            register_response=FakeResponse(200, json_data={"continue_url": register_continue_url}),
            get_responses={
                register_continue_url: FakeResponse(200, json_data={"page": {"type": "email_verification"}})
            },
            select_responses={"ws-cookie": self._success_select_response()},
            oauths=[self.oauth],
        )

        get_urls = [call["url"] for call in session.get_calls]
        self.assertIn(register_continue_url, get_urls)
        self.assertNotIn(EMAIL_OTP_SEND_URL, get_urls)
        self.assertEqual(result["continue_url"], self.continue_url)
        self.assertTrue(any("优先跟随 register.continue_url 推进状态机" in line for line in logs))

    def test_run_register_falls_back_to_email_otp_send_when_register_continue_url_missing(self):
        _, logs, _, session, _, _ = self._run_scenario(
            auth_cookie=make_auth_cookie(["ws-cookie"]),
            select_responses={"ws-cookie": self._success_select_response()},
            oauths=[self.oauth],
        )

        get_urls = [call["url"] for call in session.get_calls]
        self.assertIn(EMAIL_OTP_SEND_URL, get_urls)
        self.assertTrue(any("注册响应没有 continue_url，回退旧接口触发注册验证码发送" in line for line in logs))

    def test_run_register_prefers_cookie_workspaces_without_dump_fallback(self):
        result, logs, raw_logs, session, fake_mail, submit_mock = self._run_scenario(
            auth_cookie=make_auth_cookie(["ws-cookie"]),
            client_auth_session_dump_response=FakeResponse(200, json_data={
                "client_auth_session": {"workspaces": []}
            }),
            select_responses={"ws-cookie": self._success_select_response()},
            oauths=[self.oauth],
        )

        self.assertEqual(session.client_auth_session_dump_called, 1)
        self.assertEqual(session.workspace_select_calls, ["ws-cookie"])
        self.assertEqual(result["email"], "mock@example.com")
        self.assertEqual(result["password"], "Passw0rd!")
        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(result["account_id"], "account-from-token")
        self.assertEqual(result["workspace_id"], "ws-cookie")
        self.assertEqual(result["workspace_ids"], ["ws-cookie"])
        self.assertEqual(result["workspace_source"], "postauth.cookie.workspaces")
        self.assertEqual(result["workspace_extraction_stage"], "postauth")
        self.assertEqual(result["preauth_workspace_id"], "ws-cookie")
        self.assertEqual(result["preauth_workspace_source"], "preauth.cookie.workspaces")
        self.assertEqual(result["continue_url"], self.continue_url)
        self.assertTrue(session.closed)
        self.assertEqual(submit_mock.call_count, 1)
        self.assertIn("code=test-code", submit_mock.call_args.kwargs["callback_url"])
        self.assertIn("log", submit_mock.call_args.kwargs)
        self.assertTrue(any("preauth workspace/select 命中来源: cookie.workspaces" in line for line in logs))
        self.assertTrue(any("postauth workspace 提取来源: postauth.cookie.workspaces" in line for line in logs))
        self.assertEqual(len(fake_mail.wait_calls), 1)
        self._assert_common_success_logs(logs)
        self._assert_no_plaintext_secrets(logs)

    def test_run_register_falls_back_to_client_auth_session_dump_workspaces(self):
        result, logs, raw_logs, session, _, submit_mock = self._run_scenario(
            auth_cookie=make_auth_cookie(None),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-dump"}]}
                }),
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-dump"}]}
                }),
            ],
            select_responses={"ws-dump": self._success_select_response()},
            oauths=[self.oauth],
        )

        self.assertEqual(session.client_auth_session_dump_called, 2)
        self.assertEqual(session.workspace_select_calls, ["ws-dump"])
        self.assertEqual(result["refresh_token"], "refresh-token")
        self.assertEqual(result["workspace_id"], "ws-dump")
        self.assertEqual(result["workspace_ids"], ["ws-dump"])
        self.assertEqual(result["workspace_source"], "postauth.client_auth_session_dump.workspaces")
        self.assertEqual(result["workspace_extraction_stage"], "postauth")
        self.assertEqual(submit_mock.call_count, 1)
        self.assertTrue(any("preauth workspace/select 命中来源: client_auth_session_dump.workspaces" in line for line in logs))
        self.assertTrue(any("postauth workspace 提取来源: postauth.client_auth_session_dump.workspaces" in line for line in logs))
        self._assert_common_success_logs(logs)
        self._assert_no_plaintext_secrets(logs)

    def test_run_register_accepts_top_level_workspaces_from_client_auth_session_dump(self):
        result, logs, raw_logs, session, _, _ = self._run_scenario(
            auth_cookie=make_auth_cookie(None),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "workspaces": [{"id": "ws-top-level"}]
                }),
                FakeResponse(200, json_data={
                    "workspaces": [{"id": "ws-top-level"}]
                }),
            ],
            select_responses={"ws-top-level": self._success_select_response()},
            oauths=[self.oauth],
        )

        self.assertEqual(session.client_auth_session_dump_called, 2)
        self.assertEqual(session.workspace_select_calls, ["ws-top-level"])
        self.assertEqual(result["id_token"], "id-token")
        self.assertEqual(result["workspace_id"], "ws-top-level")
        self.assertEqual(result["workspace_source"], "postauth.client_auth_session_dump.workspaces")
        self.assertTrue(any("preauth workspace/select 命中来源: client_auth_session_dump.workspaces" in line for line in logs))
        self._assert_common_success_logs(logs)
        self._assert_no_plaintext_secrets(logs)

    def test_run_register_switches_to_passwordless_session_when_create_account_requires_add_phone(self):
        passwordless_continue_url = "https://auth.openai.com/continue/passwordless-login"
        passwordless_session = FakeSession(
            auth_cookie=make_auth_cookie(["ws-login"]),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-login"}]}
                })
            ],
            select_responses={"ws-login": self._success_select_response()},
            auth_url=self.login_auth_url,
            continue_url=self.continue_url,
            callback_location="/callback?code=test-code&state=login-state",
            authorize_continue_responses=[
                FakeResponse(200, json_data={
                    "continue_url": passwordless_continue_url,
                    "page": {"type": "passwordless"},
                })
            ],
            passwordless_send_otp_response=FakeResponse(200, json_data={
                "page": {"type": "email_verification"}
            }),
            get_responses={
                passwordless_continue_url: FakeResponse(200, json_data={"page": {"type": "passwordless"}})
            },
            set_auth_cookie_on_create=False,
            set_auth_cookie_on_validate=True,
        )

        result, logs, raw_logs, session, fake_mail, submit_mock = self._run_scenario(
            auth_cookie=make_auth_cookie(["ws-initial"]),
            create_account_response=FakeResponse(200, json_data={
                "account_created": True,
                "page": {"type": "add_phone"},
            }),
            passwordless_session=passwordless_session,
            oauths=[self.oauth, self.login_oauth],
        )

        flows = [item["flow"] for item in session.sentinel_requests]
        self.assertEqual(flows, ["authorize_continue", "username_password_create", "authorize_continue"])
        self.assertTrue(session.closed)
        self.assertTrue(passwordless_session.closed)
        self.assertEqual(len(fake_mail.wait_calls), 2)
        self.assertEqual(submit_mock.call_args.kwargs["code_verifier"], self.login_oauth.code_verifier)
        self.assertEqual(submit_mock.call_args.kwargs["expected_state"], self.login_oauth.state)
        self.assertEqual(result["workspace_id"], "ws-login")
        self.assertEqual(result["workspace_ids"], ["ws-login"])
        self.assertEqual(result["workspace_source"], "postauth.client_auth_session_dump.workspaces")
        self.assertEqual(result["preauth_workspace_id"], "ws-login")
        self.assertEqual(result["preauth_workspace_source"], "preauth.cookie.workspaces")
        self.assertEqual(passwordless_session.workspace_select_calls, ["ws-login"])
        self.assertEqual(passwordless_session.client_auth_session_dump_called, 1)
        self.assertIn(passwordless_continue_url, [call["url"] for call in passwordless_session.get_calls])
        self.assertTrue(any("账号已创建，检测到 add_phone，改用 passwordless OTP 登录绕过" in line for line in logs))
        self.assertTrue(any("passwordless OAuth 参数已生成" in line for line in logs))
        self.assertTrue(any("passwordless 登录完成，已切换到新的授权会话" in line for line in logs))
        self.assertIn("passwordless 登录验证码原文: 123456", "\n".join(raw_logs))
        self._assert_no_plaintext_secrets(logs)

    def test_run_register_raw_logs_include_unmasked_local_debug_values(self):
        _, logs, raw_logs, _, _, _ = self._run_scenario(
            auth_cookie=make_auth_cookie(None),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "client_auth_session": {
                        "session_id": "sess-123",
                        "country_code_hint": "US",
                        "workspaces": [{"id": "ws-dump"}],
                    },
                    "checksum": "checksum-xyz",
                    "session_id": "outer-session-456",
                }),
                FakeResponse(200, json_data={
                    "client_auth_session": {
                        "session_id": "sess-post-789",
                        "country_code_hint": "US",
                        "workspaces": [{"id": "ws-dump"}],
                    },
                    "checksum": "checksum-post-abc",
                    "session_id": "outer-session-post-654",
                }),
            ],
            select_responses={"ws-dump": self._success_select_response()},
            oauths=[self.oauth],
        )

        joined_logs = "\n".join(logs)
        joined_raw = "\n".join(raw_logs)

        self.assertNotIn("sess-123", joined_logs)
        self.assertNotIn("outer-session-456", joined_logs)
        self.assertNotIn("sess-post-789", joined_logs)
        self.assertNotIn("outer-session-post-654", joined_logs)
        self.assertIn("preauth client_auth_session_dump 原文:", joined_raw)
        self.assertIn("postauth client_auth_session_dump 原文:", joined_raw)
        self.assertIn("sess-123", joined_raw)
        self.assertIn("outer-session-456", joined_raw)
        self.assertIn("sess-post-789", joined_raw)
        self.assertIn("outer-session-post-654", joined_raw)
        self.assertIn("checksum-xyz", joined_raw)
        self.assertIn("checksum-post-abc", joined_raw)
        self.assertIn("注册邮箱验证码原文: 123456", joined_raw)
        self.assertIn("preauth 授权 Cookie 原文:", joined_raw)
        self.assertIn("Sentinel 响应原文:", joined_raw)

    def test_run_register_reports_attempted_sources_when_all_candidates_fail(self):
        with self.assertRaisesRegex(RuntimeError, "workspace/select 未命中任何候选") as ctx:
            self._run_scenario(
                auth_cookie=make_auth_cookie(None),
                client_auth_session_dump_responses=[
                    FakeResponse(200, json_data={
                        "client_auth_session": {"workspaces": [{"id": "ws-dump"}]}
                    })
                ],
                select_responses={
                    "ws-dump": FakeResponse(400, json_data={"error": "not allowed"}),
                },
                oauths=[self.oauth],
            )

        message = str(ctx.exception)
        self.assertIn("cookie.workspaces, client_auth_session_dump.workspaces", message)
        self.assertIn("client_auth_session_dump.workspaces", message)

    def test_run_register_preserves_dump_fetch_error_when_fallback_endpoint_fails(self):
        with self.assertRaisesRegex(RuntimeError, "无法获取可用 workspace 候选") as ctx:
            self._run_scenario(
                auth_cookie=make_auth_cookie(None),
                client_auth_session_dump_responses=[
                    FakeResponse(500, text="server exploded")
                ],
                select_responses={},
                oauths=[self.oauth],
            )

        message = str(ctx.exception)
        self.assertIn("cookie.workspaces, client_auth_session_dump.workspaces", message)
        self.assertIn("client_auth_session_dump 失败", message)
        self.assertIn("500", message)

    def test_run_register_extracts_postauth_workspace_after_token_exchange(self):
        result, logs, raw_logs, session, _, submit_mock = self._run_scenario(
            auth_cookie=make_auth_cookie(None),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-preauth"}]}
                }),
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-other"}, {"id": "ws-preauth"}]}
                }),
            ],
            select_responses={"ws-preauth": self._success_select_response()},
            oauths=[self.oauth],
        )

        self.assertEqual(session.client_auth_session_dump_called, 2)
        self.assertEqual(session.workspace_select_calls, ["ws-preauth"])
        self.assertEqual(submit_mock.call_count, 1)
        self.assertEqual(result["workspace_id"], "ws-preauth")
        self.assertEqual(result["workspace_ids"], ["ws-other", "ws-preauth"])
        self.assertEqual(result["workspace_source"], "postauth.client_auth_session_dump.workspaces")
        self.assertEqual(result["workspace_extraction_stage"], "postauth")
        self.assertEqual(result["preauth_workspace_id"], "ws-preauth")
        self.assertEqual(result["preauth_workspace_source"], "preauth.client_auth_session_dump.workspaces")
        self.assertTrue(any("token 已获取，开始提取最终 workspace 信息..." in line for line in logs))
        self.assertTrue(any("postauth workspace 数量: 2" in line for line in logs))
        self.assertTrue(any("postauth 最终 workspace:" in line for line in logs))
        self.assertIn("postauth workspace_ids 原文: ['ws-other', 'ws-preauth']", "\n".join(raw_logs))
        self._assert_no_plaintext_secrets(logs)

    def test_run_register_falls_back_to_preauth_when_postauth_extraction_fails(self):
        result, logs, raw_logs, session, _, submit_mock = self._run_scenario(
            auth_cookie=make_auth_cookie(None),
            client_auth_session_dump_responses=[
                FakeResponse(200, json_data={
                    "client_auth_session": {"workspaces": [{"id": "ws-preauth"}]}
                }),
                FakeResponse(500, text="server exploded"),
            ],
            select_responses={"ws-preauth": self._success_select_response()},
            oauths=[self.oauth],
        )

        self.assertEqual(session.client_auth_session_dump_called, 2)
        self.assertEqual(session.workspace_select_calls, ["ws-preauth"])
        self.assertEqual(submit_mock.call_count, 1)
        self.assertEqual(result["workspace_id"], "ws-preauth")
        self.assertEqual(result["workspace_ids"], ["ws-preauth"])
        self.assertEqual(result["workspace_source"], "preauth.client_auth_session_dump.workspaces")
        self.assertEqual(result["workspace_extraction_stage"], "preauth_fallback")
        self.assertEqual(result["preauth_workspace_id"], "ws-preauth")
        self.assertTrue(any("postauth workspace 提取失败，回退到 preauth bootstrap:" in line for line in logs))
        self.assertIn("postauth client_auth_session_dump 原文(text): status=500, body=server exploded", "\n".join(raw_logs))
        self._assert_no_plaintext_secrets(logs)


if __name__ == "__main__":
    unittest.main()
