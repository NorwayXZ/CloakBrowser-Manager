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
ScreenMode = Literal["real", "custom"]

_DOTTED_VERSION_RE = re.compile(r"^\d+(?:\.\d+){0,3}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


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
    # real: the screen follows this computer's display at launch, because
    # sites read the real one through CSS media queries; custom: use
    # screen_width/screen_height as configured.
    screen: ScreenMode = "real"
    # Fixed browser language (e.g. zh-CN) for the interface, navigator and
    # Intl alike, even when the exit IP is elsewhere; None follows the
    # profile's locale / exit IP. One language for all three keeps them
    # consistent: a Chinese interface over Japanese web languages is flagged.
    language: str | None = None
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

    @field_validator("language", mode="before")
    @classmethod
    def _language_tag(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        tag = str(v).strip().replace("_", "-")
        parts = tag.split("-")
        tag = parts[0].lower() + ("-" + parts[1].upper() if len(parts) > 1 else "")
        if not _LANGUAGE_RE.match(tag):
            raise ValueError("浏览器语言格式不对，例如 zh-CN")
        return tag

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
    warmup_enabled: bool = False
    warmup_daily_max: int = Field(default=1, ge=1, le=5)
    warmup_targets: list[str] = Field(default_factory=list)
    warmup_persona: str | None = Field(default=None, max_length=200)
    evolution_enabled: bool = False
    evolution_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
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
    warmup_enabled: bool | None = None
    warmup_daily_max: int | None = Field(default=None, ge=1, le=5)
    warmup_targets: list[str] | None = None
    warmup_persona: str | None = Field(default=None, max_length=200)
    evolution_enabled: bool | None = None
    evolution_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
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
    warmup_enabled: bool = False
    warmup_daily_max: int = 1
    warmup_targets: list[str] = Field(default_factory=list)
    warmup_persona: str | None = None
    evolution_enabled: bool = False

    @field_validator("evolution_enabled", mode="before")
    @classmethod
    def coerce_evolution_enabled(cls, v: object) -> bool:
        return bool(v)

    evolution_interval_hours: int = 24

    @field_validator("evolution_interval_hours", mode="before")
    @classmethod
    def coerce_evolution_interval(cls, v: object) -> int:
        return int(v) if v else 24

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

    disposable: bool = False

    @field_validator("disposable", mode="before")
    @classmethod
    def coerce_disposable(cls, v: object) -> bool:
        return bool(v)

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
    # This computer's screen, which profiles following it launch with.
    host_screen: list[int] | None = None


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


class IpQualitySignal(BaseModel):
    source: str
    status: Literal["flagged", "suspicious", "clean", "unknown"]
    detail: str


class IpQualityLink(BaseModel):
    name: str
    url: str


class IpQuality(BaseModel):
    verdict: Literal["flagged", "suspicious", "clean", "unknown"]
    summary: str
    signals: list[IpQualitySignal] = []
    links: list[IpQualityLink] = []


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
    ip_quality: IpQuality | None = None


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = None


class DeviceTemplateResponse(BaseModel):
    """One entry from the Windows device template library (backend/device_templates.py)."""

    id: str
    name: str
    family: str
    cpu: str
    gpu_vendor: str
    gpu_renderer: str
    screen_width: int
    screen_height: int
    hardware_concurrency: int
    device_memory: int
    device_scale_factor: float


class ApplyDeviceTemplateRequest(BaseModel):
    template_id: str = Field(min_length=1)


class DisposableCreateRequest(BaseModel):
    """One-click throwaway identity. Everything is optional: the persona
    defaults to US (en-US / America/New_York), region selects a coherent
    locale + timezone pair, and explicit timezone/locale win over region."""

    name: str | None = None
    region: str | None = None  # ISO country code, e.g. "JP"
    timezone: str | None = None
    locale: str | None = None


class SentenceDraftRequest(BaseModel):
    """一句话建号草案请求：只有原句，长度在端点里校验（中文 422 文案）。"""

    sentence: str = ""


class SentenceAssembledPayload(BaseModel):
    """Preview-dialog assembly returned by the client for confirm-create.

    Never trusted: the confirm endpoint re-validates every field
    server-side (hardware is rewritten from the template library,
    fingerprint options are forced to the recommended preset).
    """

    name: str | None = None
    device_profile: str | None = None
    timezone: str | None = None
    locale: str | None = None
    warmup_targets: list[str] = Field(default_factory=list)
    warmup_enabled: bool = False
    warmup_persona: str | None = None
    notes: str | None = None
    disposable: bool = False


class SentenceCreateRequest(BaseModel):
    sentence: str = ""
    assembled: SentenceAssembledPayload


class BurnRequest(BaseModel):
    confirm: bool = False


class BurnResponse(BaseModel):
    ok: bool
    profile_id: str
    user_data_dir: str
    files_removed: int
    was_running: bool


class LinkabilityProfileRef(BaseModel):
    id: str
    name: str


class LinkabilityLink(BaseModel):
    a_id: str
    b_id: str
    a_name: str
    b_name: str
    score: int
    level: str  # "strong" | "medium"
    reasons: list[str] = []
    suggestions: list[str] = []


class LinkabilityCluster(BaseModel):
    id: str
    risk: str  # "high" | "medium"
    profiles: list[LinkabilityProfileRef] = []
    links: list[LinkabilityLink] = []


class LinkabilityResponse(BaseModel):
    profile_count: int
    unclustered_count: int
    clusters: list[LinkabilityCluster] = []


class EvolutionProposalResponse(BaseModel):
    """A verified config fix waiting for the user's approval.

    Experiments only ever run on disposable clones; a proposal is the sole
    bridge back to the real profile, and it moves only when approved.
    """

    id: str
    profile_id: str
    profile_name: str | None = None
    knob: str
    label: str | None = None
    from_value: object = None
    to_value: object = None
    targets: list[str] = []
    evidence: dict = {}
    status: str  # pending | applied | dismissed
    created_at: str
    decided_at: str | None = None


class EvolutionLogResponse(BaseModel):
    id: str
    profile_id: str | None = None
    profile_name: str | None = None
    started_at: str
    finished_at: str | None = None
    trigger: str | None = None  # scheduled | manual
    outcome: str | None = None  # running | clean | unfixable_only | experiments | check_failed | deferred
    summary: str | None = None
    detail: dict = {}


class EvolutionStatusResponse(BaseModel):
    busy: bool
    profile_id: str | None = None
    profile_name: str | None = None
    lock_owner: str | None = None  # site_check | warmup | evolution
    pending_proposals: int = 0


class AutomationHoursRequest(BaseModel):
    # Local-time "HH-HH" range (e.g. "09-18", "23-07"); null/"" = no restriction.
    hours: str | None = None


class AutomationHoursResponse(BaseModel):
    hours: str | None = None
    open_now: bool = True


class AutomationStatusResponse(BaseModel):
    active: bool = False
    kind: str | None = None  # site_check | warmup | evolution
    label: str | None = None
    profile_id: str | None = None
    profile_name: str | None = None


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
    # True when a key is saved in the wrapper's license.key file (the key
    # itself is never exposed); False when keyless or env-provided.
    key_stored: bool = False


class KernelLicenseKeyRequest(BaseModel):
    license_key: str = Field(min_length=1, max_length=1024)


class KernelSettingsModel(BaseModel):
    auto_update: bool = True
    release_channel: Literal["stable", "preview"] = "stable"
    pinned_version: str | None = None


class LlmSettingsModel(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str | None = None  # write-only: omitted/empty keeps the stored key
    executor_model: str = ""  # AI 驾驶员的执行模型（与剧本生成模型分开）
    executor_effort: str = ""  # 执行模型的 effort 档位，空 = 服务商默认


class McpSettingsModel(BaseModel):
    # off = bridge refuses to serve; read-only = the 14 read tools only;
    # full = read tools + the 5 action tools. Stored as settings["mcp.mode"].
    mode: Literal["off", "read-only", "full"] = "read-only"


class McpAuditIn(BaseModel):
    """One tool call reported by the stdio MCP bridge after dispatch."""

    client_name: str | None = Field(default=None, max_length=200)
    client_version: str | None = Field(default=None, max_length=100)
    tool: str = Field(min_length=1, max_length=100)
    # Already summarised/redacted by the bridge; never raw tool arguments.
    args_summary: dict = Field(default_factory=dict)
    ok: bool = False
    reason: str | None = Field(default=None, max_length=200)
    duration_ms: int | None = Field(default=None, ge=0)


class McpAuditResponse(BaseModel):
    id: str
    ts: str
    client_name: str | None = None
    client_version: str | None = None
    tool: str
    args_summary: dict = Field(default_factory=dict)
    ok: bool = False
    reason: str | None = None
    duration_ms: int | None = None


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


class CookiePullResponse(BaseModel):
    """Cookies read back from a running browser, ready to save as config."""
    cookies: list[dict]
    cookies_json: str
    count: int


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
