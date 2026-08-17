"""Windows-only runtime smoke test used by GitHub Actions."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.xray_runtime import XRAY_DATA_FILES, ensure_xray_runtime


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _verify_chromium_runtime(chromium: Path, data_dir: Path) -> str:
    """Start Chromium and verify its runtime endpoint instead of using --version.

    Windows Chromium is a GUI executable. Some builds keep the process alive when
    passed --version, so that flag is not a reliable CI probe.
    """
    port = _unused_local_port()
    user_data_dir = data_dir / "chromium-profile"
    process = subprocess.Popen(
        [
            str(chromium),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={user_data_dir}",
            f"--remote-debugging-port={port}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"CloakBrowser exited before its runtime endpoint was ready "
                    f"(exit code {process.returncode})"
                )
            try:
                with urllib.request.urlopen(endpoint, timeout=2) as response:
                    payload = json.load(response)
                browser = str(payload.get("Browser", ""))
                if not browser:
                    raise RuntimeError("CloakBrowser runtime returned no browser version")
                return browser
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                time.sleep(0.5)
        raise TimeoutError("CloakBrowser runtime endpoint was not ready within 45 seconds")
    finally:
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="cloakbrowser-windows-smoke-"))
    try:
        binary, assets = asyncio.run(ensure_xray_runtime(data_dir))
        assert binary.name == "xray.exe", binary
        assert assets.is_dir(), assets
        for filename in XRAY_DATA_FILES:
            path = assets / filename
            assert path.is_file() and path.stat().st_size > 0, path

        result = subprocess.run(
            [str(binary), "version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "Xray" in (result.stdout + result.stderr)

        # A hosted runner cannot reliably show a window, but headless startup
        # still validates that the downloaded Windows runtime can execute.
        from cloakbrowser.download import ensure_binary

        chromium = Path(ensure_binary())
        assert chromium.is_file() and chromium.stat().st_size > 0, chromium
        print("CloakBrowser:", _verify_chromium_runtime(chromium, data_dir))
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
