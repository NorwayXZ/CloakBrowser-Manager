"""Panel log upload, UI preferences, and which page the server hands out."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend import client_logs
from backend import database as db
from backend import main


def test_redact_masks_proxy_credentials_and_secret_values():
    text = "socks5://alice:s3cret@203.0.113.9:1080 password=hunter2 token: abc123 api_key=\"xyz\""
    out = client_logs.redact(text)
    assert "alice" not in out and "s3cret" not in out
    assert "hunter2" not in out and "abc123" not in out and "xyz" not in out
    assert "socks5://***:***@203.0.113.9:1080" in out


def test_rate_limiter_drops_over_the_limit_and_recovers_after_the_window():
    now = [0.0]
    limiter = client_logs.RateLimiter(limit=3, window=60, clock=lambda: now[0])
    assert limiter.take(2) == 2
    assert limiter.take(5) == 1
    assert limiter.take(1) == 0
    now[0] = 61.0
    assert limiter.take(4) == 3


def test_write_entries_logs_one_line_per_entry(caplog: pytest.LogCaptureFixture):
    limiter = client_logs.RateLimiter(limit=10)
    with caplog.at_level(logging.INFO, logger="cloakbrowser.frontend"):
        accepted, dropped = client_logs.write_entries(
            [
                {"level": "error", "message": "boom\nsecond line", "route": "/next/settings", "action": "save", "detail": "cookie=abc"},
                {"level": "warn", "message": "slow"},
            ],
            limiter,
        )
    assert (accepted, dropped) == (2, 0)
    lines = [r.getMessage() for r in caplog.records if r.name == "cloakbrowser.frontend"]
    assert len(lines) == 2
    assert "[/next/settings] save: boom ⏎ second line" in lines[0]
    assert "abc" not in lines[0]
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.records[1].levelno == logging.WARNING


def test_write_entries_reports_dropped(caplog: pytest.LogCaptureFixture):
    limiter = client_logs.RateLimiter(limit=1)
    with caplog.at_level(logging.WARNING, logger="cloakbrowser.frontend"):
        assert client_logs.write_entries([{"message": "a"}, {"message": "b"}], limiter) == (1, 1)
    assert any("Dropped 1 panel log entries" in r.getMessage() for r in caplog.records)


def test_client_logs_endpoint_accepts_a_batch(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(client_logs, "_limiter", client_logs.RateLimiter(limit=1))
    resp = app_client.post("/api/client-logs", json={"entries": [{"message": "x"}, {"message": "y", "level": "warn"}]})
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "dropped": 1}


def test_client_logs_endpoint_rejects_bad_batches(app_client: TestClient):
    assert app_client.post("/api/client-logs", json={"entries": []}).status_code == 422
    assert app_client.post("/api/client-logs", json={"entries": [{"message": "x" * 2001}]}).status_code == 422
    assert app_client.post("/api/client-logs", json={"entries": [{"message": "x", "level": "fatal"}]}).status_code == 422
    assert app_client.post("/api/client-logs", json={"entries": [{"message": "x"}] * 51}).status_code == 422


def test_ui_preferences_default_then_round_trip(app_client: TestClient):
    assert app_client.get("/api/settings/ui").json() == {"theme": "system", "sidebar_collapsed": False, "interface": "new"}
    resp = app_client.put("/api/settings/ui", json={"theme": "dark", "sidebar_collapsed": True})
    assert resp.status_code == 200
    assert app_client.get("/api/settings/ui").json() == {"theme": "dark", "sidebar_collapsed": True, "interface": "new"}


def test_ui_preferences_reject_unknown_theme(app_client: TestClient):
    assert app_client.put("/api/settings/ui", json={"theme": "sepia"}).status_code == 422


def test_ui_preferences_fall_back_when_stored_value_is_unreadable(app_client: TestClient):
    db.set_setting(main.UI_PREFERENCES_SETTING_KEY, "{not json")
    assert app_client.get("/api/settings/ui").json() == {"theme": "system", "sidebar_collapsed": False, "interface": "new"}


def _built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, legacy: bool = True):
    (tmp_path / "index.html").write_text("new")
    if legacy:
        (tmp_path / "legacy").mkdir()
        (tmp_path / "legacy" / "index.html").write_text("old")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)


def test_spa_page_serves_the_new_panel_by_default_and_the_old_one_under_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _built(tmp_path, monkeypatch)
    new, old = tmp_path / "index.html", tmp_path / "legacy" / "index.html"
    assert main._spa_page("") == new
    assert main._spa_page("profiles") == new
    assert main._spa_page("settings/about") == new
    assert main._spa_page("legacygen") == new
    assert main._spa_page("legacy") == old
    assert main._spa_page("legacy/anything") == old


def test_spa_page_root_follows_the_saved_interface_preference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _built(tmp_path, monkeypatch)
    new, old = tmp_path / "index.html", tmp_path / "legacy" / "index.html"
    assert main._spa_page("", "legacy") == old
    # Only the root follows it: a deep link into the new panel stays in the new panel.
    assert main._spa_page("profiles", "legacy") == new
    assert main._spa_page("", "new") == new


def test_spa_page_falls_back_to_the_new_panel_when_legacy_was_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _built(tmp_path, monkeypatch, legacy=False)
    assert main._spa_page("legacy") == tmp_path / "index.html"
    assert main._spa_page("", "legacy") == tmp_path / "index.html"


def test_root_serves_the_page_the_preference_asks_for(app_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _built(tmp_path, monkeypatch)
    assert app_client.get("/").text == "new"
    assert app_client.put("/api/settings/ui", json={"theme": "dark", "sidebar_collapsed": False, "interface": "legacy"}).json()["interface"] == "legacy"
    assert app_client.get("/").text == "old"
    assert app_client.get("/profiles").text == "new"
    assert app_client.get("/legacy/").text == "old"
    assert app_client.get("/").headers["cache-control"] == "no-cache"
    assert app_client.put("/api/settings/ui", json={"theme": "dark", "sidebar_collapsed": False}).json()["interface"] == "new"
    assert app_client.get("/").text == "new"


def test_old_preview_addresses_redirect_to_the_same_page_without_next(app_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _built(tmp_path, monkeypatch)
    for source, target in [("/next", "/"), ("/next/", "/"), ("/next/settings/about", "/settings/about"), ("/next/checks?report=abc", "/checks?report=abc")]:
        response = app_client.get(source, follow_redirects=False)
        assert response.status_code == 307, source
        assert response.headers["location"] == target, source
    assert app_client.get("/nextgen").text == "new"


def test_interface_preference_defaults_to_new_and_rejects_unknown_values(app_client: TestClient):
    assert app_client.get("/api/settings/ui").json()["interface"] == "new"
    assert app_client.put("/api/settings/ui", json={"theme": "system", "sidebar_collapsed": False, "interface": "classic"}).status_code == 422
    db.set_setting(main.UI_PREFERENCES_SETTING_KEY, '{"theme": "dark", "sidebar_collapsed": true}')
    assert app_client.get("/api/settings/ui").json() == {"theme": "dark", "sidebar_collapsed": True, "interface": "new"}
