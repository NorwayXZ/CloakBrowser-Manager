"""Kernel center: which CloakBrowser binary launches, what is cached, updates.

Wraps the cloakbrowser wrapper's own resolution (license tier, release channel,
version pin) so the panel reports exactly what the next launch will run.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .cloak_runtime import _version_core, inspect_cloak_runtime

KERNEL_DIR_RE = re.compile(r"^chromium-(\d+(?:\.\d+){3,4})(-pro)?$")

SETTING_AUTO_UPDATE = "kernel_auto_update"
SETTING_RELEASE_CHANNEL = "kernel_release_channel"
SETTING_PINNED_VERSION = "kernel_pinned_version"

ENV_AUTO_UPDATE = "CLOAKBROWSER_AUTO_UPDATE"
ENV_RELEASE_CHANNEL = "CLOAKBROWSER_RELEASE_CHANNEL"
ENV_PINNED_VERSION = "CLOAKBROWSER_VERSION"


class KernelError(Exception):
    """A kernel action the user asked for cannot be done as requested."""


@dataclass
class LicenseState:
    tier: str  # none | free | paid | invalid | unknown
    plan: str | None = None
    expires: str | None = None
    entitled_pro: bool = False

    @property
    def can_pin(self) -> bool:
        # A free GitHub key always receives the latest build; the wrapper drops pins.
        return self.tier in {"none", "paid"}


@dataclass
class KernelSettings:
    auto_update: bool = True
    release_channel: str = "stable"
    pinned_version: str | None = None


@dataclass
class InstalledKernel:
    name: str
    version: str
    pro: bool
    size_bytes: int
    in_use: bool


@dataclass
class KernelOverview:
    wrapper_version: str | None
    platform: str | None
    cache_dir: str
    license: LicenseState
    settings: KernelSettings
    version: str | None
    installed: bool
    pinned: bool
    bundled_version: str | None
    installed_kernels: list[InstalledKernel] = field(default_factory=list)


def _cli() -> Any:
    return importlib.import_module("cloakbrowser.__main__")


def resolve_license() -> LicenseState:
    """License tier the way ensure_binary sees it; the key itself never leaves here."""
    section, entitled = _cli()._resolve_license()
    raw_tier = str(section.get("tier") or "unknown")
    if not entitled:
        # The wrapper reports a keyless run as tier "free" without entitlement.
        tier = "none" if raw_tier == "free" else raw_tier
    else:
        tier = "free" if raw_tier == "free" else "paid"
    return LicenseState(
        tier=tier,
        plan=raw_tier if entitled else None,
        expires=section.get("expires"),
        entitled_pro=entitled,
    )


LICENSE_KEY_FILENAME = "license.key"
ENV_LICENSE_KEY = "CLOAKBROWSER_LICENSE_KEY"


def license_key_path() -> Path:
    """Where the wrapper reads a saved license key: its cache dir / license.key.

    Matches cloakbrowser.license resolution (param > env var > this file);
    the cache dir honours CLOAKBROWSER_CACHE_DIR, defaulting to ~/.cloakbrowser.
    """
    from cloakbrowser.config import get_cache_dir

    return get_cache_dir() / LICENSE_KEY_FILENAME


def license_key_source() -> str:
    """How the wrapper finds a key right now: "env", "file" or "none".

    Mirrors the wrapper's resolution order without ever returning the key.
    """
    if os.environ.get(ENV_LICENSE_KEY, "").strip():
        return "env"
    try:
        if license_key_path().read_text(encoding="utf-8").strip():
            return "file"
    except OSError:
        pass
    return "none"


def license_key_stored() -> bool:
    """True when a key is saved in the license.key file the panel manages."""
    return license_key_source() == "file"


def _restore_license_key_file(path: Path, previous: bytes | None) -> None:
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
    except OSError:
        pass


def save_license_key(raw_key: str) -> LicenseState:
    """Save a key where the wrapper resolves it, then report the new state.

    A key the server rejects (tier "invalid") is rolled back to whatever was
    saved before, so a typo never replaces a working key. An env-provided key
    outranks the file, so saving is refused while one is set — otherwise the
    panel would report a failure that has nothing to do with the typed key.
    """
    key = (raw_key or "").strip()
    if not key:
        raise KernelError("授权密钥是空的。")
    if license_key_source() == "env":
        raise KernelError(
            f"当前授权密钥由环境变量 {ENV_LICENSE_KEY} 提供，面板保存的密钥不会生效；"
            "请先移除该环境变量并重启 Manager，再在这里保存。"
        )
    path = license_key_path()
    previous = path.read_bytes() if path.exists() else None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass  # Windows has no POSIX modes; the profile dir is user-private.
    except OSError as exc:
        raise KernelError("保存授权密钥失败：写不进密钥文件。") from exc
    state = resolve_license()
    if state.tier == "invalid":
        _restore_license_key_file(path, previous)
        raise KernelError("这个授权密钥没有通过官方验证，已恢复之前的设置。请核对密钥后重新输入。")
    return state


def remove_license_key() -> LicenseState:
    """Delete the saved key file and report the state that leaves behind.

    An env-provided key is not the panel's to remove; the file is deleted
    either way and the returned state reflects what still resolves.
    """
    path = license_key_path()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise KernelError("删除保存的授权密钥失败。") from exc
    return resolve_license()


def effective_binary(license_state: LicenseState, *, network: bool = False) -> dict[str, Any]:
    return _cli()._effective_binary(license_state.entitled_pro, quick=not network)


def read_settings(get_setting: Callable[[str], str | None]) -> KernelSettings:
    channel = get_setting(SETTING_RELEASE_CHANNEL) or "stable"
    return KernelSettings(
        auto_update=(get_setting(SETTING_AUTO_UPDATE) or "true") != "false",
        release_channel="preview" if channel == "preview" else "stable",
        pinned_version=get_setting(SETTING_PINNED_VERSION) or None,
    )


def has_saved_settings(get_setting: Callable[[str], str | None]) -> bool:
    """Until the panel saves kernel settings, env vars set by hand stay in charge."""
    return get_setting(SETTING_AUTO_UPDATE) is not None


def apply_settings(settings: KernelSettings, environ: dict[str, str] | None = None) -> None:
    """Expose the panel's kernel settings to the wrapper through its env vars."""
    env = os.environ if environ is None else environ
    if settings.auto_update:
        env.pop(ENV_AUTO_UPDATE, None)
    else:
        env[ENV_AUTO_UPDATE] = "false"
    if settings.release_channel == "preview":
        env[ENV_RELEASE_CHANNEL] = "preview"
    else:
        env.pop(ENV_RELEASE_CHANNEL, None)
    if settings.pinned_version:
        env[ENV_PINNED_VERSION] = settings.pinned_version
    else:
        env.pop(ENV_PINNED_VERSION, None)


