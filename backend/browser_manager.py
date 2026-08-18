"""Launch/stop/track CloakBrowser instances per profile."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from cloakbrowser import launch_persistent_context_async

from .fingerprint_report import DEFAULT_NETWORK_PROBE_URL, analyze_fingerprint, run_fingerprint_probe
from .cloak_runtime import get_effective_chromium_version
from .proxy_geo import fetch_proxy_geo
from .proxy_bridge import HttpProxyBridge
from .runtime import RuntimeConfig, resolve_runtime
from .vnc_manager import VNCManager
from .xray_runtime import XrayProcess, is_xray_link, parse_xray_link, start_xray_proxy

logger = logging.getLogger("cloakbrowser.manager.browser")

BROWSER_ENGINE_ENV = "CLOAKBROWSER_MANAGER_ENGINE"
SYSTEM_CHROME_PATH_ENV = "CLOAKBROWSER_SYSTEM_CHROME_PATH"
SESSION_RESTORE_ARG = "--restore-last-session"
SYSTEM_CHROME_BASE_ARGS = [
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    SESSION_RESTORE_ARG,
]
NATIVE_START_PAGE_TEMPLATE = "http://127.0.0.1:8080/profile/{profile_id}/start"
BLANK_PAGE_URLS = {
    "",
    "about:blank",
    "chrome://newtab/",
    "chrome://new-tab-page/",
}
COOKIE_IMPORTER_DIRNAME = "manager-cookie-importer"
MACOS_CHROMIUM_DEFAULTS_DOMAIN = "org.chromium.Chromium"
_MACOS_LOCALE_LAUNCH_LOCK = threading.Lock()


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read Chrome JSON file %s: %s", path, exc)
        return {}


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _locale_to_posix(locale: str) -> str:
    return f"{locale.replace('-', '_')}.UTF-8"


def _locale_fallbacks(locale: str) -> list[str]:
    parts = [p for p in locale.replace("_", "-").split("-") if p]
    if not parts:
        return []
    normalized = parts[0].lower()
    if len(parts) > 1:
        normalized = f"{normalized}-{parts[1].upper()}"
    languages = [normalized]
    base = parts[0].lower()
    if base not in languages:
        languages.append(base)
    return languages


def _accept_language_value(locale: str) -> str:
    return ",".join(_locale_fallbacks(locale))


def _sync_profile_locale(user_data_dir: Path, locale: str | None) -> None:
    """Persist Chrome language preferences so renderer processes follow locale."""
    if not locale:
        return

    languages = _accept_language_value(locale)
    if not languages:
        return

    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    prefs_path = default_dir / "Preferences"
    prefs = _read_json_file(prefs_path)
    intl = prefs.setdefault("intl", {})
    if isinstance(intl, dict):
        intl["accept_languages"] = languages
        intl["selected_languages"] = languages
    else:
        prefs["intl"] = {
            "accept_languages": languages,
            "selected_languages": languages,
        }
    translate = prefs.setdefault("translate", {})
    if isinstance(translate, dict):
        translate["enabled"] = False
    else:
        prefs["translate"] = {"enabled": False}
    _write_json_file(prefs_path, prefs)

    local_state_path = user_data_dir / "Local State"
    local_state = _read_json_file(local_state_path)
    state_intl = local_state.setdefault("intl", {})
    if isinstance(state_intl, dict):
        state_intl["app_locale"] = locale
    else:
        local_state["intl"] = {"app_locale": locale}
    _write_json_file(local_state_path, local_state)


def _sync_webrtc_policy(user_data_dir: Path) -> None:
    """Prefer proxied WebRTC routes so direct public IPs are not exposed."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs = _read_json_file(prefs_path)
    webrtc = prefs.setdefault("webrtc", {})
    if isinstance(webrtc, dict):
        webrtc["ip_handling_policy"] = "disable_non_proxied_udp"
        webrtc["multiple_routes_enabled"] = False
        webrtc["nonproxied_udp_enabled"] = False
    else:
        prefs["webrtc"] = {
            "ip_handling_policy": "disable_non_proxied_udp",
            "multiple_routes_enabled": False,
            "nonproxied_udp_enabled": False,
        }
    _write_json_file(prefs_path, prefs)


def _sync_session_restore(user_data_dir: Path) -> None:
    """Keep Chrome's last tabs available when a persistent profile restarts."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs = _read_json_file(prefs_path)
    session = prefs.setdefault("session", {})
    if isinstance(session, dict):
        session["restore_on_startup"] = 1
    else:
        prefs["session"] = {"restore_on_startup": 1}
    _write_json_file(prefs_path, prefs)


def _sync_native_window_placement(user_data_dir: Path, width: int, height: int) -> None:
    """Keep Chromium's saved headed window bounds aligned with the profile screen."""
    if width <= 0 or height <= 0:
        return

    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs = _read_json_file(prefs_path)
    browser = prefs.setdefault("browser", {})
    if not isinstance(browser, dict):
        browser = {}
        prefs["browser"] = browser
    placement = browser.setdefault("window_placement", {})
    if not isinstance(placement, dict):
        placement = {}
        browser["window_placement"] = placement

    left = placement.get("left", 0)
    top = placement.get("top", 30)
    if not isinstance(left, int):
        left = 0
    if not isinstance(top, int):
        top = 30
    placement.update({
        "left": left,
        "top": top,
        "right": left + width,
        "bottom": top + height,
        "maximized": False,
    })
    _write_json_file(prefs_path, prefs)


def _quarantine_macos_cloak_sync_data(
    user_data_dir: Path,
    last_exit_reason: str | None,
) -> Path | None:
    """Preserve incompatible Chromium sync metadata after a macOS SIGTRAP."""
    if not last_exit_reason or not re.search(r"(?:代码\s*-5|SIGTRAP)", last_exit_reason, re.I):
        return None

    sync_data_dir = user_data_dir / "Default" / "Sync Data"
    if not sync_data_dir.exists():
        return None

    recovery_dir = user_data_dir / ".manager-recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = recovery_dir / f"Sync Data-{stamp}"
    suffix = 1
    while destination.exists():
        destination = recovery_dir / f"Sync Data-{stamp}-{suffix}"
        suffix += 1

    shutil.move(os.fspath(sync_data_dir), os.fspath(destination))
    logger.warning(
        "Quarantined incompatible Chromium sync metadata after macOS SIGTRAP: %s",
        destination,
    )
    return destination


def _parse_profile_cookies(
    raw: str | None,
    *,
    preserve_host_only: bool = False,
) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid cookies_json ignored: %s", exc)
        return []
    if isinstance(data, dict):
        data = data.get("cookies", [])
    if not isinstance(data, list):
        return []
    cookies: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain")
        if not isinstance(name, str) or not isinstance(value, str) or not isinstance(domain, str):
            continue
        cookie = dict(item)
        if "expirationDate" in cookie and "expires" not in cookie:
            cookie["expires"] = cookie.pop("expirationDate")
        if not preserve_host_only:
            cookie.pop("hostOnly", None)
        cookies.append(cookie)
    return cookies


def _sync_cookie_import_extension(user_data_dir: Path, raw: str | None) -> Path | None:
    """Create a profile-local MV3 extension for no-CDP cookie imports."""
    extension_dir = user_data_dir / COOKIE_IMPORTER_DIRNAME
    cookies = _parse_profile_cookies(raw, preserve_host_only=True)
    if not cookies:
        shutil.rmtree(extension_dir, ignore_errors=True)
        return None

    extension_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(cookies, ensure_ascii=False, separators=(",", ":"))
    payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    payload = {"hash": payload_hash, "cookies": cookies}
    manifest = {
        "manifest_version": 3,
        "name": "CloakBrowser Cookie Importer",
        "version": "1.0.0",
        "description": "Imports the Cookie JSON saved for this local browser profile.",
        "permissions": ["cookies", "storage"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "service_worker.js"},
    }
    worker_template = r"""
const COOKIE_PAYLOAD = __COOKIE_PAYLOAD__;

const normalizeSameSite = (value) => {
  const normalized = String(value || "").toLowerCase().replaceAll("-", "_");
  if (normalized === "strict") return "strict";
  if (normalized === "lax") return "lax";
  if (["none", "no_restriction", "unspecified"].includes(normalized)) {
    return normalized === "none" ? "no_restriction" : normalized;
  }
  return undefined;
};

const cookieDetails = (cookie) => {
  const domain = String(cookie.domain || "").trim();
  const host = domain.replace(/^\./, "");
  if (!host || !cookie.name) return null;
  const path = String(cookie.path || "/");
  const details = {
    url: `${cookie.secure ? "https" : "http"}://${host}${path.startsWith("/") ? path : "/"}`,
    name: String(cookie.name),
    value: String(cookie.value || ""),
    path: path.startsWith("/") ? path : "/",
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly),
  };
  if (!cookie.hostOnly) details.domain = domain;
  const sameSite = normalizeSameSite(cookie.sameSite);
  if (sameSite) details.sameSite = sameSite;
  const expires = Number(cookie.expires ?? cookie.expirationDate);
  if (Number.isFinite(expires) && expires > 0) details.expirationDate = expires;
  return details;
};

const importCookies = async () => {
  const payload = COOKIE_PAYLOAD;
  const state = await chrome.storage.local.get("payloadHash");
  if (state.payloadHash === payload.hash) return;
  let imported = 0;
  let failed = 0;
  for (const cookie of payload.cookies || []) {
    const details = cookieDetails(cookie);
    if (!details) { failed += 1; continue; }
    try {
      await chrome.cookies.set(details);
      imported += 1;
    } catch (_) {
      failed += 1;
    }
  }
  await chrome.storage.local.set({
    payloadHash: payload.hash,
    imported,
    failed,
    completedAt: new Date().toISOString(),
  });
};

chrome.runtime.onInstalled.addListener(() => { void importCookies(); });
chrome.runtime.onStartup.addListener(() => { void importCookies(); });
void importCookies();
""".strip()
    worker = worker_template.replace(
        "__COOKIE_PAYLOAD__",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    _write_json_file(extension_dir / "manifest.json", manifest)
    _write_json_file(extension_dir / "cookies.json", payload)
    (extension_dir / "service_worker.js").write_text(worker, encoding="utf-8")
    return extension_dir


def _append_unpacked_extension_arg(args: list[str], extension_dir: Path) -> None:
    extension = os.fspath(extension_dir)
    for index, arg in enumerate(args):
        if arg.startswith("--load-extension="):
            paths = [value for value in arg.split("=", 1)[1].split(",") if value]
            if extension not in paths:
                paths.append(extension)
            args[index] = f"--load-extension={','.join(paths)}"
            return
    args.append(f"--load-extension={extension}")


def _clean_startup_urls(raw_urls: Any) -> list[str]:
    """Return only web URLs that can be passed to Chrome as startup tabs."""
    if not isinstance(raw_urls, list):
        return []
    urls: list[str] = []
    for raw in raw_urls:
        url = str(raw or "").strip()
        if not url:
            continue
        if "://" in url and not url.startswith(("http://", "https://")):
            continue
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if parsed.scheme in {"http", "https"} and parsed.netloc and not hostname.startswith("-"):
            urls.append(url)
    return urls


def _startup_urls_for_profile(profile: dict[str, Any], profile_id: str) -> list[str]:
    urls = _clean_startup_urls(profile.get("startup_urls"))
    if urls:
        return urls
    return [NATIVE_START_PAGE_TEMPLATE.format(profile_id=profile_id)]


def _playwright_proxy(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None
    settings: dict[str, str] = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        "bypass": "127.0.0.1,localhost,[::1]",
    }
    if parsed.username:
        settings["username"] = unquote(parsed.username)
    if parsed.password:
        settings["password"] = unquote(parsed.password)
    return settings


def _build_locale_timezone_env(
    *,
    locale: str | None,
    timezone: str | None,
    display: int | None,
) -> dict[str, str] | None:
    env_updates: dict[str, str] = {}
    if display is not None:
        env_updates["DISPLAY"] = f":{display}"
    if timezone:
        env_updates["TZ"] = timezone
    if locale:
        posix_locale = _locale_to_posix(locale)
        env_updates.update({
            "LANG": posix_locale,
            "LC_ALL": posix_locale,
            "LC_CTYPE": posix_locale,
            "LC_MESSAGES": posix_locale,
            "LANGUAGE": ":".join(lang.replace("-", "_") for lang in _locale_fallbacks(locale)),
        })
    if not env_updates:
        return None
    return {**os.environ, **env_updates}


def _read_macos_default(key: str) -> str | list[str] | None:
    result = subprocess.run(
        ["/usr/bin/defaults", "read", MACOS_CHROMIUM_DEFAULTS_DOMAIN, key],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if key != "AppleLanguages":
        return raw or None

    quoted = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw)
    if quoted:
        return [bytes(value, "utf-8").decode("unicode_escape") for value in quoted]
    values = [
        value.strip().strip('"')
        for value in raw.strip("()\n ").split(",")
        if value.strip()
    ]
    return values or None


def _write_macos_default(key: str, value: str | list[str] | None) -> None:
    if value is None:
        subprocess.run(
            ["/usr/bin/defaults", "delete", MACOS_CHROMIUM_DEFAULTS_DOMAIN, key],
            capture_output=True,
            check=False,
        )
        return

    command = ["/usr/bin/defaults", "write", MACOS_CHROMIUM_DEFAULTS_DOMAIN, key]
    if isinstance(value, list):
        command.extend(["-array", *value])
    else:
        command.extend(["-string", value])
    subprocess.run(command, capture_output=True, check=True)


@contextmanager
def _macos_application_locale(locale: str | None):
    """Apply Cocoa's locale while Chromium initializes, then restore defaults."""
    if sys.platform != "darwin" or not locale:
        yield
        return

    with _MACOS_LOCALE_LAUNCH_LOCK:
        previous_languages = _read_macos_default("AppleLanguages")
        previous_locale = _read_macos_default("AppleLocale")
        try:
            _write_macos_default("AppleLanguages", [locale])
            _write_macos_default("AppleLocale", locale.replace("-", "_"))
            yield
        finally:
            _write_macos_default("AppleLanguages", previous_languages)
            _write_macos_default("AppleLocale", previous_locale)


def _has_chrome_arg(args: list[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)


def _append_chrome_arg_once(args: list[str], flag: str, value: str | None = None) -> None:
    if _has_chrome_arg(args, flag):
        return
    args.append(flag if value is None else f"{flag}={value}")


def _format_proxy_endpoint(parsed: Any) -> str:
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}:{parsed.port}"


def _chrome_proxy_args(proxy: str | None) -> list[str]:
    if not proxy:
        return []
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return []
    proxy_host = parsed.hostname
    rules = (
        f"MAP * ~NOTFOUND, EXCLUDE {proxy_host}, EXCLUDE localhost, "
        "EXCLUDE 127.0.0.1, EXCLUDE ::1"
    )
    return [
        f"--proxy-server={_format_proxy_endpoint(parsed)}",
        "--proxy-bypass-list=127.0.0.1;localhost;[::1]",
        f"--host-resolver-rules={rules}",
    ]


def _extract_remote_debugging_port(args: list[str]) -> int | None:
    for arg in args:
        if arg.startswith("--remote-debugging-port="):
            raw = arg.split("=", 1)[1]
            return int(raw)
    return None


def _resolve_system_chrome_executable() -> Path:
    configured = os.environ.get(SYSTEM_CHROME_PATH_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
        raise RuntimeError(f"{SYSTEM_CHROME_PATH_ENV} points to a missing file: {path}")

    candidates: list[Path] = []
    if os.name == "nt":
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if base:
                candidates.append(
                    Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )
        for name in ("chrome.exe", "chrome"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ])
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "Google Chrome was not found. Install Chrome or set "
        f"{SYSTEM_CHROME_PATH_ENV} to the Chrome executable path."
    )


