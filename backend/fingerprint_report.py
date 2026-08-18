"""Local fingerprint consistency diagnostics for running profiles."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any


PROBE_URL = "https://example.com/"
FALLBACK_PROBE_URL = "data:text/html,<title>fingerprint-probe</title><body></body>"
DEFAULT_NETWORK_PROBE_URL = "https://cloakbrowser-network-probe-norwayx.424982.workers.dev"


DIAGNOSTIC_SCRIPT = """
async () => {
  const hashString = (value) => {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  };

  const readWebGL = () => {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!gl) return null;
      const debug = gl.getExtension('WEBGL_debug_renderer_info');
      return {
        vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
        renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
        version: gl.getParameter(gl.VERSION),
        shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
        maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
      };
    } catch (err) {
      return { error: String(err) };
    }
  };

  const readStorage = async () => {
    const result = {
      cookieEnabled: navigator.cookieEnabled,
      localStorage: { available: false, roundTrip: false },
      sessionStorage: { available: false, roundTrip: false },
      indexedDB: false,
      cacheStorage: false,
      estimate: null,
    };
    for (const name of ['localStorage', 'sessionStorage']) {
      try {
        const storage = window[name];
        const key = '__cloak_probe__';
        storage.setItem(key, 'ok');
        result[name].available = true;
        result[name].roundTrip = storage.getItem(key) === 'ok';
        storage.removeItem(key);
      } catch (_) { /* opaque pages can intentionally deny storage */ }
    }
    try { result.indexedDB = Boolean(window.indexedDB); } catch (_) {}
    try { result.cacheStorage = Boolean(window.caches); } catch (_) {}
    try { result.estimate = await navigator.storage?.estimate?.(); } catch (_) {}
    return result;
  };

  const readFonts = () => {
    const candidates = ['Arial', 'Helvetica Neue', 'Times New Roman', 'Courier New', 'Menlo', 'SF Pro Text', 'Segoe UI', 'Roboto'];
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return { available: [], measurable: false };
    const baseline = '72px monospace';
    ctx.font = baseline;
    const baselineWidth = ctx.measureText('mmmmmmmmmmlli').width;
    const available = candidates.filter((font) => {
      ctx.font = `72px "${font}", monospace`;
      return ctx.measureText('mmmmmmmmmmlli').width !== baselineWidth;
    });
    return { available, measurable: true };
  };

  const readWebRtcCandidates = async () => {
    try {
      if (!window.RTCPeerConnection) return [];
      const pc = new RTCPeerConnection({ iceServers: [] });
      const candidates = [];
      pc.createDataChannel('probe');
      pc.onicecandidate = (event) => { if (event.candidate?.candidate) candidates.push(event.candidate.candidate); };
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise((resolve) => setTimeout(resolve, 1200));
      pc.close();
      return candidates;
    } catch (_) { return []; }
  };

  const readExternalProbe = async () => {
    const baseUrl = window.__CLOAK_NETWORK_PROBE_URL;
    if (!baseUrl) return null;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      const response = await fetch(`${baseUrl.replace(/\/$/, '')}/?t=${Date.now()}`, {
        cache: 'no-store',
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (!response.ok) return { error: `HTTP ${response.status}` };
      return await response.json();
    } catch (err) {
      return { error: String(err) };
    }
  };

  const readCanvasHash = () => {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 280;
      canvas.height = 90;
      const ctx = canvas.getContext('2d');
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#f60';
      ctx.fillRect(0, 0, 280, 90);
      ctx.fillStyle = '#069';
      ctx.font = '18px Arial';
      ctx.fillText('CloakBrowser fingerprint probe 123', 8, 12);
      ctx.fillStyle = 'rgba(120, 40, 200, 0.7)';
      ctx.font = '16px Times New Roman';
      ctx.fillText('language/timezone/canvas', 8, 44);
      return hashString(canvas.toDataURL());
    } catch (err) {
      return `error:${String(err)}`;
    }
  };

  const readAudioHash = async () => {
    try {
      const OfflineAudioContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;
      if (!OfflineAudioContext) return null;
      const ctx = new OfflineAudioContext(1, 44100, 44100);
      const oscillator = ctx.createOscillator();
      const compressor = ctx.createDynamicsCompressor();
      oscillator.type = 'triangle';
      oscillator.frequency.value = 10000;
      compressor.threshold.value = -50;
      compressor.knee.value = 40;
      compressor.ratio.value = 12;
      compressor.attack.value = 0;
      compressor.release.value = 0.25;
      oscillator.connect(compressor);
      compressor.connect(ctx.destination);
      oscillator.start(0);
      const rendered = await ctx.startRendering();
      const data = rendered.getChannelData(0);
      let sample = '';
      for (let i = 4500; i < 5000; i += 7) sample += data[i].toFixed(7);
      return hashString(sample);
    } catch (err) {
      return `error:${String(err)}`;
    }
  };

  const collect = async (scope) => {
    const now = new Date('2026-08-16T05:51:19Z');
    const uaData = navigator.userAgentData || null;
    const uaHighEntropy = uaData && uaData.getHighEntropyValues
      ? await uaData.getHighEntropyValues([
          'architecture',
          'bitness',
          'brands',
          'fullVersionList',
          'mobile',
          'model',
          'platform',
          'platformVersion',
          'uaFullVersion',
          'wow64',
        ])
      : null;
    return {
      scope,
      page: {
        href: location.href,
        origin: location.origin,
        secureContext: window.isSecureContext,
      },
      navigator: {
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        languages: Array.from(navigator.languages || []),
        webdriver: navigator.webdriver,
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: navigator.deviceMemory ?? null,
        maxTouchPoints: navigator.maxTouchPoints,
        plugins: navigator.plugins ? navigator.plugins.length : null,
        userAgentData: uaData ? {
          brands: uaData.brands,
          mobile: uaData.mobile,
          platform: uaData.platform,
          highEntropy: uaHighEntropy,
        } : null,
      },
      intl: {
        dateTime: Intl.DateTimeFormat().resolvedOptions(),
        number: Intl.NumberFormat().resolvedOptions(),
        collator: Intl.Collator().resolvedOptions(),
        pluralRules: new Intl.PluralRules().resolvedOptions(),
      },
      date: {
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        offset: now.getTimezoneOffset(),
        string: now.toString(),
        localeString: now.toLocaleString(),
      },
      screen: {
        width: screen.width,
        height: screen.height,
        availWidth: screen.availWidth,
        availHeight: screen.availHeight,
        colorDepth: screen.colorDepth,
        pixelDepth: screen.pixelDepth,
        devicePixelRatio: window.devicePixelRatio,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
      },
      graphics: {
        webgl: readWebGL(),
        canvasHashA: readCanvasHash(),
        canvasHashB: readCanvasHash(),
        audioHashA: await readAudioHash(),
        audioHashB: await readAudioHash(),
      },
      storage: await readStorage(),
      fonts: readFonts(),
      network: {
        webrtcCandidates: await readWebRtcCandidates(),
        externalProbe: await readExternalProbe(),
        connection: navigator.connection ? {
          effectiveType: navigator.connection.effectiveType ?? null,
          rtt: navigator.connection.rtt ?? null,
          downlink: navigator.connection.downlink ?? null,
        } : null,
      },
      nativeStrings: {
        functionToString: Function.prototype.toString.toString(),
        dateToString: Date.prototype.toString.toString(),
        getTimezoneOffset: Date.prototype.getTimezoneOffset.toString(),
        intlDateTimeFormat: Intl.DateTimeFormat.toString(),
        intlNumberFormat: Intl.NumberFormat.toString(),
        navigatorLanguageGetter: String(
          Object.getOwnPropertyDescriptor(Navigator.prototype, 'language')?.get
        ),
      },
    };
  };

  const readIframe = async () => {
    try {
      const iframe = document.createElement('iframe');
      iframe.srcdoc = '<!doctype html><title>probe</title>';
      document.body.appendChild(iframe);
      await new Promise((resolve) => {
        iframe.onload = resolve;
        setTimeout(resolve, 1000);
      });
      const w = iframe.contentWindow;
      const now = new w.Date('2026-08-16T05:51:19Z');
      const uaData = w.navigator.userAgentData || null;
      const uaHighEntropy = uaData && uaData.getHighEntropyValues
        ? await uaData.getHighEntropyValues(['architecture', 'bitness', 'brands', 'fullVersionList', 'mobile', 'model', 'platform', 'platformVersion', 'uaFullVersion', 'wow64'])
        : null;
      const result = {
        scope: 'iframe',
        page: {
          href: w.location.href,
          origin: w.location.origin,
          secureContext: w.isSecureContext,
        },
        navigator: {
          language: w.navigator.language,
          languages: Array.from(w.navigator.languages || []),
          userAgent: w.navigator.userAgent,
          platform: w.navigator.platform,
          webdriver: w.navigator.webdriver,
          hardwareConcurrency: w.navigator.hardwareConcurrency,
          deviceMemory: w.navigator.deviceMemory ?? null,
          userAgentData: uaData ? {
            brands: uaData.brands,
            mobile: uaData.mobile,
            platform: uaData.platform,
            highEntropy: uaHighEntropy,
          } : null,
        },
        intl: {
          dateTime: w.Intl.DateTimeFormat().resolvedOptions(),
          number: w.Intl.NumberFormat().resolvedOptions(),
          collator: w.Intl.Collator().resolvedOptions(),
        },
        date: {
          timezone: w.Intl.DateTimeFormat().resolvedOptions().timeZone,
          offset: now.getTimezoneOffset(),
          string: now.toString(),
        },
      };
      iframe.remove();
      return result;
    } catch (err) {
      return { scope: 'iframe', error: String(err) };
    }
  };

  const readWorker = async () => {
    try {
      const source = `
        const now = new Date('2026-08-16T05:51:19Z');
        const uaData = navigator.userAgentData || null;
        postMessage({
          scope: 'worker',
          navigator: {
            userAgent: navigator.userAgent,
            platform: navigator.platform,
            language: navigator.language,
            languages: Array.from(navigator.languages || []),
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory: navigator.deviceMemory ?? null,
            userAgentData: uaData ? {
              brands: uaData.brands,
              mobile: uaData.mobile,
              platform: uaData.platform,
              highEntropy: null,
            } : null,
          },
          intl: {
            dateTime: Intl.DateTimeFormat().resolvedOptions(),
            number: Intl.NumberFormat().resolvedOptions(),
            collator: Intl.Collator().resolvedOptions(),
            pluralRules: new Intl.PluralRules().resolvedOptions(),
          },
          date: {
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            offset: now.getTimezoneOffset(),
            string: now.toString(),
          },
          nativeStrings: {
            functionToString: Function.prototype.toString.toString(),
            dateToString: Date.prototype.toString.toString(),
            getTimezoneOffset: Date.prototype.getTimezoneOffset.toString(),
            intlDateTimeFormat: Intl.DateTimeFormat.toString(),
            intlNumberFormat: Intl.NumberFormat.toString(),
          },
        });
      `;
      const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
      const worker = new Worker(url);
      const result = await new Promise((resolve, reject) => {
        worker.onmessage = (event) => resolve(event.data);
        worker.onerror = (event) => reject(event.message || 'worker error');
        setTimeout(() => reject('worker timeout'), 3000);
      });
      worker.terminate();
      URL.revokeObjectURL(url);
      return result;
    } catch (err) {
      return { scope: 'worker', error: String(err) };
    }
  };

  return {
    main: await collect('main'),
    iframe: await readIframe(),
    worker: await readWorker(),
  };
}
"""


def _locale_matches(actual: str | None, expected: str | None) -> bool:
    if not actual or not expected:
        return True
    actual_norm = actual.replace("_", "-").lower()
    expected_norm = expected.replace("_", "-").lower()
    expected_base = expected_norm.split("-", 1)[0]
    return actual_norm == expected_norm or actual_norm == expected_base


def _first_language(values: dict[str, Any]) -> str | None:
    languages = values.get("navigator", {}).get("languages")
    if isinstance(languages, list) and languages:
        return str(languages[0])
    language = values.get("navigator", {}).get("language")
    return str(language) if language else None


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    signal: str,
    scope: str,
    expected: Any,
    actual: Any,
    message: str,
) -> None:
    issues.append({
        "severity": severity,
        "signal": signal,
        "scope": scope,
        "expected": expected,
        "actual": actual,
        "message": message,
    })


def analyze_fingerprint(
    raw: dict[str, Any],
    *,
    expected_locale: str | None,
    expected_timezone: str | None,
    expected_platform: str | None,
    expected_screen_width: int | None,
    expected_screen_height: int | None,
    expected_hardware_concurrency: int | None,
    expected_device_memory: int | None = None,
    expected_gpu_vendor: str | None = None,
    expected_gpu_renderer: str | None = None,
    expected_user_agent: str | None = None,
    proxy_configured: bool = False,
    expected_proxy_ip: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    if raw.get("probe_error"):
        _add_issue(
            issues,
            severity="warning",
            signal="probe_url",
            scope="main",
            expected=PROBE_URL,
            actual=raw.get("probe_error"),
            message="HTTPS fingerprint probe could not load; secure-context signals may be incomplete",
        )

    for scope in ("main", "iframe", "worker"):
        values = raw.get(scope)
        if not isinstance(values, dict):
            continue
        if values.get("error"):
            _add_issue(
                issues,
                severity="warning",
                signal="scope_error",
                scope=scope,
                expected="readable",
                actual=values.get("error"),
                message=f"{scope} fingerprint scope could not be read",
            )
            continue

        language = values.get("navigator", {}).get("language")
        first_language = _first_language(values)
        intl_date = values.get("intl", {}).get("dateTime", {}).get("locale")
        intl_number = values.get("intl", {}).get("number", {}).get("locale")
        intl_collator = values.get("intl", {}).get("collator", {}).get("locale")
        timezone = values.get("date", {}).get("timezone")

        if expected_locale and not _locale_matches(str(language), expected_locale):
            _add_issue(
                issues,
                severity="error",
                signal="navigator.language",
                scope=scope,
                expected=expected_locale,
                actual=language,
                message="Navigator language does not match the profile locale",
            )
        if expected_locale and not _locale_matches(first_language, expected_locale):
            _add_issue(
                issues,
                severity="error",
                signal="navigator.languages",
                scope=scope,
                expected=expected_locale,
                actual=values.get("navigator", {}).get("languages"),
                message="The first navigator.languages value does not match the profile locale",
            )
        for signal, actual in (
            ("Intl.DateTimeFormat", intl_date),
            ("Intl.NumberFormat", intl_number),
            ("Intl.Collator", intl_collator),
        ):
            if expected_locale and not _locale_matches(str(actual), expected_locale):
                _add_issue(
                    issues,
                    severity="error",
                    signal=signal,
                    scope=scope,
                    expected=expected_locale,
                    actual=actual,
                    message=f"{signal} locale does not match the profile locale",
                )
        if expected_timezone and timezone != expected_timezone:
            _add_issue(
                issues,
                severity="error",
                signal="timezone",
                scope=scope,
                expected=expected_timezone,
                actual=timezone,
                message="Timezone does not match the profile/proxy timezone",
            )

    # A profile can have no explicit locale/timezone (for example when GeoIP is
    # unavailable). The browser surfaces must still agree with each other.
    # Compare against main rather than inventing a value from one child scope.
    main_values = raw.get("main") if isinstance(raw.get("main"), dict) else None
    if main_values:
        main_nav = main_values.get("navigator", {})
        main_intl = main_values.get("intl", {})
        main_date = main_values.get("date", {})
        main_language = main_nav.get("language")
        main_first_language = _first_language(main_values)
        main_timezone = main_date.get("timezone")
        main_intl_values = {
            "Intl.DateTimeFormat": main_intl.get("dateTime", {}).get("locale"),
            "Intl.NumberFormat": main_intl.get("number", {}).get("locale"),
            "Intl.Collator": main_intl.get("collator", {}).get("locale"),
        }
        for scope in ("iframe", "worker"):
            values = raw.get(scope)
            if not isinstance(values, dict) or values.get("error"):
                continue
            nav = values.get("navigator", {})
            intl = values.get("intl", {})
            date = values.get("date", {})
            scope_language = nav.get("language")
            if main_language and scope_language and not _locale_matches(str(scope_language), str(main_language)):
                _add_issue(
                    issues,
                    severity="error",
                    signal="scope_consistency.navigator.language",
                    scope=scope,
                    expected=main_language,
                    actual=scope_language,
                    message="Main page, iframe and Worker navigator.language values differ",
                )
            scope_first_language = _first_language(values)
            if main_first_language and scope_first_language and not _locale_matches(str(scope_first_language), str(main_first_language)):
                _add_issue(
                    issues,
                    severity="error",
                    signal="scope_consistency.navigator.languages",
                    scope=scope,
                    expected=main_first_language,
                    actual=scope_first_language,
                    message="Main page, iframe and Worker navigator.languages values differ",
                )
            for signal, main_actual, scope_actual in (
                ("userAgent", main_nav.get("userAgent"), nav.get("userAgent")),
                ("platform", main_nav.get("platform"), nav.get("platform")),
                ("hardwareConcurrency", main_nav.get("hardwareConcurrency"), nav.get("hardwareConcurrency")),
                ("deviceMemory", main_nav.get("deviceMemory"), nav.get("deviceMemory")),
            ):
                if main_actual is not None and scope_actual is not None and main_actual != scope_actual:
                    _add_issue(
                        issues,
                        severity="error",
                        signal=f"scope_consistency.navigator.{signal}",
                        scope=scope,
                        expected=main_actual,
                        actual=scope_actual,
                        message=f"Main page and {scope} navigator.{signal} values differ",
                    )
            main_ua_data = main_nav.get("userAgentData") if isinstance(main_nav.get("userAgentData"), dict) else None
            scope_ua_data = nav.get("userAgentData") if isinstance(nav.get("userAgentData"), dict) else None
            if main_ua_data and scope_ua_data and main_ua_data.get("platform") != scope_ua_data.get("platform"):
                _add_issue(
                    issues,
                    severity="error",
                    signal="scope_consistency.userAgentData.platform",
                    scope=scope,
                    expected=main_ua_data.get("platform"),
                    actual=scope_ua_data.get("platform"),
                    message=f"Main page and {scope} UA-CH platform values differ",
                )
            scope_intl_values = {
                "Intl.DateTimeFormat": intl.get("dateTime", {}).get("locale"),
                "Intl.NumberFormat": intl.get("number", {}).get("locale"),
                "Intl.Collator": intl.get("collator", {}).get("locale"),
            }
            for signal, actual in scope_intl_values.items():
                expected = main_intl_values[signal]
                if expected and actual and not _locale_matches(str(actual), str(expected)):
                    _add_issue(
                        issues,
                        severity="error",
                        signal=f"scope_consistency.{signal}",
                        scope=scope,
                        expected=expected,
                        actual=actual,
                        message=f"Main page, iframe and Worker {signal} locales differ",
                    )
            scope_timezone = date.get("timezone")
            if main_timezone and scope_timezone and scope_timezone != main_timezone:
                _add_issue(
                    issues,
                    severity="error",
                    signal="scope_consistency.timezone",
                    scope=scope,
                    expected=main_timezone,
                    actual=scope_timezone,
                    message="Main page, iframe and Worker timezones differ",
                )

    main = raw.get("main", {}) if isinstance(raw.get("main"), dict) else {}
    nav = main.get("navigator", {}) if isinstance(main.get("navigator"), dict) else {}
    page = main.get("page", {}) if isinstance(main.get("page"), dict) else {}
    screen = main.get("screen", {}) if isinstance(main.get("screen"), dict) else {}
    graphics = main.get("graphics", {}) if isinstance(main.get("graphics"), dict) else {}
    native_strings = main.get("nativeStrings", {}) if isinstance(main.get("nativeStrings"), dict) else {}
    ua_data = nav.get("userAgentData") if isinstance(nav.get("userAgentData"), dict) else None

    if nav.get("webdriver") is not False:
        _add_issue(
            issues,
            severity="error",
            signal="navigator.webdriver",
            scope="main",
            expected=False,
            actual=nav.get("webdriver"),
            message="navigator.webdriver should be false",
        )

    if page.get("secureContext") is True and not ua_data:
        _add_issue(
            issues,
            severity="warning",
            signal="navigator.userAgentData",
            scope="main",
            expected="present in secure context",
            actual=None,
            message="UA Client Hints are missing in a secure context",
        )

    if ua_data:
        expected_ua_ch_platform = None
        if expected_platform == "macos":
            expected_ua_ch_platform = "macOS"
        elif expected_platform == "windows":
            expected_ua_ch_platform = "Windows"
        if expected_ua_ch_platform and ua_data.get("platform") != expected_ua_ch_platform:
            _add_issue(
                issues,
                severity="warning",
                signal="navigator.userAgentData.platform",
                scope="main",
                expected=expected_ua_ch_platform,
                actual=ua_data.get("platform"),
                message="UA-CH platform does not match the profile platform",
            )

    user_agent = str(nav.get("userAgent") or "")
    platform = str(nav.get("platform") or "")
    if expected_user_agent and user_agent != expected_user_agent:
        _add_issue(
            issues,
            severity="warning",
            signal="userAgent",
            scope="main",
            expected=expected_user_agent,
            actual=user_agent,
            message="实际 User-Agent 与配置值不同；请避免手动填写与内核版本不一致的 UA。",
        )

    chrome_major_match = re.search(r"(?:Chrome|Chromium)/(\d+)", user_agent)
    if chrome_major_match and ua_data:
        brands = ua_data.get("highEntropy", {}).get("fullVersionList") if isinstance(ua_data.get("highEntropy"), dict) else ua_data.get("brands")
        chrome_brand_version = None
        if isinstance(brands, list):
            for brand in brands:
                if isinstance(brand, dict) and brand.get("brand") in {"Google Chrome", "Chromium"}:
                    chrome_brand_version = str(brand.get("version") or "")
                    break
        if chrome_brand_version and chrome_brand_version.split(".", 1)[0] != chrome_major_match.group(1):
            _add_issue(
                issues,
                severity="error",
                signal="ua_ua_ch_version",
                scope="main",
                expected=chrome_major_match.group(1),
                actual=chrome_brand_version,
                message="User-Agent 的 Chrome 主版本与 UA-CH 不一致。",
            )
    if expected_platform == "macos":
        if "Macintosh" not in user_agent or platform != "MacIntel":
            _add_issue(
                issues,
                severity="error",
                signal="platform",
                scope="main",
                expected="Macintosh UA + MacIntel",
                actual={"userAgent": user_agent, "platform": platform},
                message="macOS profile should expose a coherent Mac user agent and platform",
            )
    elif expected_platform == "windows":
        if "Windows NT" not in user_agent or platform not in ("Win32", "Win64"):
            _add_issue(
                issues,
                severity="error",
                signal="platform",
                scope="main",
                expected="Windows NT UA + Win32/Win64",
                actual={"userAgent": user_agent, "platform": platform},
                message="Windows profile should expose a coherent Windows user agent and platform",
            )

    if expected_hardware_concurrency and nav.get("hardwareConcurrency") != expected_hardware_concurrency:
        _add_issue(
            issues,
            severity="warning",
            signal="hardwareConcurrency",
            scope="main",
            expected=expected_hardware_concurrency,
            actual=nav.get("hardwareConcurrency"),
            message="Hardware concurrency differs from the configured profile value",
        )

    if expected_device_memory and nav.get("deviceMemory") not in (None, expected_device_memory):
        _add_issue(
            issues,
            severity="warning",
            signal="deviceMemory",
            scope="main",
            expected=expected_device_memory,
            actual=nav.get("deviceMemory"),
            message="浏览器内存暴露值与画像不同；Chrome 会对该值做粗粒度限制。",
        )

    if expected_screen_width and screen.get("availWidth") not in (None, expected_screen_width):
        _add_issue(
            issues,
            severity="warning",
            signal="screen.availWidth",
            scope="main",
            expected=expected_screen_width,
            actual=screen.get("availWidth"),
            message="Available screen width differs from the configured profile width",
        )
    if expected_screen_height and screen.get("height") not in (None, expected_screen_height):
        _add_issue(
            issues,
            severity="warning",
            signal="screen.height",
            scope="main",
            expected=expected_screen_height,
            actual=screen.get("height"),
            message="Screen height differs from the configured profile height",
        )

    inner_width = screen.get("innerWidth")
    inner_height = screen.get("innerHeight")
    outer_width = screen.get("outerWidth")
    outer_height = screen.get("outerHeight")
    screen_width = screen.get("width")
    screen_height = screen.get("height")
    if isinstance(outer_width, (int, float)) and outer_width <= 0:
        _add_issue(
            issues,
            severity="error",
            signal="window.outerWidth",
            scope="main",
            expected="> 0",
            actual=outer_width,
            message="浏览器窗口宽度为 0，属于不可能的窗口几何值。",
        )
    if isinstance(outer_height, (int, float)) and outer_height <= 0:
        _add_issue(
            issues,
            severity="error",
            signal="window.outerHeight",
            scope="main",
            expected="> 0",
            actual=outer_height,
            message="浏览器窗口高度为 0，属于不可能的窗口几何值。",
        )
    for signal, inner, outer in (
        ("window.width", inner_width, outer_width),
        ("window.height", inner_height, outer_height),
    ):
        if all(isinstance(value, (int, float)) and value > 0 for value in (inner, outer)) and inner > outer:
            _add_issue(
                issues,
                severity="error",
                signal=signal,
                scope="main",
                expected=f"inner <= outer ({outer})",
                actual=inner,
                message="页面内部尺寸大于浏览器外部窗口，窗口画像不一致。",
            )
    for signal, inner, total in (
        ("screen.width_geometry", inner_width, screen_width),
        ("screen.height_geometry", inner_height, screen_height),
    ):
        if all(isinstance(value, (int, float)) and value > 0 for value in (inner, total)) and inner > total:
            _add_issue(
                issues,
                severity="error",
                signal=signal,
                scope="main",
                expected=f"window <= screen ({total})",
                actual=inner,
                message="浏览器内容区域大于画像屏幕尺寸，容易被识别为屏幕参数遮罩。",
            )

    webgl = graphics.get("webgl") if isinstance(graphics.get("webgl"), dict) else {}
    if expected_gpu_vendor and webgl.get("vendor") and str(expected_gpu_vendor).lower() not in str(webgl.get("vendor")).lower():
        _add_issue(
            issues,
            severity="warning",
            signal="webgl.vendor",
            scope="main",
            expected=expected_gpu_vendor,
            actual=webgl.get("vendor"),
            message="WebGL 厂商与画像预期不同；请检查运行环境是否强制了软件渲染。",
        )
    if expected_gpu_renderer and webgl.get("renderer") and str(expected_gpu_renderer).lower() not in str(webgl.get("renderer")).lower():
        _add_issue(
            issues,
            severity="warning",
            signal="webgl.renderer",
            scope="main",
            expected=expected_gpu_renderer,
            actual=webgl.get("renderer"),
            message="WebGL 渲染器与画像预期不同；VNC/软件渲染环境可能覆盖了 GPU。",
        )

    storage = main.get("storage") if isinstance(main.get("storage"), dict) else {}
    for storage_name in ("localStorage", "sessionStorage"):
        value = storage.get(storage_name)
        if isinstance(value, dict) and value.get("available") is False:
            _add_issue(
                issues,
                severity="warning",
                signal=f"storage.{storage_name}",
                scope="main",
                expected="available",
                actual=value,
                message=f"{storage_name} 不可用；这会影响部分网站的登录状态和本地设置。",
            )
    if storage.get("cookieEnabled") is False:
        _add_issue(
            issues,
            severity="error",
            signal="cookies",
            scope="main",
            expected=True,
            actual=False,
            message="浏览器 Cookie 被禁用，网站无法保存登录状态。",
        )

    fonts = main.get("fonts") if isinstance(main.get("fonts"), dict) else {}
    available_fonts = fonts.get("available") if isinstance(fonts.get("available"), list) else []
    if fonts.get("measurable") and expected_platform == "macos" and not any(
        font in available_fonts for font in ("Arial", "Helvetica Neue", "Menlo")
    ):
        _add_issue(
            issues,
            severity="warning",
            signal="fonts.macos_baseline",
            scope="main",
            expected="Arial or Helvetica Neue or Menlo",
            actual=available_fonts,
            message="没有检测到常见 macOS 字体基线；字体目录或运行容器可能与 macOS 画像不匹配。",
        )
    if fonts.get("measurable") and expected_platform == "windows" and not any(
        font in available_fonts for font in ("Arial", "Segoe UI", "Courier New")
    ):
        _add_issue(
            issues,
            severity="warning",
            signal="fonts.windows_baseline",
            scope="main",
            expected="Arial or Segoe UI or Courier New",
            actual=available_fonts,
            message="没有检测到常见 Windows 字体基线；字体目录或运行容器可能与 Windows 画像不匹配。",
        )

    network = main.get("network") if isinstance(main.get("network"), dict) else {}
    external_probe = network.get("externalProbe") if isinstance(network.get("externalProbe"), dict) else None
    if external_probe is None:
        _add_issue(
            issues,
            severity="warning",
            signal="network.external_probe",
            scope="main",
            expected="configured external probe",
            actual=None,
            message="没有收到外部网络探针结果；TLS、出口 IP 和浏览器请求头无法在本地完全验证。",
        )
    elif external_probe.get("error"):
        _add_issue(
            issues,
            severity="warning",
            signal="network.external_probe",
            scope="main",
            expected="successful probe",
            actual=external_probe.get("error"),
            message="外部网络探针请求失败；本次只显示本地代理策略。",
        )
    elif expected_proxy_ip:
        observed_ip = external_probe.get("egress", {}).get("ip") if isinstance(external_probe.get("egress"), dict) else None
        if observed_ip and observed_ip != expected_proxy_ip:
            _add_issue(
                issues,
                severity="warning",
                signal="network.egress_ip",
                scope="main",
                expected=expected_proxy_ip,
                actual=observed_ip,
                message="浏览器外部探针看到的出口 IP 与启动时代理测试 IP 不同，可能是代理轮换或链路配置不一致。",
            )
    if external_probe and not external_probe.get("error"):
        probe_headers = external_probe.get("headers") if isinstance(external_probe.get("headers"), dict) else {}
        observed_ua = probe_headers.get("user_agent")
        observed_language = probe_headers.get("accept_language")
        if expected_user_agent and observed_ua and observed_ua != expected_user_agent:
            _add_issue(
                issues,
                severity="warning",
                signal="network.user_agent_header",
                scope="main",
                expected=expected_user_agent,
                actual=observed_ua,
                message="外部探针收到的 User-Agent 请求头与画像配置不同。",
            )
        if expected_locale and observed_language and not _locale_matches(str(observed_language).split(",", 1)[0], expected_locale):
            _add_issue(
                issues,
                severity="warning",
                signal="network.accept_language",
                scope="main",
                expected=expected_locale,
                actual=observed_language,
                message="外部探针收到的 Accept-Language 请求头与画像语言不同。",
            )
    candidates = network.get("webrtcCandidates")
    if proxy_configured and isinstance(candidates, list) and any("typ host" in str(candidate).lower() for candidate in candidates):
        _add_issue(
            issues,
            severity="warning",
            signal="webrtc.host_candidates",
            scope="main",
            expected="no non-proxied host candidates",
            actual=candidates,
            message="WebRTC 仍产生本地候选地址；已配置代理时请结合浏览器设置和外部页面继续确认是否有公网泄漏。",
        )

    if graphics.get("canvasHashA") != graphics.get("canvasHashB"):
        _add_issue(
            issues,
            severity="error",
            signal="canvas_stability",
            scope="main",
            expected=graphics.get("canvasHashA"),
            actual=graphics.get("canvasHashB"),
            message="Canvas fingerprint changes within the same page",
        )
    if graphics.get("audioHashA") != graphics.get("audioHashB"):
        _add_issue(
            issues,
            severity="error",
            signal="audio_stability",
            scope="main",
            expected=graphics.get("audioHashA"),
            actual=graphics.get("audioHashB"),
            message="Audio fingerprint changes within the same page",
        )

    for signal, value in native_strings.items():
        if isinstance(value, str) and "[native code]" not in value:
            _add_issue(
                issues,
                severity="error",
                signal=f"native_string.{signal}",
                scope="main",
                expected="[native code]",
                actual=value[:160],
                message="A patched browser API exposes non-native function source",
            )

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    score = max(0, 100 - error_count * 18 - warning_count * 6)
    status = "pass" if error_count == 0 and warning_count <= 1 else "warning"
    if error_count:
        status = "fail"

    return {
        "status": status,
        "score": score,
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }


async def run_fingerprint_probe(context: Any) -> dict[str, Any]:
    page = await context.new_page()
    try:
        probe_error = None
        try:
            await page.goto(PROBE_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            probe_error = str(exc)
            await page.goto(FALLBACK_PROBE_URL)
        await page.evaluate(
            "url => { window.__CLOAK_NETWORK_PROBE_URL = url; }",
            os.environ.get("CLOAKBROWSER_NETWORK_PROBE_URL") or DEFAULT_NETWORK_PROBE_URL,
        )
        raw = await asyncio.wait_for(page.evaluate(DIAGNOSTIC_SCRIPT), timeout=20)
        if probe_error:
            raw["probe_error"] = probe_error
            raw["probe_fallback"] = FALLBACK_PROBE_URL
        else:
            raw["probe_url"] = PROBE_URL
        return raw
    finally:
        await page.close()
