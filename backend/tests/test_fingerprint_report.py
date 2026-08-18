"""Tests for the local fingerprint self-check analysis rules."""

from __future__ import annotations

from backend.fingerprint_report import analyze_fingerprint


def _raw_platform(
    *,
    user_agent: str,
    platform: str,
    ua_ch_platform: str,
) -> dict:
    return {
        "main": {
            "navigator": {
                "webdriver": False,
                "userAgent": user_agent,
                "platform": platform,
                "userAgentData": {"platform": ua_ch_platform},
            },
            "page": {"secureContext": True},
            "screen": {},
            "graphics": {},
            "nativeStrings": {},
        },
    }


def _analyze(raw: dict, expected_platform: str) -> dict:
    return analyze_fingerprint(
        raw,
        expected_locale=None,
        expected_timezone=None,
        expected_platform=expected_platform,
        expected_screen_width=None,
        expected_screen_height=None,
        expected_hardware_concurrency=None,
    )


def test_windows_platform_values_pass():
    result = _analyze(
        _raw_platform(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            platform="Win32",
            ua_ch_platform="Windows",
        ),
        "windows",
    )

    assert not [issue for issue in result["issues"] if issue["signal"] in {"platform", "navigator.userAgentData.platform"}]


def test_windows_platform_mismatch_is_reported():
    result = _analyze(
        _raw_platform(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            platform="MacIntel",
            ua_ch_platform="macOS",
        ),
        "windows",
    )

    signals = {issue["signal"] for issue in result["issues"]}
    assert "platform" in signals
    assert "navigator.userAgentData.platform" in signals


def test_scope_locale_and_timezone_mismatch_is_reported_without_expected_values():
    main = {
        "navigator": {"language": "en-US", "languages": ["en-US"]},
        "intl": {
            "dateTime": {"locale": "en-US"},
            "number": {"locale": "en-US"},
            "collator": {"locale": "en-US"},
        },
        "date": {"timezone": "America/New_York"},
    }
    iframe = {
        "navigator": {"language": "fr-FR", "languages": ["fr-FR"]},
        "intl": {
            "dateTime": {"locale": "fr-FR"},
            "number": {"locale": "fr-FR"},
            "collator": {"locale": "fr-FR"},
        },
        "date": {"timezone": "Europe/Paris"},
    }
    result = analyze_fingerprint(
        {"main": main, "iframe": iframe, "worker": iframe},
        expected_locale=None,
        expected_timezone=None,
        expected_platform=None,
        expected_screen_width=None,
        expected_screen_height=None,
        expected_hardware_concurrency=None,
    )

    signals = {issue["signal"] for issue in result["issues"]}
    assert "scope_consistency.navigator.language" in signals
    assert "scope_consistency.timezone" in signals


def test_external_probe_matching_ip_does_not_report_egress_mismatch():
    raw = {
        "main": {
            "navigator": {"userAgent": "UA", "language": "en-US", "languages": ["en-US"]},
            "network": {
                "externalProbe": {
                    "egress": {"ip": "203.0.113.10"},
                    "transport": {"tls_version": "TLSv1.3"},
                    "headers": {"user_agent": "UA", "accept_language": "en-US,en;q=0.9"},
                },
            },
        },
    }
    result = analyze_fingerprint(
        raw,
        expected_locale="en-US",
        expected_timezone=None,
        expected_platform=None,
        expected_screen_width=None,
        expected_screen_height=None,
        expected_hardware_concurrency=None,
        expected_user_agent="UA",
        expected_proxy_ip="203.0.113.10",
    )

    assert "network.egress_ip" not in {issue["signal"] for issue in result["issues"]}


def test_external_probe_mismatch_is_reported():
    raw = {"main": {"navigator": {}, "network": {"externalProbe": {"egress": {"ip": "198.51.100.20"}}}}}
    result = analyze_fingerprint(
        raw,
        expected_locale=None,
        expected_timezone=None,
        expected_platform=None,
        expected_screen_width=None,
        expected_screen_height=None,
        expected_hardware_concurrency=None,
        expected_proxy_ip="203.0.113.10",
    )

    assert "network.egress_ip" in {issue["signal"] for issue in result["issues"]}


def test_external_probe_failure_is_a_warning():
    raw = {"main": {"navigator": {}, "network": {"externalProbe": {"error": "AbortError"}}}}
    result = analyze_fingerprint(
        raw,
        expected_locale=None,
        expected_timezone=None,
        expected_platform=None,
        expected_screen_width=None,
        expected_screen_height=None,
        expected_hardware_concurrency=None,
    )

    issue = next(issue for issue in result["issues"] if issue["signal"] == "network.external_probe")
    assert issue["severity"] == "warning"


def test_impossible_window_geometry_is_reported():
    raw = _raw_platform(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        platform="MacIntel",
        ua_ch_platform="macOS",
    )
    raw["main"]["screen"] = {
        "width": 1512,
        "height": 982,
        "innerWidth": 1646,
        "innerHeight": 1167,
        "outerWidth": 0,
        "outerHeight": 0,
    }

    result = _analyze(raw, "macos")
    signals = {issue["signal"] for issue in result["issues"]}

    assert "window.outerWidth" in signals
    assert "window.outerHeight" in signals
    assert "screen.width_geometry" in signals
    assert "screen.height_geometry" in signals