def _build_system_chrome_command_args(
    *,
    user_data_dir: str | os.PathLike[str],
    cdp_port: int | None,
    headless: bool,
    proxy: str | None,
    args: list[str] | None,
    user_agent: str | None,
    viewport: Any,
    locale: str | None,
) -> list[str]:
    chrome_args = [f"--user-data-dir={os.fspath(user_data_dir)}"]
    chrome_args.extend(args or [])

    if cdp_port is not None:
        _append_chrome_arg_once(chrome_args, "--remote-debugging-address", "127.0.0.1")
        _append_chrome_arg_once(chrome_args, "--remote-debugging-port", str(cdp_port))
    _append_chrome_arg_once(chrome_args, "--no-first-run")
    _append_chrome_arg_once(chrome_args, "--no-default-browser-check")

    if headless:
        _append_chrome_arg_once(chrome_args, "--headless", "new")
        if viewport and isinstance(viewport, dict):
            width = viewport.get("width")
            height = viewport.get("height")
            if width and height:
                _append_chrome_arg_once(chrome_args, "--window-size", f"{width},{height}")

    if proxy and not _has_chrome_arg(chrome_args, "--proxy-server"):
        chrome_args.extend(_chrome_proxy_args(proxy))
    if user_agent:
        _append_chrome_arg_once(chrome_args, "--user-agent", user_agent)
    if locale:
        _append_chrome_arg_once(chrome_args, "--lang", locale)
        _append_chrome_arg_once(chrome_args, "--accept-lang", _accept_language_value(locale))

    return chrome_args


def _chrome_popen_kwargs(env: dict[str, str] | None = None) -> dict[str, Any]:
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env or os.environ.copy(),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    return popen_kwargs


def _sync_macos_window_after_launch(process: subprocess.Popen[Any], viewport: Any) -> None:
    """Normalize a restored macOS window without opening a DevTools channel."""
    if sys.platform != "darwin" or not isinstance(viewport, dict):
        return
    width = viewport.get("width")
    height = viewport.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return

    script = f'''tell application "System Events"
  set targetProcess to first application process whose unix id is {process.pid}
  set frontmost of targetProcess to true
  repeat 30 times
    if (count of windows of targetProcess) > 0 then
      set position of front window of targetProcess to {{30, 30}}
      set size of front window of targetProcess to {{{width}, {height}}}
      exit repeat
    end if
    delay 0.1
  end repeat
end tell'''
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not normalize macOS browser window: %s", exc)


def _has_restorable_chrome_session(user_data_dir: Path) -> bool:
    default_dir = user_data_dir / "Default"
    session_candidates = [
        default_dir / "Current Session",
        default_dir / "Current Tabs",
        default_dir / "Last Session",
        default_dir / "Last Tabs",
    ]
    sessions_dir = default_dir / "Sessions"
    if sessions_dir.exists():
        session_candidates.extend(sessions_dir.glob("Session_*"))
        session_candidates.extend(sessions_dir.glob("Tabs_*"))

    for path in session_candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def _launch_system_chrome_manual_process(
    *,
    user_data_dir: str | os.PathLike[str],
    headless: bool = False,
    proxy: str | None = None,
    args: list[str] | None = None,
    user_agent: str | None = None,
    viewport: Any = None,
    locale: str | None = None,
    env: dict[str, str] | None = None,
    start_url: str | None = None,
    start_urls: list[str] | None = None,
    **_: Any,
) -> subprocess.Popen[Any]:
    """Launch installed Chrome without opening a DevTools/CDP control channel."""
    if headless:
        raise ValueError("Manual system Chrome launch does not support headless mode")

    chrome_path = _resolve_system_chrome_executable()
    chrome_args = _build_system_chrome_command_args(
        user_data_dir=user_data_dir,
        cdp_port=None,
        headless=headless,
        proxy=proxy,
        args=args,
        user_agent=user_agent,
        viewport=viewport,
        locale=locale,
    )
    if start_url:
        chrome_args.append(start_url)
    for url in start_urls or []:
        chrome_args.append(url)
    process = subprocess.Popen(
        [os.fspath(chrome_path), *chrome_args],
        **_chrome_popen_kwargs(env),
    )
    _sync_macos_window_after_launch(process, viewport)
    return process


def _launch_cloakbrowser_manual_process(
    *,
    user_data_dir: str | os.PathLike[str],
    headless: bool = False,
    proxy: str | None = None,
    args: list[str] | None = None,
    user_agent: str | None = None,
    viewport: Any = None,
    locale: str | None = None,
    timezone: str | None = None,
    env: dict[str, str] | None = None,
    start_urls: list[str] | None = None,
    **_: Any,
) -> subprocess.Popen[Any]:
    """Launch the patched CloakBrowser binary without Playwright or CDP."""
    if headless:
        raise ValueError("Manual CloakBrowser launch does not support headless mode")

    from cloakbrowser import build_args
    from cloakbrowser.download import ensure_binary

    browser_path = Path(ensure_binary())
    if not browser_path.exists():
        raise RuntimeError(f"CloakBrowser binary was not found: {browser_path}")

    extra_args = list(args or [])
    if proxy and not _has_chrome_arg(extra_args, "--proxy-server"):
        extra_args.extend(_chrome_proxy_args(proxy))
    if user_agent:
        _append_chrome_arg_once(extra_args, "--user-agent", user_agent)
    _append_chrome_arg_once(extra_args, "--user-data-dir", os.fspath(user_data_dir))
    _append_chrome_arg_once(extra_args, "--no-first-run")
    _append_chrome_arg_once(extra_args, "--no-default-browser-check")
    if viewport and isinstance(viewport, dict):
        width = viewport.get("width")
        height = viewport.get("height")
        if width and height:
            _append_chrome_arg_once(extra_args, "--window-size", f"{width},{height}")

    if sys.platform == "darwin":
        from cloakbrowser.config import binary_supports_maximized_window

        start_maximized = binary_supports_maximized_window()
    else:
        start_maximized = False

    chrome_args = build_args(
        sys.platform != "darwin",
        extra_args,
        timezone=timezone,
        locale=locale,
        headless=False,
        start_maximized=start_maximized,
    )
    chrome_args.extend(start_urls or [])
    with _macos_application_locale(locale):
        process = subprocess.Popen(
            [os.fspath(browser_path), *chrome_args],
            **_chrome_popen_kwargs(env),
        )
        if sys.platform == "darwin" and locale:
            # Cocoa reads per-app language defaults during early startup. Keep
            # them in place until the browser process has initialized them.
            time.sleep(0.35)
        _sync_macos_window_after_launch(process, viewport)
        return process


async def _terminate_process_async(process: subprocess.Popen[Any] | None) -> None:
    if process is None:
        return
    if process.poll() is not None:
        try:
            await asyncio.to_thread(process.wait, 0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        await asyncio.to_thread(process.wait, 5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            return
        try:
            await asyncio.to_thread(process.wait, 5)
        except (OSError, subprocess.TimeoutExpired):
            pass


async def _connect_over_cdp_when_ready(
    playwright_runtime: Any,
    cdp_port: int,
    process: subprocess.Popen[Any],
    *,
    timeout: float | None = None,
) -> Any:
    timeout = CDP_READY_TIMEOUT if timeout is None else timeout
    endpoint = f"http://127.0.0.1:{cdp_port}"
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"System Chrome exited before CDP became ready (code {process.returncode})"
            )
        try:
            return await playwright_runtime.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.2)
    raise TimeoutError(f"System Chrome CDP endpoint was not ready at {endpoint}") from last_error