def validate_pin(version: str | None, license_state: LicenseState) -> str | None:
    if not version or not version.strip():
        return None
    from cloakbrowser.config import normalize_requested_version

    if not license_state.can_pin:
        raise KernelError("免费 GitHub 密钥总是使用最新内核，不能锁定版本。")
    try:
        return normalize_requested_version(version)
    except ValueError as exc:
        raise KernelError("版本号格式不对，需要完整版本，例如 154.0.8037.57.1。") from exc


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def list_installed(cache_dir: Path, in_use_dir: str | None) -> list[InstalledKernel]:
    if not cache_dir.is_dir():
        return []
    kernels = []
    for entry in cache_dir.iterdir():
        match = KERNEL_DIR_RE.fullmatch(entry.name)
        if not match or not entry.is_dir():
            continue
        kernels.append(InstalledKernel(
            name=entry.name,
            version=match.group(1),
            pro=bool(match.group(2)),
            size_bytes=_dir_size(entry),
            in_use=bool(in_use_dir) and Path(in_use_dir).name == entry.name,
        ))

    def sort_key(kernel: InstalledKernel) -> tuple[int, ...]:
        return tuple(int(part) for part in kernel.version.split("."))

    return sorted(kernels, key=sort_key, reverse=True)


def overview(settings: KernelSettings) -> KernelOverview:
    import cloakbrowser
    from cloakbrowser.config import get_cache_dir, get_platform_tag

    license_state = resolve_license()
    binary = effective_binary(license_state)
    cache_dir = get_cache_dir()
    return KernelOverview(
        wrapper_version=getattr(cloakbrowser, "__version__", None),
        platform=get_platform_tag(),
        cache_dir=str(cache_dir),
        license=license_state,
        settings=settings,
        version=binary.get("version"),
        installed=bool(binary.get("installed")),
        pinned=bool(binary.get("pinned")),
        bundled_version=binary.get("bundled_version"),
        installed_kernels=list_installed(cache_dir, binary.get("cache_dir")),
    )


