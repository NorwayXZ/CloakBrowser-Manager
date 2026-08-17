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
