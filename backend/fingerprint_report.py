"""Local fingerprint consistency diagnostics for running profiles."""

from __future__ import annotations

import asyncio
from typing import Any


PROBE_URL = "https://example.com/"
FALLBACK_PROBE_URL = "data:text/html,<title>fingerprint-probe</title><body></body>"


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
      };
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

    if ua_data and expected_platform == "macos" and ua_data.get("platform") not in ("macOS", "macos"):
        _add_issue(
            issues,
            severity="warning",
            signal="navigator.userAgentData.platform",
            scope="main",
            expected="macOS",
            actual=ua_data.get("platform"),
            message="UA-CH platform does not match the profile platform",
        )

    user_agent = str(nav.get("userAgent") or "")
    platform = str(nav.get("platform") or "")
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
        raw = await asyncio.wait_for(page.evaluate(DIAGNOSTIC_SCRIPT), timeout=20)
        if probe_error:
            raw["probe_error"] = probe_error
            raw["probe_fallback"] = FALLBACK_PROBE_URL
        else:
            raw["probe_url"] = PROBE_URL
        return raw
    finally:
        await page.close()
