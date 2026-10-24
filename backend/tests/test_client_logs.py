"""Panel log upload, UI preferences, and which page /next/ serves."""

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
    assert app_client.get("/api/settings/ui").json() == {"theme": "system", "sidebar_collapsed": False}
    resp = app_client.put("/api/settings/ui", json={"theme": "dark", "sidebar_collapsed": True})
    assert resp.status_code == 200
    assert app_client.get("/api/settings/ui").json() == {"theme": "dark", "sidebar_collapsed": True}


def test_ui_preferences_reject_unknown_theme(app_client: TestClient):
    assert app_client.put("/api/settings/ui", json={"theme": "sepia"}).status_code == 422


def test_ui_preferences_fall_back_when_stored_value_is_unreadable(app_client: TestClient):
    db.set_setting(main.UI_PREFERENCES_SETTING_KEY, "{not json")
    assert app_client.get("/api/settings/ui").json() == {"theme": "system", "sidebar_collapsed": False}


def test_spa_page_serves_next_only_under_next(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "next").mkdir()
    (tmp_path / "index.html").write_text("old")
    (tmp_path / "next" / "index.html").write_text("new")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    assert main._spa_page("") == tmp_path / "index.html"
    assert main._spa_page("profiles") == tmp_path / "index.html"
    assert main._spa_page("nextgen") == tmp_path / "index.html"
    assert main._spa_page("next") == tmp_path / "next" / "index.html"
    assert main._spa_page("next/settings/appearance") == tmp_path / "next" / "index.html"


def test_spa_page_falls_back_when_next_was_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "index.html").write_text("old")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    assert main._spa_page("next/settings") == tmp_path / "index.html"
