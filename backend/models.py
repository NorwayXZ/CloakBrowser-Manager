"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .runtime import HostOS, RuntimeMode, ViewerMode

BrowserEngine = Literal["auto", "system_chrome", "cloakbrowser"]
LaunchMode = Literal["manual", "debug"]


class ProfileCreate(BaseModel):
    name: str
    browser_engine: BrowserEngine = "auto"
    device_profile: str | None = None
    fingerprint_seed: int | None = None  # random if not set
    proxy: str | None = None  # "http://user:pass@host:port" or null
    timezone: str | None = None  # "America/New_York"
    locale: str | None = None  # "en-US"
    platform: Literal["windows", "macos", "linux"] = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    device_memory: int | None = Field(default=None, ge=1, le=8)
    humanize: bool = True
    human_preset: Literal["default", "careful"] = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    group_name: str | None = "未分组"
    account_platform: str | None = None
    cookies_json: str | None = None
    startup_urls: list[str] = Field(default_factory=list)
    launch_args: list[str] = Field(default_factory=list)
    notes: str | None = None
    tags: list[TagCreate] | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    browser_engine: BrowserEngine | None = None
    device_profile: str | None = Field(default=None)
    fingerprint_seed: int | None = None
    proxy: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    locale: str | None = Field(default=None)
    platform: Literal["windows", "macos", "linux"] | None = None
    user_agent: str | None = Field(default=None)
    screen_width: int | None = None
    screen_height: int | None = None
    gpu_vendor: str | None = Field(default=None)
    gpu_renderer: str | None = Field(default=None)
    hardware_concurrency: int | None = Field(default=None)
    device_memory: int | None = Field(default=None, ge=1, le=8)
    humanize: bool | None = None
    human_preset: Literal["default", "careful"] | None = None
    headless: bool | None = None
    geoip: bool | None = None
    clipboard_sync: bool | None = None
    auto_launch: bool | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = Field(default=None)
    group_name: str | None = Field(default=None)
    account_platform: str | None = Field(default=None)
    cookies_json: str | None = Field(default=None)
    startup_urls: list[str] | None = None
    launch_args: list[str] | None = None
    notes: str | None = Field(default=None)
    tags: list[TagCreate] | None = None


class TagCreate(BaseModel):
    tag: str
    color: str | None = None  # hex color


class TagResponse(BaseModel):
    tag: str
    color: str | None = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    browser_engine: str | None = None
    device_profile: str | None = None
    fingerprint_seed: int
    proxy: str | None = None
    timezone: str | None = None
    locale: str | None = None
    platform: str = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    device_memory: int | None = None
    humanize: bool = True
    human_preset: str = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False
    group_name: str | None = "未分组"
    account_platform: str | None = None
    cookies_json: str | None = None
    startup_urls: list[str] = []

    @field_validator("clipboard_sync", mode="before")
    @classmethod
    def coerce_clipboard_sync(cls, v: object) -> bool:
        return True if v is None else bool(v)

    color_scheme: str | None = None
    launch_args: list[str] = []
    notes: str | None = None
    user_data_dir: str
    created_at: str
    updated_at: str
    last_opened_at: str | None = None
    deleted_at: str | None = None
    tags: list[TagResponse] = []
    status: str = "stopped"  # "running" | "stopped"
    runtime_mode: RuntimeMode = "docker"
    viewer_mode: ViewerMode = "vnc"
    vnc_ws_port: int | None = None
    cdp_url: str | None = None
    launch_mode: LaunchMode | None = None
    proxy_geo: dict | None = None


class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None
    browser_engine: str | None = None
    launch_mode: LaunchMode = "debug"


class LaunchRequest(BaseModel):
    launch_mode: LaunchMode = "manual"


class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    profiles_total: int
    host_os: HostOS
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode


class ManagerUpdateResponse(BaseModel):
    ok: bool
    updated: bool
    before: str | None = None
    after: str | None = None
    branch: str | None = None
    restart_required: bool = False
    message: str
    log: list[str] = []


class BrowserUpdateResponse(BaseModel):
    ok: bool
    updated: bool = False
    wrapper_version: str | None = None
    current_version: str | None = None
    available_version: str | None = None
    platform: str | None = None
    restart_required: bool = False
    message: str


class PreflightIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str


class PreflightResponse(BaseModel):
    status: Literal["pass", "warning", "fail"]
    browser_engine: str
    launch_mode: LaunchMode
    can_launch: bool
    issues: list[PreflightIssue] = []
    capabilities: dict = {}


class ProxyTestRequest(BaseModel):
    proxy: str


class ProxyTestResponse(BaseModel):
    ok: bool = True
    ip: str | None = None
    country: str | None = None
    country_code: str | None = None
    suggested_locale: str | None = None
    region: str | None = None
    city: str | None = None
    timezone: str | None = None
    org: str | None = None
    asn: str | None = None
    source: str = "ipapi.co"


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = None


class GroupResponse(BaseModel):
    id: str
    name: str
    color: str | None = None
    created_at: str
    updated_at: str


class ProxyPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    proxy: str
    mode: str


class ProxyPresetBulkCreate(BaseModel):
    items: list[ProxyPresetCreate] = Field(min_length=1, max_length=500)


class ProxyPresetResponse(BaseModel):
    id: str
    name: str
    proxy: str
    mode: str
    created_at: str
    updated_at: str


class ProfileStatusResponse(BaseModel):
    status: str  # "running" | "stopped"
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None
    browser_engine: str | None = None
    launch_mode: LaunchMode | None = None
    proxy_geo: dict | None = None


class ClipboardRequest(BaseModel):
    text: str = Field(max_length=1_048_576)  # 1MB max


class LoginRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    token: str | None = None


class AuthAccountUpdate(BaseModel):
    current_password: str
    username: str | None = Field(default=None, min_length=3, max_length=64)
    new_password: str | None = Field(default=None, min_length=8, max_length=256)
