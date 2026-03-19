from pydantic import BaseModel
from typing import Optional
from enum import Enum


# ── Accounts ──

class AccountStatus(str, Enum):
    pending = "pending"
    registering = "registering"
    success = "success"
    failed = "failed"


class AccountOut(BaseModel):
    id: int
    email: str
    password: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    account_id: Optional[str] = None
    token_expired_at: Optional[str] = None
    temp_email_provider: Optional[str] = None
    proxy_used: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


class ExportRequest(BaseModel):
    fields: list[str]
    format: str = "json"  # json | csv | txt
    status_filter: Optional[str] = None
    ids: Optional[list[int]] = None  # 指定导出的账号 ID


# ── Email Providers ──

class ProviderOut(BaseModel):
    id: int
    name: str
    base_url: str
    origin: str
    enabled: bool
    fail_count: int
    created_at: str


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    origin: str
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    origin: Optional[str] = None
    enabled: Optional[bool] = None


# ── Proxies ──

class ProxyOut(BaseModel):
    id: int
    url: str
    proxy_type: str
    enabled: bool
    fail_count: int
    last_test_ok: Optional[bool] = None
    last_test_ms: Optional[int] = None
    last_test_info: Optional[str] = None
    last_test_at: Optional[str] = None
    created_at: str


class ProxyCreate(BaseModel):
    url: str
    proxy_type: str = "http"
    enabled: bool = True


class ProxyBatchCreate(BaseModel):
    proxies: list[str]
    proxy_type: str = "http"


class ProxyUpdate(BaseModel):
    url: Optional[str] = None
    proxy_type: Optional[str] = None
    enabled: Optional[bool] = None


# ── Settings ──

class SettingsOut(BaseModel):
    thread_count: int
    default_password: str
    default_proxy: str
    registration_delay_min: int
    registration_delay_max: int
    email_poll_timeout: int
    auto_switch_provider: bool
    email_mode: str  # "tempmail_lol" | "custom"


class SettingsUpdate(BaseModel):
    thread_count: Optional[int] = None
    default_password: Optional[str] = None
    default_proxy: Optional[str] = None
    registration_delay_min: Optional[int] = None
    registration_delay_max: Optional[int] = None
    email_poll_timeout: Optional[int] = None
    auto_switch_provider: Optional[bool] = None
    email_mode: Optional[str] = None


# ── Registration ──

class RegistrationStart(BaseModel):
    count: int = 1


class RegistrationStatus(BaseModel):
    running: bool
    total: int
    completed: int
    success: int
    failed: int
