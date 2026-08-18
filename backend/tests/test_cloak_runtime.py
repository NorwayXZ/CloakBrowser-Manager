"""Tests for effective CloakBrowser binary version reporting."""

from pathlib import Path
import sys
import types

import cloakbrowser
import cloakbrowser.config as cloak_config
import pytest

from backend.cloak_runtime import get_effective_chromium_version, inspect_cloak_runtime


def test_effective_version_prefers_update_marker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cloak_config, "get_effective_version", lambda: "150.0.1.2.3", raising=False)
    monkeypatch.setattr(cloak_config, "get_chromium_version", lambda: "145.0.1.2.3", raising=False)

    assert get_effective_chromium_version() == "150.0.1.2.3"


def test_effective_version_reads_license_scoped_marker(monkeypatch: pytest.MonkeyPatch):
    cloak_license = types.ModuleType("cloakbrowser.license")
    seen: list[bool] = []

    def effective(*, pro: bool = False):
        seen.append(pro)
        return "150.0.1.2.3" if pro else "145.0.1.2.3"

    cloak_license.resolve_license_key = lambda: "free-key"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloakbrowser.license", cloak_license)
    monkeypatch.setattr(cloak_config, "get_effective_version", effective, raising=False)

    assert get_effective_chromium_version() == "150.0.1.2.3"
    assert seen == [True]


def test_inspect_runtime_verifies_effective_cached_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    version = "150.0.1.2.3"
    binary = tmp_path / f"chromium-{version}" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"runtime")

    cloak_download = types.ModuleType("cloakbrowser.download")
    cloak_download.ensure_binary = lambda: str(binary)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloakbrowser.download", cloak_download)

    monkeypatch.setattr(cloakbrowser, "__version__", "0.5.7", raising=False)
    monkeypatch.setattr(cloak_config, "get_effective_version", lambda: version, raising=False)
    monkeypatch.setattr(cloak_config, "get_chromium_version", lambda: "145.0.1.2.3", raising=False)
    monkeypatch.setattr(cloak_config, "get_platform_tag", lambda: "darwin-arm64", raising=False)
    result = inspect_cloak_runtime(ensure_binary=True)

    assert result.configured_version == "145.0.1.2.3"
    assert result.effective_version == version
    assert result.binary_version == version
    assert result.binary_verified is True


def test_inspect_runtime_rejects_stale_cached_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    binary = tmp_path / "chromium-145.0.1.2.3" / "chrome.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"runtime")

    cloak_download = types.ModuleType("cloakbrowser.download")
    cloak_download.ensure_binary = lambda: str(binary)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloakbrowser.download", cloak_download)

    monkeypatch.setattr(cloak_config, "get_effective_version", lambda: "150.0.1.2.3", raising=False)
    monkeypatch.setattr(cloak_config, "get_chromium_version", lambda: "145.0.1.2.3", raising=False)
    assert inspect_cloak_runtime(ensure_binary=True).binary_verified is False