def _version_newer(a: str, b: str | None) -> bool:
    from cloakbrowser.config import _version_newer as newer

    return not b or newer(a, b)


def check_latest(settings: KernelSettings) -> dict[str, Any]:
    """Ask the release server for the newest build this license would get."""
    license_state = resolve_license()
    current = effective_binary(license_state).get("version")
    if license_state.entitled_pro:
        from cloakbrowser.license import get_pro_latest_release

        release = get_pro_latest_release(settings.release_channel)
        latest = release.version if release else None
    else:
        from cloakbrowser import download

        latest = download._get_latest_chromium_version()
    if latest is None:
        raise KernelError("没有连上内核发布服务器，请检查网络后再试。")
    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": _version_newer(latest, current),
        "pinned": bool(settings.pinned_version),
    }


def update(settings: KernelSettings) -> dict[str, Any]:
    """Download the newest build for this license and verify it launches."""
    license_state = resolve_license()
    before = effective_binary(license_state).get("version")
    if settings.pinned_version:
        latest = None
    elif license_state.entitled_pro:
        from cloakbrowser.download import check_for_pro_update
        from cloakbrowser.license import resolve_license_key

        key = resolve_license_key(None)
        if not key:
            raise KernelError("没有找到 CloakBrowser 授权密钥。")
        latest = check_for_pro_update(key, settings.release_channel)
    else:
        from cloakbrowser.download import check_for_update

        latest = check_for_update()

    runtime = inspect_cloak_runtime(ensure_binary=True)
    after = runtime.binary_version or runtime.effective_version
    if not runtime.binary_verified:
        actual = runtime.binary_version or os.fspath(runtime.binary_path or "未知路径")
        raise KernelError(f"下载后的内核文件未通过版本核对：期望 {runtime.effective_version}，实际 {actual}")
    # Pro cache folders carry a "-pro" suffix the launch version lacks.
    updated = bool(latest) or _version_core(after) != _version_core(before)
    if settings.pinned_version:
        message = f"已锁定内核 {after}，不会自动换到新版本；要更新请先在内核页解除锁定。"
    elif updated:
        message = f"CloakBrowser 内核已更新并验证为 {after}；关闭运行中的浏览器后重新启动画像。"
    else:
        message = f"当前内核 {after} 已是最新，文件和版本核对通过。"
    return {
        "updated": updated,
        "wrapper_version": runtime.wrapper_version,
        "current_version": before,
        "available_version": runtime.effective_version,
        "installed_version": after,
        "platform": runtime.platform,
        "binary_verified": runtime.binary_verified,
        "restart_required": updated,
        "message": message,
    }


def delete_kernel(name: str) -> int:
    """Remove one cached kernel folder that is not the one launches use."""
    from cloakbrowser.config import get_cache_dir

    if not KERNEL_DIR_RE.fullmatch(name):
        raise KernelError("不是内核目录。")
    license_state = resolve_license()
    in_use = effective_binary(license_state).get("cache_dir")
    if in_use and Path(in_use).name == name:
        raise KernelError("这是正在使用的内核，不能删除。")
    target = get_cache_dir() / name
    if not target.is_dir():
        raise KernelError("这个内核目录已经不存在。")
    size = _dir_size(target)
    shutil.rmtree(target)
    return size
