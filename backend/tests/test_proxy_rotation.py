"""Rotating exit IPs: spotting them in a lookup and warning before launch."""

from __future__ import annotations

from pathlib import Path

from backend.browser_manager import BrowserManager
from backend.proxy_geo import exit_ip_spread
from backend.runtime import RuntimeConfig


def test_one_exit_ip_is_not_rotating():
    assert exit_ip_spread([{"ip": "60.66.231.77"}, {"ip": "60.66.231.77"}]) == (["60.66.231.77"], False)


def test_two_ipv4_exits_are_rotating():
    ips, rotating = exit_ip_spread([{"ip": "60.66.231.77"}, {"ip": "150.31.13.127"}, {"ip": None}])

    assert rotating is True
    assert ips == ["150.31.13.127", "60.66.231.77"]


def test_dual_stack_direct_connection_is_not_rotating():
    ips, rotating = exit_ip_spread([{"ip": "103.100.176.106"}, {"ip": "2408:8256::1"}])

    assert rotating is False
    assert len(ips) == 2


def _preflight(tmp_path: Path, profile: dict) -> set[str]:
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    base = {"platform": "macos", "browser_engine": "cloakbrowser", "screen_width": 1512, "screen_height": 982}
    return {issue["code"] for issue in manager.preflight({**base, **profile})["issues"]}


def test_preflight_warns_after_a_rotating_exit_was_seen(tmp_path: Path):
    codes = _preflight(tmp_path, {"proxy_geo": {"ip": "1.2.3.4", "exit_ips": ["1.2.3.4", "5.6.7.8"], "rotating_ip": True}})

    assert "rotating_exit_ip" in codes


def test_preflight_notes_the_linkage_risk_of_noise_off(tmp_path: Path):
    assert "noise_off_linkable" in _preflight(tmp_path, {"fingerprint_options": {"noise": False}})
    assert "noise_off_linkable" not in _preflight(tmp_path, {"fingerprint_options": {"noise": True}})
