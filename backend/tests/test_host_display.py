"""Tests for reading the computer's own screen size."""

from __future__ import annotations

import pytest

from backend import host_display


def test_screen_size_is_unknown_off_macos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_display.sys, "platform", "win32")

    assert host_display.primary_screen_size() is None


def test_screen_size_rounds_points(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_display.sys, "platform", "darwin")
    monkeypatch.setattr(host_display, "_macos_primary_screen", lambda: (1511.6, 982.0))

    assert host_display.primary_screen_size() == (1512, 982)


@pytest.mark.parametrize("size", [(0.0, 0.0), (200.0, 900.0)])
def test_screen_size_ignores_missing_displays(monkeypatch: pytest.MonkeyPatch, size):
    monkeypatch.setattr(host_display.sys, "platform", "darwin")
    monkeypatch.setattr(host_display, "_macos_primary_screen", lambda: size)

    assert host_display.primary_screen_size() is None


def test_screen_size_survives_a_missing_framework(monkeypatch: pytest.MonkeyPatch):
    def broken():
        raise OSError("no CoreGraphics")

    monkeypatch.setattr(host_display.sys, "platform", "darwin")
    monkeypatch.setattr(host_display, "_macos_primary_screen", broken)

    assert host_display.primary_screen_size() is None
