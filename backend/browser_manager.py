"""Launch/stop/track CloakBrowser instances per profile."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from cloakbrowser import launch_persistent_context_async

from .fingerprint_report import analyze_fingerprint, run_fingerprint_probe
from .proxy_geo import fetch_proxy_geo
from .runtime import RuntimeConfig, resolve_runtime
from .vnc_manager import VNCManager

logger = logging.getLogger("cloakbrowser.manager.browser")

BROWSER_ENGINE_ENV = "CLOAKBROWSER_MANAGER_ENGINE"
SYSTEM_CHROME_IGNORE_DEFAULT_ARGS = ["--enable-automation", "--enable-unsafe-swiftshader"]
SYSTEM_CHROME_BASE_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
]


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


def _playwright_proxy(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None
    settings: dict[str, str] = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
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
            "LC_MESSAGES": posix_locale,
            "LANGUAGE": ":".join(lang.replace("-", "_") for lang in _locale_fallbacks(locale)),
        })
    if not env_updates:
        return None
    return {**os.environ, **env_updates}


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
    """Launch the user's installed Chrome with native BrowserContext overrides."""
    from playwright.async_api import async_playwright

    context_kwargs: dict[str, Any] = {
        "user_data_dir": os.fspath(user_data_dir),
        "channel": "chrome",
        "headless": headless,
        "args": args or [],
        "ignore_default_args": SYSTEM_CHROME_IGNORE_DEFAULT_ARGS,
        "viewport": viewport,
    }
    proxy_settings = _playwright_proxy(proxy)
    if proxy_settings:
        context_kwargs["proxy"] = proxy_settings
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    if locale:
        context_kwargs["locale"] = locale
    if timezone:
        context_kwargs["timezone_id"] = timezone
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    if env:
        context_kwargs["env"] = env

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(**context_kwargs)
    except Exception:
        await pw.stop()
        raise

    original_close = context.close

    async def close_with_cleanup(*, reason: str | None = None) -> None:
        try:
            if reason is None:
                await original_close()
            else:
                await original_close(reason=reason)
        finally:
            await pw.stop()

    context.close = close_with_cleanup

    if humanize:
        try:
            from cloakbrowser.human import patch_context_async
            from cloakbrowser.human.config import resolve_config

            patch_context_async(context, resolve_config(human_preset))
        except Exception as exc:
            logger.debug("Humanize patch skipped for system Chrome: %s", exc)

    return context


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
                const originalToLocaleString = Date.prototype.toLocaleString;
                const originalToLocaleDateString = Date.prototype.toLocaleDateString;
                const originalToLocaleTimeString = Date.prototype.toLocaleTimeString;

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

                const partsFor = (date) => Object.fromEntries(
                    englishPartsFormatter.formatToParts(date)
                        .filter((part) => part.type !== 'literal')
                        .map((part) => [part.type, part.value])
                );
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
                    const p = partsFor(date);
                    return `${p.weekday} ${p.month} ${p.day} ${p.year}`;
                };
                const nativeLikeTimeString = (date) => {
                    const p = partsFor(date);
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
                    return `${nativeLikeDateString(this)} ${nativeLikeTimeString(this)}`;
                }, 'toString');
                Date.prototype.toLocaleString = markNative(function toLocaleString(locales, options) {
                    const nextOptions = Object.assign({}, options || {});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleString.call(this, defaultLocales(locales), nextOptions);
                }, 'toLocaleString');
                Date.prototype.toLocaleDateString = markNative(function toLocaleDateString(locales, options) {
                    const nextOptions = Object.assign({}, options || {});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleDateString.call(this, defaultLocales(locales), nextOptions);
                }, 'toLocaleDateString');
                Date.prototype.toLocaleTimeString = markNative(function toLocaleTimeString(locales, options) {
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
                const originalToLocaleString = Date.prototype.toLocaleString;
                const originalToLocaleDateString = Date.prototype.toLocaleDateString;
                const originalToLocaleTimeString = Date.prototype.toLocaleTimeString;

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

                const partsFor = (date) => Object.fromEntries(
                    englishPartsFormatter.formatToParts(date)
                        .filter((part) => part.type !== 'literal')
                        .map((part) => [part.type, part.value])
                );
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
                    const p = partsFor(date);
                    return `${{p.weekday}} ${{p.month}} ${{p.day}} ${{p.year}}`;
                }};
                const nativeLikeTimeString = (date) => {{
                    const p = partsFor(date);
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
                    return `${{nativeLikeDateString(this)}} ${{nativeLikeTimeString(this)}}`;
                }}, 'toString');
                Date.prototype.toLocaleString = markNative(function toLocaleString(locales, options) {{
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleString');
                Date.prototype.toLocaleDateString = markNative(function toLocaleDateString(locales, options) {{
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleDateString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleDateString');
                Date.prototype.toLocaleTimeString = markNative(function toLocaleTimeString(locales, options) {{
                    const nextOptions = Object.assign({{}}, options || {{}});
                    if (!nextOptions.timeZone) nextOptions.timeZone = timezone;
                    return originalToLocaleTimeString.call(this, defaultLocales(locales), nextOptions);
                }}, 'toLocaleTimeString');
            }}
        }})();
    """


def _normalize_proxy(raw: str) -> str:
    """Convert common proxy formats to http://user:pass@host:port.

    Accepts:
      - http://user:pass@host:port  (already valid)
      - host:port:user:pass
      - host:port
    """
    if raw.startswith(("http://", "https://", "socks5://")):
        return raw
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return f"http://{user}:{passwd}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{raw}"
    return raw


def _validate_proxy(url: str) -> None:
    """Validate that a normalized proxy URL has scheme, host, and port."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", "socks5"):
        raise ValueError(
            f"Invalid proxy scheme '{parsed.scheme}'. Must be http, https, or socks5."
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


@dataclass
class RunningProfile:
    profile_id: str
    context: Any  # Playwright BrowserContext
    cdp_port: int
    display: int | None = None
    ws_port: int | None = None
    effective_timezone: str | None = None
    effective_locale: str | None = None
    proxy_geo: dict[str, Any] | None = None
    browser_engine: str = "cloakbrowser"


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
            return "system_chrome"
        if profile_engine in {"cloak", "cloakbrowser", "cloak-browser"}:
            return "cloakbrowser"

        configured = os.environ.get(BROWSER_ENGINE_ENV, "auto").strip().lower()
        if configured in {"chrome", "system-chrome", "system_chrome"}:
            return "system_chrome"
        if configured in {"cloak", "cloakbrowser", "cloak-browser"}:
            return "cloakbrowser"
        if configured != "auto":
            logger.warning(
                "Unknown %s=%r; using auto browser engine",
                BROWSER_ENGINE_ENV,
                configured,
            )
        if self.runtime.runtime_mode == "native" and self.runtime.host_os == "macos":
            return "system_chrome"
        return "cloakbrowser"

    async def launch(self, profile: dict[str, Any]) -> RunningProfile:
        """Launch a browser instance using the configured host runtime."""
        profile_id = profile["id"]

        async with self._lock:
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            self._launching.add(profile_id)

        display: int | None = None
        ws_port: int | None = None
        cdp_port: int | None = None
        context: Any | None = None
        try:
            if self.runtime.viewer_mode == "vnc":
                display, ws_port = await self.vnc.allocate()

            user_data_dir = Path(profile["user_data_dir"])

            # Docker can leave stale locks after an unclean container exit. Native
            # mode must let Chromium arbitrate profile ownership itself.
            if self.runtime.runtime_mode == "docker":
                for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    (user_data_dir / lock_file).unlink(missing_ok=True)

            _init_profile_defaults(user_data_dir)

            if display is not None and ws_port is not None:
                await self.vnc.start_vnc(
                    display,
                    ws_port,
                    width=profile.get("screen_width", 1920),
                    height=profile.get("screen_height", 1080),
                )

            user_launch_args = profile.get("launch_args") or []
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

            resolved_timezone = profile.get("timezone") or None
            resolved_locale = profile.get("locale") or None
            proxy_geo: dict[str, Any] | None = None
            if proxy and profile.get("geoip"):
                try:
                    geo = await fetch_proxy_geo(proxy)
                    proxy_geo = geo
                    resolved_timezone = geo.get("timezone") or resolved_timezone
                    resolved_locale = geo.get("suggested_locale") or resolved_locale
                    logger.info(
                        "GeoIP applied for %s: timezone=%s locale=%s source=%s",
                        profile_id,
                        resolved_timezone,
                        resolved_locale,
                        geo.get("source"),
                    )
                except Exception as exc:
                    logger.warning("GeoIP lookup failed for %s: %s", profile_id, exc)

            browser_engine = self._browser_engine(profile)
            _sync_profile_locale(user_data_dir, resolved_locale)
            if browser_engine == "system_chrome" and proxy:
                _sync_webrtc_policy(user_data_dir)

            if browser_engine == "system_chrome":
                extra_args = list(SYSTEM_CHROME_BASE_ARGS)
            else:
                extra_args = self._build_fingerprint_args(profile)
                if resolved_locale and not any(arg.startswith("--lang") for arg in user_launch_args):
                    extra_args.append(f"--lang={resolved_locale}")
                if resolved_locale and not any(arg.startswith("--accept-lang") for arg in user_launch_args):
                    extra_args.append(f"--accept-lang={_accept_language_value(resolved_locale)}")
            extra_args += user_launch_args
            extra_args.append("--remote-debugging-address=127.0.0.1")

            launch_env = _build_locale_timezone_env(
                locale=resolved_locale,
                timezone=resolved_timezone,
                display=display,
            )

            launch_options: dict[str, Any] = {
                "user_data_dir": profile["user_data_dir"],
                "headless": bool(profile.get("headless", False)),
                "proxy": proxy,
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

            last_cdp_error: Exception | None = None
            for attempt in range(1, CDP_START_ATTEMPTS + 1):
                cdp_port = self._reserve_cdp_port()
                launch_options["args"] = [
                    *extra_args,
                    f"--remote-debugging-port={cdp_port}",
                ]
                try:
                    launcher = (
                        _launch_system_chrome_persistent_context_async
                        if browser_engine == "system_chrome"
                        else launch_persistent_context_async
                    )
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
            fingerprint_init_js = _build_fingerprint_init_script(
                locale=resolved_locale,
                timezone=resolved_timezone,
                platform=profile.get("platform"),
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
            )
            context.on(
                "close",
                lambda *_: asyncio.ensure_future(self._on_browser_closed(profile_id)),
            )

            async with self._lock:
                self.running[profile_id] = running
                self._launching.discard(profile_id)

            logger.info(
                "Launched profile %s (runtime=%s, display=%s, ws_port=%s, cdp_port=%d)",
                profile_id,
                self.runtime.runtime_mode,
                f":{display}" if display is not None else "native",
                ws_port,
                cdp_port,
            )
            return running

        except BaseException:
            async with self._lock:
                self._launching.discard(profile_id)
            if context is not None:
                await self._close_context(context, profile_id)
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

    async def _dispose_running(
        self,
        running: RunningProfile,
        *,
        close_context: bool,
    ) -> None:
        if close_context:
            await self._close_context(running.context, running.profile_id)
        if running.display is not None:
            await self.vnc.stop_vnc(running.display)
        self._release_cdp_port(running.cdp_port)

    async def _on_browser_closed(self, profile_id: str):
        """Release resources after a browser crash or user-initiated close."""
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if running:
            logger.info("Browser closed for profile %s, cleaning up", profile_id)
            await self._dispose_running(running, close_context=False)

    async def stop(self, profile_id: str):
        """Stop a running browser instance and release all owned resources."""
        # Pop before close so the close event observes an already-clean state.
        async with self._lock:
            running = self.running.pop(profile_id, None)

        if not running:
            return

        logger.info("Stopping profile %s", profile_id)
        await self._dispose_running(running, close_context=True)

    def get_status(self, profile_id: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        """Get running status and viewer capabilities for a profile."""
        running = self.running.get(profile_id)
        running_engine = getattr(running, "browser_engine", None) if running else None
        browser_engine = (
            running_engine
            if isinstance(running_engine, str)
            else self._browser_engine(profile)
        )
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
            "cdp_url": f"/api/profiles/{profile_id}/cdp" if running else None,
        }
        return status

    async def fingerprint_report(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Run a local consistency probe in an already running profile."""
        profile_id = profile["id"]
        running = self.running.get(profile_id)
        if not running:
            raise RuntimeError(f"Profile {profile_id} is not running")

        expected_locale = running.effective_locale or profile.get("locale")
        expected_timezone = running.effective_timezone or profile.get("timezone")
        expected_screen_width = None if running.browser_engine == "system_chrome" else profile.get("screen_width")
        expected_screen_height = None if running.browser_engine == "system_chrome" else profile.get("screen_height")
        expected_hardware_concurrency = (
            None if running.browser_engine == "system_chrome" else profile.get("hardware_concurrency")
        )
        raw = await run_fingerprint_probe(running.context)
        analysis = analyze_fingerprint(
            raw,
            expected_locale=expected_locale,
            expected_timezone=expected_timezone,
            expected_platform=profile.get("platform"),
            expected_screen_width=expected_screen_width,
            expected_screen_height=expected_screen_height,
            expected_hardware_concurrency=expected_hardware_concurrency,
        )
        return {
            "profile_id": profile_id,
            "expected": {
                "browser_engine": running.browser_engine,
                "locale": expected_locale,
                "timezone": expected_timezone,
                "platform": profile.get("platform"),
                "screen_width": expected_screen_width,
                "screen_height": expected_screen_height,
                "hardware_concurrency": expected_hardware_concurrency,
            },
            "proxy_geo": running.proxy_geo,
            "analysis": analysis,
            "raw": raw,
        }

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
        args: list[str] = [
            "--disable-infobars",
            "--test-type",  # suppress "unsupported flag: --no-sandbox" bad flags warning
        ]
        if self.runtime.viewer_mode == "vnc":
            args.append("--use-angle=swiftshader")

        seed = profile.get("fingerprint_seed")
        if seed is not None:
            args.append(f"--fingerprint={seed}")

        p = profile.get("platform")
        if p:
            # Map our "macos" to binary's "macos"
            args.append(f"--fingerprint-platform={p}")

        vendor = profile.get("gpu_vendor")
        if vendor:
            args.append(f"--fingerprint-gpu-vendor={vendor}")

        renderer = profile.get("gpu_renderer")
        if renderer:
            args.append(f"--fingerprint-gpu-renderer={renderer}")

        hw = profile.get("hardware_concurrency")
        if hw is not None:
            args.append(f"--fingerprint-hardware-concurrency={hw}")

        sw = profile.get("screen_width")
        sh = profile.get("screen_height")
        if sw:
            args.append(f"--fingerprint-screen-width={sw}")
        if sh:
            args.append(f"--fingerprint-screen-height={sh}")

        return args