async def _launch_system_chrome_persistent_context_async(
    *,
    user_data_dir: str | os.PathLike[str],
    headless: bool = False,
    proxy: str | None = None,
    args: list[str] | None = None,
    user_agent: str | None = None,
    viewport: Any = None,
    locale: str | None = None,
    timezone: str | None = None,
    color_scheme: str | None = None,
    env: dict[str, str] | None = None,
    humanize: bool = False,
    human_preset: str = "default",
    **_: Any,
) -> Any:
    """Launch installed Chrome as a normal process, then attach over CDP."""
    from playwright.async_api import async_playwright

    raw_args = args or []
    cdp_port = _extract_remote_debugging_port(raw_args)
    if cdp_port is None:
        raise ValueError("System Chrome launch requires --remote-debugging-port")

    chrome_path = _resolve_system_chrome_executable()
    chrome_args = _build_system_chrome_command_args(
        user_data_dir=user_data_dir,
        cdp_port=cdp_port,
        headless=headless,
        proxy=proxy,
        args=raw_args,
        user_agent=user_agent,
        viewport=viewport,
        locale=locale,
    )

    process: subprocess.Popen[Any] | None = None
    pw = await async_playwright().start()
    browser: Any | None = None
    try:
        process = subprocess.Popen(
            [os.fspath(chrome_path), *chrome_args],
            **_chrome_popen_kwargs(env),
        )
        browser = await _connect_over_cdp_when_ready(pw, cdp_port, process)
        if not browser.contexts:
            raise RuntimeError("System Chrome did not expose a default browser context")
        context = browser.contexts[0]
    except Exception:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await _terminate_process_async(process)
        await pw.stop()
        raise

    original_close = context.close
    closed = False

    async def close_with_cleanup(*, reason: str | None = None) -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            try:
                if reason is None:
                    await original_close()
                else:
                    await original_close(reason=reason)
            except Exception as exc:
                logger.debug("Native Chrome context close failed: %s", exc)
            if browser is not None:
                try:
                    await browser.close()
                except Exception as exc:
                    logger.debug("Native Chrome CDP close failed: %s", exc)
        finally:
            await _terminate_process_async(process)
            await pw.stop()

    context.close = close_with_cleanup
    context._cloak_browser_process = process
    context._cloak_browser = browser
    context._cloak_playwright = pw

    if humanize:
        try:
            from cloakbrowser.human import patch_context_async
            from cloakbrowser.human.config import resolve_config

            patch_context_async(context, resolve_config(human_preset))
        except Exception as exc:
            logger.debug("Humanize patch skipped for system Chrome: %s", exc)

    return context


async def _launch_cloakbrowser_persistent_context_async(
    *,
    user_data_dir: str | os.PathLike[str],
    headless: bool = False,
    proxy: str | None = None,
    args: list[str] | None = None,
    user_agent: str | None = None,
    viewport: Any = None,
    locale: str | None = None,
    timezone: str | None = None,
    env: dict[str, str] | None = None,
    humanize: bool = False,
    human_preset: str = "default",
    **_: Any,
) -> Any:
    """Launch CloakBrowser directly, then attach CDP for explicit debug mode."""
    from playwright.async_api import async_playwright

    raw_args = args or []
    cdp_port = _extract_remote_debugging_port(raw_args)
    if cdp_port is None:
        raise ValueError("CloakBrowser debug launch requires --remote-debugging-port")

    process: subprocess.Popen[Any] | None = None
    pw = await async_playwright().start()
    browser: Any | None = None
    try:
        process = _launch_cloakbrowser_manual_process(
            user_data_dir=user_data_dir,
            headless=headless,
            proxy=proxy,
            args=raw_args,
            user_agent=user_agent,
            viewport=viewport,
            locale=locale,
            timezone=timezone,
            env=env,
        )
        browser = await _connect_over_cdp_when_ready(pw, cdp_port, process)
        if not browser.contexts:
            raise RuntimeError("CloakBrowser did not expose a default browser context")
        context = browser.contexts[0]
    except Exception:
        if browser is not None:
            with suppress(Exception):
                await browser.close()
        await _terminate_process_async(process)
        await pw.stop()
        raise

    original_close = context.close
    closed = False

    async def close_with_cleanup(*, reason: str | None = None) -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            try:
                if reason is None:
                    await original_close()
                else:
                    await original_close(reason=reason)
            except Exception as exc:
                logger.debug("Native CloakBrowser context close failed: %s", exc)
            if browser is not None:
                with suppress(Exception):
                    await browser.close()
        finally:
            await _terminate_process_async(process)
            await pw.stop()

    context.close = close_with_cleanup
    context._cloak_browser_process = process
    context._cloak_browser = browser
    context._cloak_playwright = pw

    if humanize:
        try:
            from cloakbrowser.human import patch_context_async
            from cloakbrowser.human.config import resolve_config

            patch_context_async(context, resolve_config(human_preset))
        except Exception as exc:
            logger.debug("Humanize patch skipped for CloakBrowser: %s", exc)

    return context


async def _open_native_start_page(
    context: Any,
    profile_id: str,
    startup_urls: list[str] | None = None,
) -> None:
    """Open startup pages only when no real tab was restored."""
    try:
        pages = list(getattr(context, "pages", []) or [])
        if any(str(getattr(page, "url", "") or "") not in BLANK_PAGE_URLS for page in pages):
            return
        urls = startup_urls or [NATIVE_START_PAGE_TEMPLATE.format(profile_id=profile_id)]
        first_page = pages[0] if pages else await context.new_page()
        for idx, url in enumerate(urls):
            page = first_page if idx == 0 else await context.new_page()
            if idx == 0 and str(getattr(page, "url", "") or "") not in BLANK_PAGE_URLS:
                continue
            await page.goto(url, wait_until="domcontentloaded")
        try:
            await first_page.bring_to_front()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Could not open native start page for %s: %s", profile_id, exc)


def _build_worker_fingerprint_patch(payload: dict[str, Any]) -> str:
    """Patch locale/timezone surfaces inside classic dedicated workers."""
    return """
        (() => {
            const cfg = __PAYLOAD__;
            const locale = cfg.locale;
            const languages = cfg.languages || [];
            const timezone = cfg.timezone;
            const profilePlatform = cfg.platform;
            const nativeToString = Function.prototype.toString;
            const nativeSources = new WeakMap();

            const markNative = (fn, name) => {
                try {
                    nativeSources.set(fn, `function ${name}() { [native code] }`);
                } catch (_) {}
                return fn;
            };

            const patchedFunctionToString = function toString() {
                if (nativeSources.has(this)) return nativeSources.get(this);
                return nativeToString.call(this);
            };
            markNative(patchedFunctionToString, 'toString');
            try {
                Object.defineProperty(Function.prototype, 'toString', {
                    value: patchedFunctionToString,
                    configurable: true,
                    writable: true,
                });
            } catch (_) {}

            const defineGetter = (proto, name, getter) => {
                try {
                    Object.defineProperty(proto, name, {
                        get: markNative(getter, `get ${name}`),
                        configurable: true,
                    });
                } catch (_) {}
            };

            const clientHintsPlatform = () => {
                if (profilePlatform === 'macos') return 'macOS';
                if (profilePlatform === 'windows') return 'Windows';
                if (profilePlatform === 'linux') return 'Linux';
                if (/Mac/.test(navigator.platform || '')) return 'macOS';
                if (/Win/.test(navigator.platform || '')) return 'Windows';
                if (/Linux/.test(navigator.platform || '')) return 'Linux';
                return 'Unknown';
            };

            const buildUserAgentData = () => {
                const match = String(navigator.userAgent || '').match(/Chrome\/(\d+)(?:\.([0-9.]+))?/);
                const major = match ? match[1] : '145';
                const full = match ? `${major}.${match[2] || '0.0.0'}` : '145.0.0.0';
                const brands = [
                    { brand: 'Not:A-Brand', version: '99' },
                    { brand: 'Google Chrome', version: major },
                    { brand: 'Chromium', version: major },
                ];
                const fullVersionList = brands.map((brand) => ({
                    brand: brand.brand,
                    version: brand.brand === 'Not:A-Brand' ? '99.0.0.0' : full,
                }));
                const platform = clientHintsPlatform();
                return {
                    brands,
                    mobile: false,
                    platform,
                    getHighEntropyValues: markNative(async function getHighEntropyValues(hints) {
                        const values = {
                            brands,
                            mobile: false,
                            platform,
                            architecture: platform === 'macOS' ? 'arm' : 'x86',
                            bitness: '64',
                            model: '',
                            platformVersion: platform === 'macOS' ? '15.0.0' : '10.0.0',
                            uaFullVersion: full,
                            fullVersionList,
                            wow64: false,
                        };
                        const result = { brands, mobile: false, platform };
                        for (const hint of hints || []) {
                            if (hint in values) result[hint] = values[hint];
                        }
                        return result;
                    }, 'getHighEntropyValues'),
                    toJSON: markNative(function toJSON() {
                        return { brands, mobile: false, platform };
                    }, 'toJSON'),
                };
            };

            const defaultLocales = (locales) => {
                if (!locale) return locales;
                if (locales === undefined || locales === null) return locale;
                if (Array.isArray(locales) && locales.length === 0) return locale;
                return locales;
            };

            const patchIntlConstructor = (name, configureOptions) => {
                const Original = Intl[name];
                if (typeof Original !== 'function') return;

                const Patched = function(locales, options) {
                    const nextOptions = Object.assign({}, options || {});
                    if (configureOptions) configureOptions(nextOptions);
                    return new Original(defaultLocales(locales), nextOptions);
                };

                try {
                    Object.setPrototypeOf(Patched, Original);
                    Patched.prototype = Original.prototype;
                    if (typeof Original.supportedLocalesOf === 'function') {
                        Object.defineProperty(Patched, 'supportedLocalesOf', {
                            value: markNative(function supportedLocalesOf(locales, options) {
                                return Original.supportedLocalesOf(defaultLocales(locales), options);
                            }, 'supportedLocalesOf'),
                            configurable: true,
                        });
                    }
                    Object.defineProperty(Patched, 'name', { value: name });
                    Object.defineProperty(Patched, 'length', { value: Original.length });
                    Object.defineProperty(Intl, name, {
                        value: markNative(Patched, name),
                        configurable: true,
                        writable: true,
                    });
                } catch (_) {}
            };

            if (locale && typeof navigator === 'object') {
                const navProto = Object.getPrototypeOf(navigator);
                defineGetter(navProto, 'language', function language() {
                    return locale;
                });
                defineGetter(navProto, 'languages', function languagesGetter() {
                    return languages.slice();
                });
                if (!Object.getOwnPropertyDescriptor(Navigator.prototype, 'userAgentData') && typeof isSecureContext === 'boolean' && isSecureContext) {
                    defineGetter(navProto, 'userAgentData', function userAgentData() {
                        return buildUserAgentData();
                    });
                }

                patchIntlConstructor('NumberFormat');
                patchIntlConstructor('Collator');
                patchIntlConstructor('PluralRules');
                patchIntlConstructor('RelativeTimeFormat');
                patchIntlConstructor('ListFormat');
                patchIntlConstructor('DisplayNames');
                patchIntlConstructor('Segmenter');
            }

            if (timezone) {
                const OriginalDateTimeFormat = Intl.DateTimeFormat;
                const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
                const originalToString = Date.prototype.toString;
                const originalToDateString = Date.prototype.toDateString;
                const originalToTimeString = Date.prototype.toTimeString;
                const originalToLocaleString = Date.prototype.toLocaleString;
                const originalToLocaleDateString = Date.prototype.toLocaleDateString;
                const originalToLocaleTimeString = Date.prototype.toLocaleTimeString;
                const originalGetTime = Date.prototype.getTime;
                const isValidDate = (date) => {
                    try {
                        return Number.isFinite(originalGetTime.call(date));
                    } catch (_) {
                        return false;
                    }
                };

                patchIntlConstructor('DateTimeFormat', (nextOptions) => {
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                });

                const offsetFormatter = new OriginalDateTimeFormat('en-US', {
                    timeZone: timezone,
                    hour12: false,
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                });

                const offsetFor = (date) => {
                    if (!isValidDate(date)) {
                        return originalGetTimezoneOffset.call(date);
                    }
                    try {
                        const parts = Object.fromEntries(
                            offsetFormatter.formatToParts(date)
                                .filter((part) => part.type !== 'literal')
                                .map((part) => [part.type, part.value])
                        );
                        const hour = Number(parts.hour === '24' ? '0' : parts.hour);
                        const localAsUtc = Date.UTC(
                            Number(parts.year),
                            Number(parts.month) - 1,
                            Number(parts.day),
                            hour,
                            Number(parts.minute),
                            Number(parts.second)
                        );
                        return Math.round((date.getTime() - localAsUtc) / 60000);
                    } catch (_) {
                        return originalGetTimezoneOffset.call(date);
                    }
                };

                Date.prototype.getTimezoneOffset = markNative(function getTimezoneOffset() {
                    return offsetFor(this);
                }, 'getTimezoneOffset');

                const englishPartsFormatter = new OriginalDateTimeFormat('en-US', {
                    timeZone: timezone,
                    hour12: false,
                    weekday: 'short',
                    year: 'numeric',
                    month: 'short',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                });
                const timezoneNameFormatter = new OriginalDateTimeFormat(locale || 'en-US', {
                    timeZone: timezone,
                    timeZoneName: 'long',
                });

                const partsFor = (date) => {
                    if (!isValidDate(date)) {
                        return null;
                    }
                    try {
                        return Object.fromEntries(
                            englishPartsFormatter.formatToParts(date)
                                .filter((part) => part.type !== 'literal')
                                .map((part) => [part.type, part.value])
                        );
                    } catch (_) {
                        return null;
                    }
                };
                const gmtOffsetFor = (date) => {
                    const offset = offsetFor(date);
                    const sign = offset <= 0 ? '+' : '-';
                    const abs = Math.abs(offset);
                    return `GMT${sign}${String(Math.floor(abs / 60)).padStart(2, '0')}${String(abs % 60).padStart(2, '0')}`;
                };
                const timezoneNameFor = (date) => {
                    try {
                        const found = timezoneNameFormatter
                            .formatToParts(date)
                            .find((part) => part.type === 'timeZoneName');
                        return found ? found.value : timezone;
                    } catch (_) {
                        return timezone;
                    }
                };
                const nativeLikeDateString = (date) => {
                    if (!isValidDate(date)) {
                        return originalToDateString.call(date);
                    }
                    const p = partsFor(date);
                    if (!p) {
                        return originalToDateString.call(date);
                    }
                    return `${p.weekday} ${p.month} ${p.day} ${p.year}`;
                };
                const nativeLikeTimeString = (date) => {
                    if (!isValidDate(date)) {
                        return originalToTimeString.call(date);
                    }
                    const p = partsFor(date);
                    if (!p) {
                        return originalToTimeString.call(date);
                    }
                    const hour = p.hour === '24' ? '00' : p.hour;
                    return `${hour}:${p.minute}:${p.second} ${gmtOffsetFor(date)} (${timezoneNameFor(date)})`;
                };

                Date.prototype.toDateString = markNative(function toDateString() {
                    return nativeLikeDateString(this);
                }, 'toDateString');
                Date.prototype.toTimeString = markNative(function toTimeString() {
                    return nativeLikeTimeString(this);
                }, 'toTimeString');
                Date.prototype.toString = markNative(function toString() {
                    if (!isValidDate(this)) {
                        return originalToString.call(this);
                    }
                    return `${nativeLikeDateString(this)} ${nativeLikeTimeString(this)}`;
                }, 'toString');
                Date.prototype.toLocaleString = markNative(function toLocaleString(locales, options) {
                    if (!isValidDate(this)) {
                        return originalToLocaleString.call(this, locales, options);
                    }
                    const nextOptions = Object.assign({}, options || {});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleString.call(this, defaultLocales(locales), nextOptions);
                }, 'toLocaleString');
                Date.prototype.toLocaleDateString = markNative(function toLocaleDateString(locales, options) {
                    if (!isValidDate(this)) {
                        return originalToLocaleDateString.call(this, locales, options);
                    }
                    const nextOptions = Object.assign({}, options || {});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleDateString.call(this, defaultLocales(locales), nextOptions);
                }, 'toLocaleDateString');
                Date.prototype.toLocaleTimeString = markNative(function toLocaleTimeString(locales, options) {
                    if (!isValidDate(this)) {
                        return originalToLocaleTimeString.call(this, locales, options);
                    }
                    const nextOptions = Object.assign({}, options || {});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleTimeString.call(this, defaultLocales(locales), nextOptions);
                }, 'toLocaleTimeString');
            }
        })();
    """.replace("__PAYLOAD__", json.dumps(payload))


