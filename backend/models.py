"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .runtime import HostOS, RuntimeMode, ViewerMode

BrowserEngine = Literal["auto", "system_chrome", "cloakbrowser"]
LaunchMode = Literal["manual", "debug"]
BrowserBrand = Literal["Chrome", "Edge", "Opera", "Vivaldi"]
GeolocationMode = Literal["ip", "block", "real"]
WebRTCMode = Literal["proxy", "custom"]

_DOTTED_VERSION_RE = re.compile(r"^\d+(?:\.\d+){0,3}$")


class FingerprintOptions(BaseModel):
    """CloakBrowser binary switches beyond the core device persona.

    Every field defaults to "let the binary decide", so an empty object keeps
    the kernel's own seed-derived values.
    """

    brand: BrowserBrand | None = None
    brand_version: str | None = None
    platform_version: str | None = None
    # proxy: candidates carry the proxy exit IP; custom: they carry webrtc_ip.
    # There is no "disable": the CloakBrowser kernel ignores Chromium's WebRTC
    # IP-handling policy (switch and pref), and omitting the IP could expose
    # the real one behind a proxy.
    webrtc: WebRTCMode = "proxy"
    webrtc_ip: str | None = None
    # ip: debug launches report the exit IP's coordinates; launches without
    # CDP cannot override them and block the permission instead.
    geolocation: GeolocationMode = "ip"
    noise: bool | None = None
    speech_voices: bool = True
    storage_quota_mb: int | None = Field(default=None, ge=100, le=10_000_000)
    taskbar_height: int | None = Field(default=None, ge=0, le=300)
    windows_font_metrics: bool = False
    allow_3p_cookies: bool = False
    transparent_proxy: bool = False
    portable_cookies: bool = False

    @model_validator(mode="before")
    @classmethod
    def _legacy_webrtc_ip(cls, data: object) -> object:
        # Before the webrtc mode existed, a stored webrtc_ip meant "custom".
        if isinstance(data, dict) and "webrtc" not in data and data.get("webrtc_ip"):
            return {**data, "webrtc": "custom"}
        return data

    @model_validator(mode="after")
    def _custom_webrtc_needs_ip(self) -> "FingerprintOptions":
        if self.webrtc == "custom" and not self.webrtc_ip:
            raise ValueError("WebRTC 选了「指定 IP」，请填写 IP 地址")
        if self.webrtc != "custom":
            self.webrtc_ip = None
        return self

    @field_validator("brand_version", "platform_version", mode="before")
    @classmethod
    def _dotted_version(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return None
        if not _DOTTED_VERSION_RE.fullmatch(text):
            raise ValueError("版本号只能是数字和点，例如 154.0.8037.57 或 15.0.0")
        return text

    @field_validator("webrtc_ip", mode="before")
    @classmethod
    def _ip_address(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        if not text or text.lower() == "auto":
            return None
        try:
            return str(ipaddress.ip_address(text))
        except ValueError as exc:
            raise ValueError("WebRTC IP 必须是有效的 IPv4 或 IPv6 地址") from exc


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
    geoip: bool = True
    clipboard_sync: bool = True
    auto_launch: bool = False
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    group_name: str | None = "未分组"
    account_platform: str | None = None
    cookies_json: str | None = None
    startup_urls: list[str] = Field(default_factory=list)
    launch_args: list[str] = Field(default_factory=list)
    fingerprint_options: FingerprintOptions = Field(default_factory=FingerprintOptions)
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
    fingerprint_options: FingerprintOptions | None = None
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
    geoip: bool = True
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
    fingerprint_options: FingerprintOptions = Field(default_factory=FingerprintOptions)
    notes: str | None = None
    user_data_dir: str
    created_at: str
    updated_at: str
    last_opened_at: str | None = None
    last_exit_at: str | None = None
    last_exit_reason: str | None = None
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
    app_version: str | None = None  # None when running from a source checkout
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
    download_url: str | None = None


class BrowserUpdateResponse(BaseModel):
    ok: bool
    updated: bool = False
    wrapper_version: str | None = None
    current_version: str | None = None
    available_version: str | None = None
    installed_version: str | None = None
    platform: str | None = None
    binary_verified: bool = False
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
    proxy: str | None = None


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
    connection_mode: Literal["direct", "proxy"] | None = None


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


class KernelLicenseResponse(BaseModel):
    tier: Literal["none", "free", "paid", "invalid", "unknown"]
    plan: str | None = None
    expires: str | None = None
    can_pin: bool = False


class KernelSettingsModel(BaseModel):
    auto_update: bool = True
    release_channel: Literal["stable", "preview"] = "stable"
    pinned_version: str | None = None


class InstalledKernelResponse(BaseModel):
    name: str
    version: str
    pro: bool
    size_bytes: int
    in_use: bool


class KernelOverviewResponse(BaseModel):
    wrapper_version: str | None = None
    platform: str | None = None
    cache_dir: str
    license: KernelLicenseResponse
    settings: KernelSettingsModel
    version: str | None = None
    installed: bool = False
    pinned: bool = False
    bundled_version: str | None = None
    installed_kernels: list[InstalledKernelResponse] = []
    running_count: int = 0


class KernelCheckResponse(BaseModel):
    current_version: str | None = None
    latest_version: str
    update_available: bool
    pinned: bool = False


class CookieMergeRequest(BaseModel):
    text: str
    domain: str | None = None
    existing: str | None = None


class CookieMergeResponse(BaseModel):
    cookies_json: str
    format: Literal["json", "netscape", "header"]
    added: int
    total: int


class AutoBackupSettingsModel(BaseModel):
    enabled: bool = True
    interval_days: int = Field(default=7, ge=1, le=90)
    keep: int = Field(default=4, ge=1, le=52)
    # None or "" = keep backups only inside the data directory.
    copy_dir: str | None = None


class AutoBackupStatusResponse(AutoBackupSettingsModel):
    default_copy_dir: str
    last_at: str | None = None
    next_due_at: str | None = None
    last_error: str | None = None
    last_copy: str | None = None
    waiting_for_browsers: bool = False
