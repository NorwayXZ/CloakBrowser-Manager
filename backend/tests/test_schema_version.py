"""The database remembers which layout version wrote it, so a downgrade can be noticed."""

import logging

import pytest
from fastapi.testclient import TestClient

from backend import database as db


def test_fresh_database_is_stamped_with_the_current_version(tmp_db):
    db.init_db()
    assert db.stored_schema_version() == db.SCHEMA_VERSION
    assert db.data_is_newer_than_program() is False


def test_older_or_unversioned_data_is_upgraded_to_the_current_version(tmp_db):
    db.init_db()
    db.set_setting(db.SETTING_SCHEMA_VERSION, "0")
    db.init_db()
    assert db.stored_schema_version() == db.SCHEMA_VERSION


def test_data_from_a_newer_release_is_kept_as_it_is_and_reported(tmp_db, caplog: pytest.LogCaptureFixture):
    db.init_db()
    newer = str(db.SCHEMA_VERSION + 1)
    db.set_setting(db.SETTING_SCHEMA_VERSION, newer)
    with caplog.at_level(logging.WARNING, logger="backend.database"):
        db.init_db()
    assert db.stored_schema_version() == db.SCHEMA_VERSION + 1
    assert db.data_is_newer_than_program() is True
    assert "newer than this program supports" in caplog.text


def test_an_unreadable_stored_version_counts_as_unversioned(tmp_db):
    db.init_db()
    db.set_setting(db.SETTING_SCHEMA_VERSION, "not a number")
    assert db.stored_schema_version() is None
    assert db.data_is_newer_than_program() is False
    db.init_db()
    assert db.stored_schema_version() == db.SCHEMA_VERSION


def test_status_tells_the_panel_when_data_is_newer(app_client: TestClient):
    assert app_client.get("/api/status").json()["data_newer_than_app"] is False
    db.set_setting(db.SETTING_SCHEMA_VERSION, str(db.SCHEMA_VERSION + 1))
    assert app_client.get("/api/status").json()["data_newer_than_app"] is True