def _build_fingerprint_init_script(
    *,
    locale: str | None,
    timezone: str | None,
    platform: str | None = None,
) -> str | None:
    """Patch common JS locale/timezone surfaces when a profile pins them."""
    languages = _locale_fallbacks(locale) if locale else []
    if not languages and not timezone:
        return None

    payload = {
        "locale": languages[0] if languages else None,
        "languages": languages,
        "timezone": timezone,
        "platform": platform,
    }
    worker_patch = _build_worker_fingerprint_patch(payload)
    return f"""
        (() => {{
            const cfg = {json.dumps(payload)};
            const workerPatch = {json.dumps(worker_patch)};
            const locale = cfg.locale;
            const languages = cfg.languages || [];
            const timezone = cfg.timezone;
            const profilePlatform = cfg.platform;
            const OriginalDateTimeFormat = Intl.DateTimeFormat;
            const nativeToString = Function.prototype.toString;
            const nativeSources = new WeakMap();

            const markNative = (fn, name) => {{
                try {{
                    nativeSources.set(fn, `function ${{name}}() {{ [native code] }}`);
                }} catch (_) {{}}
                return fn;
            }};

            const patchedFunctionToString = function toString() {{
                if (nativeSources.has(this)) return nativeSources.get(this);
                return nativeToString.call(this);
            }};
            markNative(patchedFunctionToString, 'toString');
            try {{
                Object.defineProperty(Function.prototype, 'toString', {{
                    value: patchedFunctionToString,
                    configurable: true,
                    writable: true,
                }});
            }} catch (_) {{}}

            const defineGetter = (proto, name, getter) => {{
                try {{
                    Object.defineProperty(proto, name, {{
                        get: markNative(getter, `get ${{name}}`),
                        configurable: true,
                    }});
                }} catch (_) {{}}
            }};

            const defaultLocales = (locales) => {{
                if (!locale) return locales;
                if (locales === undefined || locales === null) return locale;
                if (Array.isArray(locales) && locales.length === 0) return locale;
                return locales;
            }};

            const clientHintsPlatform = () => {{
                if (profilePlatform === 'macos') return 'macOS';
                if (profilePlatform === 'windows') return 'Windows';
                if (profilePlatform === 'linux') return 'Linux';
                if (/Mac/.test(navigator.platform || '')) return 'macOS';
                if (/Win/.test(navigator.platform || '')) return 'Windows';
                if (/Linux/.test(navigator.platform || '')) return 'Linux';
                return 'Unknown';
            }};

            const buildUserAgentData = () => {{
                const match = String(navigator.userAgent || '').match(/Chrome\\/(\\d+)(?:\\.([0-9.]+))?/);
                const major = match ? match[1] : '145';
                const full = match ? `${{major}}.${{match[2] || '0.0.0'}}` : '145.0.0.0';
                const brands = [
                    {{ brand: 'Not:A-Brand', version: '99' }},
                    {{ brand: 'Google Chrome', version: major }},
                    {{ brand: 'Chromium', version: major }},
                ];
                const fullVersionList = brands.map((brand) => ({{
                    brand: brand.brand,
                    version: brand.brand === 'Not:A-Brand' ? '99.0.0.0' : full,
                }}));
                const platform = clientHintsPlatform();
                return {{
                    brands,
                    mobile: false,
                    platform,
                    getHighEntropyValues: markNative(async function getHighEntropyValues(hints) {{
                        const values = {{
                            brands,
                            mobile: false,
                            platform,
                            architecture: platform === 'macOS' ? 'arm' : 'x86',
                            bitness: '64',
                            model: '',
                            platformVersion: platform === 'macOS' ? '15.0.0' : '10.0.0',
                            uaFullVersion: full,
                            fullVersionList,
                            wow64: false,
                        }};
                        const result = {{ brands, mobile: false, platform }};
                        for (const hint of hints || []) {{
                            if (hint in values) result[hint] = values[hint];
                        }}
                        return result;
                    }}, 'getHighEntropyValues'),
                    toJSON: markNative(function toJSON() {{
                        return {{ brands, mobile: false, platform }};
                    }}, 'toJSON'),
                }};
            }};

            const patchIntlConstructor = (name, configureOptions) => {{
                const Original = Intl[name];
                if (typeof Original !== 'function') return;

                const Patched = function(locales, options) {{
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (configureOptions) configureOptions(nextOptions);
                    return new Original(defaultLocales(locales), nextOptions);
                }};

                try {{
                    Object.setPrototypeOf(Patched, Original);
                    Patched.prototype = Original.prototype;
                    if (typeof Original.supportedLocalesOf === 'function') {{
                        Object.defineProperty(Patched, 'supportedLocalesOf', {{
                            value: markNative(function supportedLocalesOf(locales, options) {{
                                return Original.supportedLocalesOf(defaultLocales(locales), options);
                            }}, 'supportedLocalesOf'),
                            configurable: true,
                        }});
                    }}
                    Object.defineProperty(Patched, 'name', {{ value: name }});
                    Object.defineProperty(Patched, 'length', {{ value: Original.length }});
                    Object.defineProperty(Intl, name, {{
                        value: markNative(Patched, name),
                        configurable: true,
                        writable: true,
                    }});
                }} catch (_) {{}}
            }};

            const installWorkerPatch = () => {{
                if (typeof Blob !== 'function' || !workerPatch) return;
                const OriginalBlob = Blob;

                const shouldPatchBlob = (blobParts, options) => {{
                    try {{
                        const type = String((options && options.type) || '').toLowerCase();
                        if (!/(javascript|ecmascript)/.test(type)) return false;
                        if (!Array.isArray(blobParts)) return true;
                        const joined = blobParts
                            .filter((part) => typeof part === 'string')
                            .join('\\n')
                            .slice(0, 2000);
                        if (!joined) return true;
                        return /postMessage|onmessage|addEventListener\\s*\\(\\s*['"]message|importScripts|navigator|Intl|OffscreenCanvas/.test(joined);
                    }} catch (_) {{
                        return false;
                    }}
                }};

                const PatchedBlob = function Blob(blobParts, options) {{
                    const nextParts = shouldPatchBlob(blobParts, options)
                        ? [`${{workerPatch}}\\n`, ...(Array.isArray(blobParts) ? blobParts : [blobParts])]
                        : blobParts;
                    return new OriginalBlob(nextParts, options);
                }};

                try {{
                    Object.setPrototypeOf(PatchedBlob, OriginalBlob);
                    PatchedBlob.prototype = OriginalBlob.prototype;
                    Object.defineProperty(PatchedBlob, 'name', {{ value: 'Blob' }});
                    Object.defineProperty(PatchedBlob, 'length', {{ value: OriginalBlob.length }});
                    Object.defineProperty(window, 'Blob', {{
                        value: markNative(PatchedBlob, 'Blob'),
                        configurable: true,
                        writable: true,
                    }});
                }} catch (_) {{}}
            }};

            installWorkerPatch();

            if (locale) {{
                defineGetter(Navigator.prototype, 'language', function language() {{
                    return locale;
                }});
                defineGetter(Navigator.prototype, 'languages', function languagesGetter() {{
                    return languages.slice();
                }});
                if (!Object.getOwnPropertyDescriptor(Navigator.prototype, 'userAgentData') && typeof isSecureContext === 'boolean' && isSecureContext) {{
                    defineGetter(Navigator.prototype, 'userAgentData', function userAgentData() {{
                        return buildUserAgentData();
                    }});
                }}

                patchIntlConstructor('NumberFormat');
                patchIntlConstructor('Collator');
                patchIntlConstructor('PluralRules');
                patchIntlConstructor('RelativeTimeFormat');
                patchIntlConstructor('ListFormat');
                patchIntlConstructor('DisplayNames');
                patchIntlConstructor('Segmenter');
            }}

            if (timezone) {{
                const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
                const originalToString = Date.prototype.toString;
                const originalToDateString = Date.prototype.toDateString;
                const originalToTimeString = Date.prototype.toTimeString;
                const originalToLocaleString = Date.prototype.toLocaleString;
                const originalToLocaleDateString = Date.prototype.toLocaleDateString;
                const originalToLocaleTimeString = Date.prototype.toLocaleTimeString;
                const originalGetTime = Date.prototype.getTime;
                const isValidDate = (date) => {{
                    try {{
                        return Number.isFinite(originalGetTime.call(date));
                    }} catch (_) {{
                        return false;
                    }}
                }};

                patchIntlConstructor('DateTimeFormat', (nextOptions) => {{
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                }});

                const offsetFormatter = new OriginalDateTimeFormat('en-US', {{
                    timeZone: timezone,
                    hour12: false,
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                }});

                const offsetFor = (date) => {{
                    if (!isValidDate(date)) {{
                        return originalGetTimezoneOffset.call(date);
                    }}
                    try {{
                        const parts = Object.fromEntries(
                            offsetFormatter.formatToParts(date)
                                .filter((part) => part.type !== 'literal')
                                .map((part) => [part.type, part.value])
                        );
                        const hour = Number(parts.hour === '24' ? '0' : parts.hour);
                        const localAsUtc = Date.UTC(
                            Number(parts.year),
                            Number(parts.month) - 1,
                            Number(parts.day),
                            hour,
                            Number(parts.minute),
                            Number(parts.second)
                        );
                        return Math.round((date.getTime() - localAsUtc) / 60000);
                    }} catch (_) {{
                        return originalGetTimezoneOffset.call(date);
                    }}
                }};

                Date.prototype.getTimezoneOffset = markNative(function getTimezoneOffset() {{
                    return offsetFor(this);
                }}, 'getTimezoneOffset');

                const englishPartsFormatter = new OriginalDateTimeFormat('en-US', {{
                    timeZone: timezone,
                    hour12: false,
                    weekday: 'short',
                    year: 'numeric',
                    month: 'short',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                }});
                const timezoneNameFormatter = new OriginalDateTimeFormat(locale || 'en-US', {{
                    timeZone: timezone,
                    timeZoneName: 'long',
                }});

                const partsFor = (date) => {{
                    if (!isValidDate(date)) {{
                        return null;
                    }}
                    try {{
                        return Object.fromEntries(
                            englishPartsFormatter.formatToParts(date)
                                .filter((part) => part.type !== 'literal')
                                .map((part) => [part.type, part.value])
                        );
                    }} catch (_) {{
                        return null;
                    }}
                }};
                const gmtOffsetFor = (date) => {{
                    const offset = offsetFor(date);
                    const sign = offset <= 0 ? '+' : '-';
                    const abs = Math.abs(offset);
                    return `GMT${{sign}}${{String(Math.floor(abs / 60)).padStart(2, '0')}}${{String(abs % 60).padStart(2, '0')}}`;
                }};
                const timezoneNameFor = (date) => {{
                    try {{
                        const found = timezoneNameFormatter
                            .formatToParts(date)
                            .find((part) => part.type === 'timeZoneName');
                        return found ? found.value : timezone;
                    }} catch (_) {{
                        return timezone;
                    }}
                }};
                const nativeLikeDateString = (date) => {{
                    if (!isValidDate(date)) {{
                        return originalToDateString.call(date);
                    }}
                    const p = partsFor(date);
                    if (!p) {{
                        return originalToDateString.call(date);
                    }}
                    return `${{p.weekday}} ${{p.month}} ${{p.day}} ${{p.year}}`;
                }};
                const nativeLikeTimeString = (date) => {{
                    if (!isValidDate(date)) {{
                        return originalToTimeString.call(date);
                    }}
                    const p = partsFor(date);
                    if (!p) {{
                        return originalToTimeString.call(date);
                    }}
                    const hour = p.hour === '24' ? '00' : p.hour;
                    return `${{hour}}:${{p.minute}}:${{p.second}} ${{gmtOffsetFor(date)}} (${{timezoneNameFor(date)}})`;
                }};

                Date.prototype.toDateString = markNative(function toDateString() {{
                    return nativeLikeDateString(this);
                }}, 'toDateString');
                Date.prototype.toTimeString = markNative(function toTimeString() {{
                    return nativeLikeTimeString(this);
                }}, 'toTimeString');
                Date.prototype.toString = markNative(function toString() {{
                    if (!isValidDate(this)) {{
                        return originalToString.call(this);
                    }}
                    return `${{nativeLikeDateString(this)}} ${{nativeLikeTimeString(this)}}`;
                }}, 'toString');
                Date.prototype.toLocaleString = markNative(function toLocaleString(locales, options) {{
                    if (!isValidDate(this)) {{
                        return originalToLocaleString.call(this, locales, options);
                    }}
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleString');
                Date.prototype.toLocaleDateString = markNative(function toLocaleDateString(locales, options) {{
                    if (!isValidDate(this)) {{
                        return originalToLocaleDateString.call(this, locales, options);
                    }}
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleDateString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleDateString');
                Date.prototype.toLocaleTimeString = markNative(function toLocaleTimeString(locales, options) {{
                    if (!isValidDate(this)) {{
                        return originalToLocaleTimeString.call(this, locales, options);
                    }}
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleTimeString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleTimeString');
            }}
        }})();
    """


def _normalize_proxy(raw: str) -> str:
    """Convert common proxy formats while preserving Xray share links.

    Accepts:
      - http://user:pass@host:port  (already valid)
      - host:port:user:pass
      - host:port
      - ss://, vmess://, vless://, trojan:// (Xray share links)
    """
    raw = raw.strip()
    if raw.lower().startswith((
        "http://",
        "https://",
        "socks5://",
        "ss://",
        "vmess://",
        "vless://",
        "trojan://",
    )):
        return raw
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{raw}"
    return raw


def _validate_proxy(url: str) -> None:
    """Validate a direct proxy URL or a supported Xray share link."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme.lower() in {"ss", "vmess", "vless", "trojan"}:
        parse_xray_link(url)
        return
    if parsed.scheme not in ("http", "https", "socks5"):
        raise ValueError(
            "Invalid proxy scheme "
            f"'{parsed.scheme}'. Must be http, https, socks5, ss, vmess, vless, or trojan."
        )
    if not parsed.hostname:
        raise ValueError(f"Proxy URL missing hostname: {url}")
    if not parsed.port:
        raise ValueError(f"Proxy URL missing port: {url}")


def _init_profile_defaults(user_data_dir: Path) -> None:
    """Set up bookmarks and DuckDuckGo search on first launch."""
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    # --- Bookmarks (only on first launch) ---
    bookmarks_path = default_dir / "Bookmarks"
    if not bookmarks_path.exists():
        ts = str(int(time.time() * 1_000_000))  # Chrome timestamp format
        _id = 1

        def bm(name: str, url: str) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "url", "id": str(_id), "name": name, "url": url, "date_added": ts}

        def folder(name: str, children: list) -> dict:
            nonlocal _id
            _id += 1
            return {"type": "folder", "id": str(_id), "name": name, "children": children, "date_added": ts, "date_modified": ts}

        bookmarks = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "type": "folder", "id": "1", "name": "Bookmarks bar",
                    "date_added": ts, "date_modified": ts,
                    "children": [
                        folder("Detection Tests", [
                            bm("Rebrowser Bot Detector", "https://bot-detector.rebrowser.net/"),
                            bm("Incolumitas", "https://bot.incolumitas.com/"),
                            bm("SannySort", "https://bot.sannysoft.com/"),
                            bm("BrowserScan Bot", "https://www.browserscan.net/bot-detection"),
                            bm("FingerprintJS Demo", "https://demo.fingerprint.com/web-scraping"),
                            bm("Pixelscan", "https://pixelscan.net/fingerprint-check"),
                            bm("CreepJS", "https://abrahamjuliot.github.io/creepjs/"),
                            bm("fingerprint-scan", "https://fingerprint-scan.com/"),
                            bm("DeviceInfo Bot", "https://deviceandbrowserinfo.com/are_you_a_bot"),
                        ]),
                        folder("Fingerprint", [
                            bm("BrowserLeaks Canvas", "https://browserleaks.com/canvas"),
                            bm("BrowserLeaks WebGL", "https://browserleaks.com/webgl"),
                            bm("BrowserLeaks Fonts", "https://browserleaks.com/fonts"),
                            bm("BrowserLeaks JS", "https://browserleaks.com/javascript"),
                            bm("FingerprintJS OSS", "https://fingerprintjs.github.io/fingerprintjs/"),
                            bm("Audio FP", "https://audiofingerprint.openwpm.com/"),
                            bm("DeviceInfo", "https://deviceandbrowserinfo.com/info_device"),
                        ]),
                        folder("Headers & TLS", [
                            bm("httpbin headers", "https://httpbin.org/headers"),
                            bm("httpbin IP", "https://httpbin.org/ip"),
                            bm("TLS Fingerprint", "https://tls.browserleaks.com/"),
                        ]),
                        folder("reCAPTCHA", [
                            bm("Google v3 Demo", "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php"),
                            bm("2captcha v3", "https://2captcha.com/demo/recaptcha-v3"),
                            bm("Turnstile", "https://peet.ws/turnstile-test/non-interactive.html"),
                        ]),
                    ],
                },
                "other": {"type": "folder", "id": "2", "name": "Other bookmarks", "children": []},
                "synced": {"type": "folder", "id": "3", "name": "Mobile bookmarks", "children": []},
            },
            "version": 1,
        }
        bookmarks_path.write_text(json.dumps(bookmarks, indent=2))
        logger.info("Created default bookmarks for %s", user_data_dir.name)

    # --- DuckDuckGo as default search engine ---
    prefs_path = default_dir / "Preferences"
    if not prefs_path.exists():
        prefs = {
            "default_search_provider_data": {
                "template_url_data": {
                    "keyword": "duckduckgo.com",
                    "short_name": "DuckDuckGo",
                    "url": "https://duckduckgo.com/?q={searchTerms}",
                    "suggestions_url": "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
                    "favicon_url": "https://duckduckgo.com/favicon.ico",
                }
            },
            "default_search_provider": {
                "enabled": True,
            },
        }
        prefs_path.write_text(json.dumps(prefs, indent=2))
        logger.info("Set DuckDuckGo as default search for %s", user_data_dir.name)


CDP_START_ATTEMPTS = 3
CDP_READY_TIMEOUT = 10.0


async def _apply_cdp_locale_timezone_overrides(
    context: Any,
    *,
    profile_id: str,
    locale: str | None,
    timezone: str | None,
) -> None:
    """Apply browser-level locale/timezone overrides to a CDP-backed context."""
    if not locale and not timezone:
        return

    new_cdp_session = getattr(context, "new_cdp_session", None)
    if not callable(new_cdp_session):
        return

    cdp_locale = _locale_to_posix(locale).split(".", 1)[0] if locale else None

    async def patch_page(page: Any) -> None:
        session = None
        try:
            session = await new_cdp_session(page)
            if timezone:
                await session.send("Emulation.setTimezoneOverride", {"timezoneId": timezone})
            if cdp_locale:
                await session.send("Emulation.setLocaleOverride", {"locale": cdp_locale})
        except Exception as exc:
            logger.debug("CDP locale/timezone override skipped for %s: %s", profile_id, exc)
        finally:
            if session is not None:
                with suppress(Exception):
                    await session.detach()

    for page in list(getattr(context, "pages", []) or []):
        await patch_page(page)

    try:
        context.on("page", lambda page: asyncio.create_task(patch_page(page)))
    except Exception as exc:
        logger.debug("Could not register CDP page hook for %s: %s", profile_id, exc)


@dataclass
class RunningProfile:
    profile_id: str
    context: Any | None  # Playwright BrowserContext when debug/CDP is enabled
    cdp_port: int | None
    browser_process: subprocess.Popen[Any] | None = None
    display: int | None = None
    ws_port: int | None = None
    effective_timezone: str | None = None
    effective_locale: str | None = None
    proxy_geo: dict[str, Any] | None = None
    browser_engine: str = "cloakbrowser"
    launch_mode: str = "debug"
    proxy_bridge: HttpProxyBridge | None = None
    xray_process: XrayProcess | None = None
    monitor_task: asyncio.Task | None = None
    fingerprint_report: dict[str, Any] | None = None


class BrowserManager:
    def __init__(self, runtime_config: RuntimeConfig | None = None):
        self.runtime = runtime_config or resolve_runtime()
        self.running: dict[str, RunningProfile] = {}
        self._launching: set[str] = set()  # profile IDs currently being launched
        self.vnc = VNCManager(self.runtime.viewer_mode == "vnc")
        self._lock = asyncio.Lock()
        self._cdp_ports: set[int] = set()
        self._auto_launch_task: asyncio.Task | None = None

    def _browser_engine(self, profile: dict[str, Any] | None = None) -> str:
        profile_engine = str((profile or {}).get("browser_engine") or "auto").strip().lower()
        if profile_engine in {"chrome", "system-chrome", "system_chrome"}:
            if self.runtime.runtime_mode == "docker":
                logger.info(
                    "Profile requested system Chrome in Docker; using CloakBrowser runtime"
                )
                return "cloakbrowser"
            return "system_chrome"
        if profile_engine in {"cloak", "cloakbrowser", "cloak-browser"}:
            return "cloakbrowser"

        configured = os.environ.get(BROWSER_ENGINE_ENV, "auto").strip().lower()
        if configured in {"chrome", "system-chrome", "system_chrome"}:
            if self.runtime.runtime_mode == "docker":
                logger.info(
                    "%s requests system Chrome in Docker; using CloakBrowser runtime",
                    BROWSER_ENGINE_ENV,
                )
                return "cloakbrowser"
            return "system_chrome"
        if configured in {"cloak", "cloakbrowser", "cloak-browser"}:
            return "cloakbrowser"
        if configured != "auto":
            logger.warning(
                "Unknown %s=%r; using auto browser engine",
                BROWSER_ENGINE_ENV,
                configured,
            )
        if self.runtime.runtime_mode == "native" and self.runtime.host_os in {"macos", "windows"}:
            return "system_chrome"
        return "cloakbrowser"

    def preflight(self, profile: dict[str, Any], launch_mode: str = "manual") -> dict[str, Any]:
        """Check compatibility before a process is started.

        This is deliberately a compatibility report, not an anti-bot score. It
        prevents profiles from silently mixing host OS and device families and
        calls out features that only exist in the managed debug context.
        """
        engine = self._browser_engine(profile)
        mode = "debug" if launch_mode == "debug" else "manual"
        issues: list[dict[str, str]] = []
        host = self.runtime.host_os
        platform = str(profile.get("platform") or "").lower()

        if host in {"macos", "windows"} and platform and platform != host:
            issues.append({
                "severity": "error",
                "code": "host_platform_mismatch",
                "message": f"当前电脑是 {host}，不能启动 {platform or '未设置'} 设备画像。请在编辑页选择本机平台画像。",
            })
        if self.runtime.runtime_mode == "native" and profile.get("headless"):
            issues.append({
                "severity": "error",
                "code": "native_headless_unsupported",
                "message": "macOS/Windows 本地版只支持可见浏览器窗口；请关闭旧配置中的无界面模式后再启动。",
            })

        if engine == "system_chrome":
            spoofed = any(profile.get(key) for key in (
                "gpu_vendor", "gpu_renderer", "hardware_concurrency", "device_memory",
            ))
            device_profile = str(profile.get("device_profile") or "")
            if spoofed or device_profile.startswith(("mba_", "mbp_", "imac_", "mac_", "win_")):
                issues.append({
                    "severity": "warning",
                    "code": "system_chrome_native_only",
                    "message": "稳定原生模式使用本机 Chrome 和真实硬件；GPU、CPU、内存、屏幕和 Canvas 画像参数不会写入系统 Chrome。",
                })
        ua = str(profile.get("user_agent") or "")
        if ua:
            if platform == "macos" and ("Macintosh" not in ua or "Mac OS X" not in ua):
                issues.append({
                    "severity": "error", "code": "ua_platform_mismatch",
                    "message": "自定义 User-Agent 没有 macOS 标识，和当前 macOS 画像不一致。",
                })
            if platform == "windows" and "Windows NT" not in ua:
                issues.append({
                    "severity": "error", "code": "ua_platform_mismatch",
                    "message": "自定义 User-Agent 没有 Windows 标识，和当前 Windows 画像不一致。",
                })
            if engine == "cloakbrowser":
                ua_major = re.search(r"(?:Chrome|Chromium)/(\d+)", ua)
                try:
                    binary_major = get_effective_chromium_version().split(".", 1)[0]
                except (ImportError, AttributeError):
                    binary_major = ""
                if ua_major and binary_major and ua_major.group(1) != binary_major:
                    issues.append({
                        "severity": "error", "code": "ua_binary_version_mismatch",
                        "message": f"自定义 UA 是 Chrome {ua_major.group(1)}，当前 CloakBrowser 内核是 {binary_major}；请清空 UA 跟随内核。",
                    })

        vendor = str(profile.get("gpu_vendor") or "")
        renderer = str(profile.get("gpu_renderer") or "")
        if platform == "macos" and (
            (vendor and "apple" not in vendor.lower())
            or (renderer and "apple" not in renderer.lower())
        ):
            issues.append({
                "severity": "error", "code": "gpu_platform_mismatch",
                "message": "macOS 画像的 GPU 厂商/渲染器不是 Apple，和平台不一致。",
            })
        if platform == "windows" and ("apple" in vendor.lower() or "apple" in renderer.lower()):
            issues.append({
                "severity": "error", "code": "gpu_platform_mismatch",
                "message": "Windows 画像不能使用 Apple GPU 渲染器。",
            })

        width = profile.get("screen_width")
        height = profile.get("screen_height")
        if not isinstance(width, int) or not isinstance(height, int) or width < 320 or height < 240:
            issues.append({
                "severity": "error", "code": "invalid_screen",
                "message": "屏幕尺寸必须是至少 320×240 的有效逻辑分辨率。",
            })

        if profile.get("proxy") and profile.get("geoip") and not profile.get("proxy_geo"):
            issues.append({
                "severity": "warning", "code": "proxy_geo_pending",
                "message": "已开启按代理匹配语言/时区，但当前还没有保存的代理 GeoIP 结果；启动时会重新测试代理。",
            })
        if profile.get("cookies_json") and mode == "manual":
            issues.append({
                "severity": "info", "code": "manual_cookie_importer",
                "message": "日常无 CDP 启动会通过当前画像专用的本地扩展导入 Cookie JSON，并继续使用同一用户数据目录保存登录状态。",
            })
        if profile.get("humanize") and mode == "manual":
            issues.append({
                "severity": "info", "code": "manual_humanize_limit",
                "message": "无 CDP 手动启动不会由 Manager 自动操控鼠标键盘；你亲自使用浏览器时该选项不改变真实输入。",
            })

        error_count = sum(1 for issue in issues if issue["severity"] == "error")
        warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
        return {
            "status": "fail" if error_count else "warning" if warning_count else "pass",
            "browser_engine": engine,
            "launch_mode": mode,
            "can_launch": error_count == 0,
            "issues": issues,
            "capabilities": {
                "external_cdp": mode == "debug",
                "fingerprint_args": engine == "cloakbrowser",
                "native_system_chrome": engine == "system_chrome",
                "proxy_dns_policy": "proxy_host_resolver" if profile.get("proxy") else "direct",
                "webrtc_policy": "disable_non_proxied_udp",
                "tls_transport": "browser_native",
                "tls_externally_verified": False,
                "storage_persistence": True,
                "cookie_import": "profile_extension" if profile.get("cookies_json") and mode == "manual" else "browser_storage",
            },
        }

    async def launch(self, profile: dict[str, Any], launch_mode: str = "manual") -> RunningProfile:
        """Launch a browser instance using the configured host runtime."""
        profile_id = profile["id"]
        requested_launch_mode = "debug" if launch_mode == "debug" else "manual"

        async with self._lock:
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            self._launching.add(profile_id)

        display: int | None = None
        ws_port: int | None = None
        cdp_port: int | None = None
        context: Any | None = None
        browser_process: subprocess.Popen[Any] | None = None
        proxy_bridge: HttpProxyBridge | None = None
        xray_process: XrayProcess | None = None
        try:
            preflight = self.preflight(profile, requested_launch_mode)
            if not preflight["can_launch"]:
                messages = "；".join(issue["message"] for issue in preflight["issues"] if issue["severity"] == "error")
                raise RuntimeError(f"启动前检查未通过：{messages}")
            if self.runtime.viewer_mode == "vnc":
                display, ws_port = await self.vnc.allocate()

            user_data_dir = Path(profile["user_data_dir"])

            # Docker can leave stale locks after an unclean container exit. Native
            # mode must let Chromium arbitrate profile ownership itself.
            if self.runtime.runtime_mode == "docker":
                for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    (user_data_dir / lock_file).unlink(missing_ok=True)

            _init_profile_defaults(user_data_dir)
            _sync_session_restore(user_data_dir)
            if (
                requested_launch_mode == "manual"
                and self.runtime.runtime_mode == "native"
                and not bool(profile.get("headless", False))
            ):
                _sync_native_window_placement(
                    user_data_dir,
                    int(profile.get("screen_width", 1440)),
                    int(profile.get("screen_height", 900)),
                )

            if display is not None and ws_port is not None:
                await self.vnc.start_vnc(
                    display,
                    ws_port,
                    width=profile.get("screen_width", 1920),
                    height=profile.get("screen_height", 1080),
                )

            user_launch_args = list(profile.get("launch_args") or [])
            if requested_launch_mode == "manual":
                cookie_importer = _sync_cookie_import_extension(
                    user_data_dir,
                    profile.get("cookies_json"),
                )
                if cookie_importer is not None:
                    _append_unpacked_extension_arg(user_launch_args, cookie_importer)
            conflicting_debug_args = [
                arg for arg in user_launch_args
                if arg.startswith(("--remote-debugging-port", "--remote-debugging-address"))
            ]
            if conflicting_debug_args:
                raise ValueError(
                    "Manager owns remote debugging configuration; remove: "
                    + ", ".join(conflicting_debug_args)
                )

            raw_proxy = profile.get("proxy") or None
            proxy = _normalize_proxy(raw_proxy) if raw_proxy else None
            if proxy:
                _validate_proxy(proxy)

            browser_engine = self._browser_engine(profile)
            if self.runtime.host_os == "macos" and browser_engine == "cloakbrowser":
                _quarantine_macos_cloak_sync_data(
                    user_data_dir,
                    profile.get("last_exit_reason"),
                )
            browser_proxy = proxy
            if proxy and is_xray_link(proxy):
                xray_process = await start_xray_proxy(
                    proxy,
                    user_data_dir=user_data_dir,
                    data_dir=self.runtime.data_dir,
                )
                browser_proxy = xray_process.browser_proxy
                logger.info(
                    "Using Xray local SOCKS5 for profile %s: %s",
                    profile_id,
                    browser_proxy,
                )
            elif proxy:
                parsed_proxy = urlparse(proxy)
                needs_auth_bridge = bool(parsed_proxy.username or parsed_proxy.password)
                if needs_auth_bridge and (
                    parsed_proxy.scheme == "socks5"
                    or browser_engine == "system_chrome"
                ):
                    proxy_bridge = HttpProxyBridge(proxy)
                    browser_proxy = await proxy_bridge.start()
                    logger.info(
                        "Using local proxy bridge for authenticated proxy profile %s",
                        profile_id,
                    )

            resolved_timezone = profile.get("timezone") or None
            resolved_locale = profile.get("locale") or None
            proxy_geo: dict[str, Any] | None = None
            if browser_proxy:
                try:
                    geo = await fetch_proxy_geo(browser_proxy)
                    proxy_geo = geo
                    proxy_timezone = geo.get("timezone") or None
                    proxy_locale = geo.get("suggested_locale") or None
                    applied_timezone = False
                    applied_locale = False
                    if proxy_timezone and (profile.get("geoip") or not resolved_timezone):
                        resolved_timezone = proxy_timezone
                        applied_timezone = True
                    if proxy_locale and (profile.get("geoip") or not resolved_locale):
                        resolved_locale = proxy_locale
                        applied_locale = True
                    logger.info(
                        (
                            "GeoIP detected for %s: ip=%s country=%s "
                            "proxy_timezone=%s proxy_locale=%s resolved_timezone=%s "
                            "resolved_locale=%s applied_timezone=%s applied_locale=%s "
                            "geoip_enabled=%s source=%s"
                        ),
                        profile_id,
                        geo.get("ip"),
                        geo.get("country_code") or geo.get("country"),
                        proxy_timezone,
                        proxy_locale,
                        resolved_timezone,
                        resolved_locale,
                        applied_timezone,
                        applied_locale,
                        bool(profile.get("geoip")),
                        geo.get("source"),
                    )
                except Exception as exc:
                    logger.warning("GeoIP lookup failed for %s: %s", profile_id, exc)

            _sync_profile_locale(user_data_dir, resolved_locale)
            if browser_engine == "system_chrome" and proxy:
                _sync_webrtc_policy(user_data_dir)

            if browser_engine == "system_chrome":
                extra_args = list(SYSTEM_CHROME_BASE_ARGS)
            else:
                extra_args = self._build_fingerprint_args(profile)
                if resolved_locale and not any(arg.startswith("--lang") for arg in user_launch_args):
                    extra_args.append(f"--lang={resolved_locale}")
                if resolved_locale and not any(arg.startswith("--fingerprint-locale") for arg in user_launch_args):
                    extra_args.append(f"--fingerprint-locale={resolved_locale}")
                if resolved_timezone and not any(arg.startswith("--fingerprint-timezone") for arg in user_launch_args):
                    extra_args.append(f"--fingerprint-timezone={resolved_timezone}")
                if resolved_locale and not any(arg.startswith("--accept-lang") for arg in user_launch_args):
                    extra_args.append(f"--accept-lang={_accept_language_value(resolved_locale)}")
                if SESSION_RESTORE_ARG not in extra_args:
                    extra_args.append(SESSION_RESTORE_ARG)
            extra_args += user_launch_args

            launch_env = _build_locale_timezone_env(
                locale=resolved_locale,
                timezone=resolved_timezone,
                display=display,
            )

            launch_options: dict[str, Any] = {
                "user_data_dir": profile["user_data_dir"],
                "headless": bool(profile.get("headless", False)),
                "proxy": browser_proxy,
                "args": extra_args,
                "timezone": resolved_timezone,
                "locale": resolved_locale,
                "humanize": bool(profile.get("humanize", False)),
                "human_preset": profile.get("human_preset", "default"),
                "geoip": bool(profile.get("geoip", False)),
                "color_scheme": profile.get("color_scheme") or None,
                "user_agent": profile.get("user_agent") or None,
            }
            if launch_env is not None:
                launch_options["env"] = launch_env
            if display is not None:
                launch_options["viewport"] = {
                    "width": profile.get("screen_width", 1920),
                    "height": profile.get("screen_height", 1080) - 133,
                }
            elif (
                requested_launch_mode == "manual"
                and self.runtime.runtime_mode == "native"
                and not bool(profile.get("headless", False))
            ):
                # Headed native launches need an explicit outer window size.
                # Without it, older macOS CloakBrowser builds can report
                # outerWidth/outerHeight as zero and create a content area
                # larger than the profile's screen geometry.
                launch_options["viewport"] = {
                    "width": profile.get("screen_width", 1440),
                    "height": profile.get("screen_height", 900),
                }

            use_manual_system_chrome = (
                requested_launch_mode == "manual"
                and self.runtime.runtime_mode == "native"
                and browser_engine == "system_chrome"
                and display is None
                and not bool(profile.get("headless", False))
            )
            use_manual_cloakbrowser = (
                requested_launch_mode == "manual"
                and self.runtime.runtime_mode == "native"
                and browser_engine == "cloakbrowser"
                and display is None
                and not bool(profile.get("headless", False))
            )

            effective_launch_mode = (
                "manual"
                if use_manual_system_chrome or use_manual_cloakbrowser
                else "debug"
            )
            startup_urls = _startup_urls_for_profile(profile, profile_id)

            if use_manual_system_chrome or use_manual_cloakbrowser:
                if _has_restorable_chrome_session(user_data_dir):
                    # Keep restored tabs and add one local report tab so manual,
                    # no-CDP launches are still checked on every startup.
                    manual_start_urls = [
                        NATIVE_START_PAGE_TEMPLATE.format(profile_id=profile_id)
                    ]
                else:
                    manual_start_urls = startup_urls
                manual_launcher = (
                    _launch_system_chrome_manual_process
                    if use_manual_system_chrome
                    else _launch_cloakbrowser_manual_process
                )
                browser_process = manual_launcher(
                    **launch_options,
                    start_urls=manual_start_urls,
                )
            else:
                debug_args = [*extra_args, "--remote-debugging-address=127.0.0.1"]
                last_cdp_error: Exception | None = None
                for attempt in range(1, CDP_START_ATTEMPTS + 1):
                    cdp_port = self._reserve_cdp_port()
                    launch_options["args"] = [
                        *debug_args,
                        f"--remote-debugging-port={cdp_port}",
                    ]
                    try:
                        if browser_engine == "system_chrome":
                            launcher = _launch_system_chrome_persistent_context_async
                        elif self.runtime.host_os == "macos" and not bool(profile.get("headless", False)):
                            # Playwright rejects Cocoa's two-part locale values
                            # before launching. Direct process startup preserves
                            # them, then debug mode attaches to the requested CDP.
                            launcher = _launch_cloakbrowser_persistent_context_async
                        else:
                            launcher = launch_persistent_context_async
                        context = await launcher(**launch_options)
                        await self._wait_for_cdp(cdp_port)
                        break
                    except asyncio.CancelledError:
                        if context is not None:
                            await self._close_context(context, profile_id)
                        self._release_cdp_port(cdp_port)
                        context = None
                        cdp_port = None
                        raise
                    except Exception as exc:
                        last_cdp_error = exc
                        if context is not None:
                            await self._close_context(context, profile_id)
                        self._release_cdp_port(cdp_port)
                        context = None
                        cdp_port = None
                        logger.warning(
                            "Browser/CDP startup attempt %d/%d failed for %s: %s",
                            attempt,
                            CDP_START_ATTEMPTS,
                            profile_id,
                            exc,
                        )
                else:
                    raise RuntimeError(
                        f"Unable to start verified CDP for profile {profile_id}"
                    ) from last_cdp_error

                if context is None or cdp_port is None:
                    raise RuntimeError(f"Browser startup did not complete for profile {profile_id}")

                # Capture copied text so the Manager clipboard endpoint can read it.
                clipboard_init_js = """
                    window.__clipboardText = '';
                    document.addEventListener('copy', () => {
                        const sel = window.getSelection();
                        if (sel) window.__clipboardText = sel.toString();
                    });
                    document.addEventListener('keydown', (e) => {
                        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !e.altKey && !e.shiftKey) {
                            const sel = window.getSelection();
                            if (sel && sel.toString()) window.__clipboardText = sel.toString();
                        }
                    });
                """
                init_scripts = [clipboard_init_js]
                fingerprint_init_js = ""
                if browser_engine == "system_chrome":
                    fingerprint_init_js = _build_fingerprint_init_script(
                        locale=resolved_locale,
                        timezone=resolved_timezone,
                        platform=profile.get("platform"),
                    )
                if browser_engine == "system_chrome":
                    await _apply_cdp_locale_timezone_overrides(
                        context,
                        profile_id=profile_id,
                        locale=resolved_locale,
                        timezone=resolved_timezone,
                    )
                if fingerprint_init_js:
                    init_scripts.append(fingerprint_init_js)
                for script in init_scripts:
                    await context.add_init_script(script)
                for page in context.pages:
                    for script in init_scripts:
                        try:
                            await page.evaluate(script)
                        except Exception as exc:
                            logger.debug("Init script failed on existing page: %s", exc)
                profile_cookies = _parse_profile_cookies(profile.get("cookies_json"))
                if profile_cookies:
                    try:
                        await context.add_cookies(profile_cookies)
                    except Exception as exc:
                        logger.warning("Profile cookies import failed for %s: %s", profile_id, exc)
                browser_process = getattr(context, "_cloak_browser_process", None)

            running = RunningProfile(
                profile_id=profile_id,
                context=context,
                cdp_port=cdp_port,
                display=display,
                ws_port=ws_port,
                effective_timezone=resolved_timezone,
                effective_locale=resolved_locale,
                proxy_geo=proxy_geo,
                browser_engine=browser_engine,
                launch_mode=effective_launch_mode,
                proxy_bridge=proxy_bridge,
                xray_process=xray_process,
                browser_process=browser_process,
            )
            if context is not None:
                context.on(
                    "close",
                    lambda *_: asyncio.ensure_future(self._on_browser_closed(profile_id)),
                )
            elif browser_process is not None:
                running.monitor_task = asyncio.create_task(
                    self._watch_process(profile_id, browser_process),
                    name=f"cloakbrowser-watch-{profile_id}",
                )

            async with self._lock:
                self.running[profile_id] = running
                self._launching.discard(profile_id)

            if (
                self.runtime.runtime_mode == "native"
                and browser_engine == "system_chrome"
                and not bool(profile.get("headless", False))
                and context is not None
            ):
                await _open_native_start_page(context, profile_id, startup_urls)

            logger.info(
                "Launched profile %s (runtime=%s, mode=%s, display=%s, ws_port=%s, cdp_port=%s)",
                profile_id,
                self.runtime.runtime_mode,
                effective_launch_mode,
                f":{display}" if display is not None else "native",
                ws_port,
                cdp_port if cdp_port is not None else "none",
            )
            return running

        except BaseException:
            async with self._lock:
                self._launching.discard(profile_id)
            if context is not None:
                await self._close_context(context, profile_id)
            elif browser_process is not None:
                await _terminate_process_async(browser_process)
            if proxy_bridge is not None:
                await proxy_bridge.close()
            if xray_process is not None:
                await xray_process.close()
            if cdp_port is not None:
                self._release_cdp_port(cdp_port)
            if display is not None:
                await self.vnc.stop_vnc(display)
            raise

    async def _close_context(self, context: Any, profile_id: str) -> None:
        try:
            await context.close()
        except Exception as exc:
            logger.warning("Error closing context for %s: %s", profile_id, exc)

    async def _watch_process(self, profile_id: str, process: subprocess.Popen[Any]) -> None:
        try:
            await asyncio.to_thread(process.wait)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Process watcher failed for %s: %s", profile_id, exc)
            return
        returncode = process.returncode
        reason = "正常关闭" if returncode in (0, None) else f"异常退出（代码 {returncode}）"
        await self._on_browser_closed(profile_id, exit_reason=reason)

    async def _dispose_running(
        self,
        running: RunningProfile,
        *,
        close_context: bool,
    ) -> None:
        if (
            running.monitor_task is not None
            and running.monitor_task is not asyncio.current_task()
        ):
            running.monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await running.monitor_task
        if close_context and running.context is not None:
            await self._close_context(running.context, running.profile_id)
        await _terminate_process_async(running.browser_process)
        if running.proxy_bridge is not None:
            await running.proxy_bridge.close()
        if running.xray_process is not None:
            await running.xray_process.close()
        if running.display is not None:
            await self.vnc.stop_vnc(running.display)
        if running.cdp_port is not None:
            self._release_cdp_port(running.cdp_port)

    async def _on_browser_closed(self, profile_id: str, *, exit_reason: str = "浏览器关闭"):
        """Release resources after a browser crash or user-initiated close."""
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if running:
            logger.info("Browser closed for profile %s, cleaning up", profile_id)
            await self._dispose_running(running, close_context=False)
            try:
                from . import database as db
                db.mark_profile_exit(profile_id, exit_reason)
            except Exception as exc:
                logger.debug("Could not persist exit status for %s: %s", profile_id, exc)

    async def stop(self, profile_id: str):
        """Stop a running browser instance and release all owned resources."""
        # Pop before close so the close event observes an already-clean state.
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if not running:
            return

        logger.info("Stopping profile %s", profile_id)
        await self._dispose_running(running, close_context=True)
        try:
            from . import database as db
            db.mark_profile_exit(profile_id, "用户关闭")
        except Exception as exc:
            logger.debug("Could not persist stop status for %s: %s", profile_id, exc)

    def get_status(self, profile_id: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        """Get running status and viewer capabilities for a profile."""
        running = self.running.get(profile_id)
        running_engine = getattr(running, "browser_engine", None) if running else None
        browser_engine = (
            running_engine
            if isinstance(running_engine, str)
            else self._browser_engine(profile)
        )
        running_launch_mode = getattr(running, "launch_mode", None) if running else None
        launch_mode = (
            running_launch_mode
            if running_launch_mode in {"manual", "debug"}
            else ("debug" if running else None)
        )
        running_proxy_geo = getattr(running, "proxy_geo", None) if running else None
        proxy_geo = running_proxy_geo if isinstance(running_proxy_geo, dict) else None
        status = {
            "status": "running" if running else "stopped",
            "runtime_mode": self.runtime.runtime_mode,
            "viewer_mode": self.runtime.viewer_mode,
            "vnc_ws_port": running.ws_port if running else None,
            "display": (
                f":{running.display}"
                if running and running.display is not None
                else None
            ),
            "browser_engine": browser_engine,
            "cdp_url": (
                f"/api/profiles/{profile_id}/cdp"
                if running and running.cdp_port is not None
                else None
            ),
            "launch_mode": launch_mode,
            "proxy_geo": proxy_geo,
        }
        return status

    async def fingerprint_report(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Run a local consistency probe in an already running profile."""
        profile_id = profile["id"]
        running = self.running.get(profile_id)
        if not running:
            raise RuntimeError(f"Profile {profile_id} is not running")
        if running.context is None:
            if running.fingerprint_report is not None:
                return running.fingerprint_report
            raise RuntimeError("起始页尚未完成自动自检，请先打开该浏览器的起始页后重试")

        raw = await run_fingerprint_probe(running.context)
        return self.record_fingerprint_report(profile, raw, collection="active")

    def record_fingerprint_report(
        self,
        profile: dict[str, Any],
        raw: dict[str, Any],
        *,
        collection: str = "passive",
    ) -> dict[str, Any]:
        """Analyze and cache a report collected by the profile itself or Manager."""
        profile_id = profile["id"]
        running = self.running.get(profile_id)
        if not running:
            raise RuntimeError(f"Profile {profile_id} is not running")

        expected_locale = running.effective_locale or profile.get("locale")
        expected_timezone = running.effective_timezone or profile.get("timezone")
        seed_derived_macos = (
            running.browser_engine == "cloakbrowser"
            and self.runtime.host_os == "macos"
            and profile.get("platform") == "macos"
        )
        native_or_seed_derived = running.browser_engine == "system_chrome" or seed_derived_macos
        expected_screen_width = None if running.browser_engine == "system_chrome" else profile.get("screen_width")
        expected_screen_height = None if running.browser_engine == "system_chrome" else profile.get("screen_height")
        expected_hardware_concurrency = (
            None if native_or_seed_derived else profile.get("hardware_concurrency")
        )
        expected_device_memory = (
            None if native_or_seed_derived else profile.get("device_memory")
        )
        analysis = analyze_fingerprint(
            raw,
            expected_locale=expected_locale,
            expected_timezone=expected_timezone,
            expected_platform=profile.get("platform"),
            expected_screen_width=expected_screen_width,
            expected_screen_height=expected_screen_height,
            expected_hardware_concurrency=expected_hardware_concurrency,
            expected_device_memory=expected_device_memory,
            expected_gpu_vendor=None if native_or_seed_derived else profile.get("gpu_vendor"),
            expected_gpu_renderer=None if native_or_seed_derived else profile.get("gpu_renderer"),
            expected_user_agent=profile.get("user_agent"),
            proxy_configured=bool(profile.get("proxy")),
            expected_proxy_ip=(running.proxy_geo or {}).get("ip") if isinstance(running.proxy_geo, dict) else None,
        )
        main_values = raw.get("main") if isinstance(raw.get("main"), dict) else {}
        network_values = main_values.get("network") if isinstance(main_values.get("network"), dict) else {}
        external_probe = network_values.get("externalProbe") if isinstance(network_values.get("externalProbe"), dict) else None
        probe_transport = external_probe.get("transport") if external_probe and isinstance(external_probe.get("transport"), dict) else {}
        tls_externally_verified = bool(
            external_probe
            and not external_probe.get("error")
            and probe_transport.get("tls_version")
        )
        report = {
            "profile_id": profile_id,
            "expected": {
                "browser_engine": running.browser_engine,
                "launch_mode": running.launch_mode,
                "external_cdp": running.cdp_port is not None,
                "locale": expected_locale,
                "timezone": expected_timezone,
                "platform": profile.get("platform"),
                "screen_width": expected_screen_width,
                "screen_height": expected_screen_height,
                "hardware_concurrency": expected_hardware_concurrency,
                "device_memory": expected_device_memory,
                "gpu_vendor": None if native_or_seed_derived else profile.get("gpu_vendor"),
                "gpu_renderer": None if native_or_seed_derived else profile.get("gpu_renderer"),
                "hardware_profile_source": "seed" if seed_derived_macos else "configured",
            },
            "proxy_geo": running.proxy_geo,
            "network": {
                "proxy_configured": bool(profile.get("proxy")),
                "dns_policy": "proxy_host_resolver" if profile.get("proxy") else "direct",
                "webrtc_policy": "disable_non_proxied_udp",
                "tls_transport": "browser_native",
                "tls_externally_verified": tls_externally_verified,
                "dns_externally_verified": False,
                "external_probe_configured": bool(
                    os.environ.get("CLOAKBROWSER_NETWORK_PROBE_URL")
                    or DEFAULT_NETWORK_PROBE_URL
                ),
            },
            "collection": collection,
            "analysis": analysis,
            "raw": raw,
        }
        running.fingerprint_report = report
        return report

    async def cleanup_all(self):
        """Stop all running profiles. Called on shutdown."""
        async with self._lock:
            profile_ids = list(self.running.keys())

        for pid in profile_ids:
            await self.stop(pid)

        if self.runtime.viewer_mode == "vnc":
            await self.vnc.cleanup_all()

    async def cleanup_stale(self):
        """Kill orphan display processes in the Docker runtime only."""
        if self.runtime.viewer_mode == "vnc":
            await self.vnc.cleanup_stale()

    async def auto_launch_all(self):
        """Launch all profiles with auto_launch=True. Called on startup."""
        from . import database as db

        profiles = db.list_profiles()
        auto_profiles = [p for p in profiles if p.get("auto_launch")]
        if not auto_profiles:
            logger.info("No profiles configured for auto-launch")
            return

        logger.info("Auto-launching %d profile(s)...", len(auto_profiles))
        for profile in auto_profiles:
            try:
                await asyncio.wait_for(self.launch(profile), timeout=60)
                logger.info("Auto-launched profile %s (%s)", profile["name"], profile["id"])
            except Exception as exc:
                logger.error(
                    "Auto-launch failed for profile %s (%s): %s",
                    profile["name"], profile["id"], exc,
                )
        logger.info("Auto-launch complete: %d running", len(self.running))

    def _reserve_cdp_port(self) -> int:
        """Reserve an OS-selected loopback port for one managed browser."""
        for _ in range(20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
            if port not in self._cdp_ports:
                self._cdp_ports.add(port)
                return port
        raise RuntimeError("Unable to reserve a unique CDP port")

    def _release_cdp_port(self, port: int) -> None:
        self._cdp_ports.discard(port)

    @staticmethod
    async def _fetch_cdp_version(port: int) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version",
                timeout=1,
            ) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise RuntimeError("CDP version response is not an object")
            return payload

        return await asyncio.to_thread(fetch)

    async def _wait_for_cdp(
        self,
        port: int,
        timeout: float = CDP_READY_TIMEOUT,
    ) -> None:
        """Wait for and verify Chromium's debugger endpoint on the reserved port."""
        deadline = asyncio.get_running_loop().time() + timeout
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                version = await self._fetch_cdp_version(port)
                websocket_url = str(version.get("webSocketDebuggerUrl") or "")
                if f":{port}/" not in websocket_url:
                    raise RuntimeError(
                        f"CDP endpoint returned an unexpected debugger URL: {websocket_url!r}"
                    )
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        raise TimeoutError(f"CDP endpoint on 127.0.0.1:{port} was not ready") from last_error

    def _build_fingerprint_args(self, profile: dict[str, Any]) -> list[str]:
        """Build extra Chromium args from profile fingerprint settings."""
        args: list[str] = []
        if self.runtime.viewer_mode == "vnc":
            args.append("--use-angle=swiftshader")

        seed = profile.get("fingerprint_seed")
        if seed is not None:
            args.append(f"--fingerprint={seed}")

        p = profile.get("platform")
        if p:
            args.append(f"--fingerprint-platform={p}")

        if (
            p == "macos"
            and self.runtime.host_os == "macos"
            and self.runtime.runtime_mode == "native"
        ):
            # Let the binary derive one complete Apple Silicon identity from
            # the fixed seed. Screen geometry is kept explicit because it must
            # also match the headed window that Chromium restores on macOS.
            args.append("--fingerprint-noise=false")
            sw = profile.get("screen_width")
            sh = profile.get("screen_height")
            if sw:
                args.append(f"--fingerprint-screen-width={sw}")
            if sh:
                args.append(f"--fingerprint-screen-height={sh}")
            return args

        vendor = profile.get("gpu_vendor")
        if vendor:
            args.append(f"--fingerprint-gpu-vendor={vendor}")

        renderer = profile.get("gpu_renderer")
        if renderer:
            args.append(f"--fingerprint-gpu-renderer={renderer}")

        hw = profile.get("hardware_concurrency")
        if hw is not None:
            args.append(f"--fingerprint-hardware-concurrency={hw}")

        memory = profile.get("device_memory")
        if memory is not None:
            args.append(f"--fingerprint-device-memory={memory}")

        sw = profile.get("screen_width")
        sh = profile.get("screen_height")
        if sw:
            args.append(f"--fingerprint-screen-width={sw}")
        if sh:
            args.append(f"--fingerprint-screen-height={sh}")

        return args
