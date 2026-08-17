"""macOS and Windows runtime smoke test used by GitHub Actions."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.cloak_runtime import get_effective_chromium_version
from backend.xray_runtime import XRAY_DATA_FILES, ensure_xray_runtime


def _runtime_version(product: str) -> str | None:
    match = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", product)
    return match.group(1) if match else None


def _expected_runtime_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 4 or not all(part.isdigit() for part in parts[:4]):
        raise AssertionError(f"Unexpected CloakBrowser version format: {version}")
    return ".".join(parts[:4])


async def _verify_chromium_runtime(expected: str) -> str:
    """Launch through the public wrapper and verify renderer plus runtime version."""
    from cloakbrowser import launch_async

    browser = await asyncio.wait_for(launch_async(headless=True), timeout=45)
    try:
        product = str(browser.version)
        actual = _runtime_version(product)
        if actual != _expected_runtime_version(expected):
            raise RuntimeError(
                f"CloakBrowser runtime version mismatch: expected {expected}, "
                f"reported {product or 'nothing'}"
            )
        page = await browser.new_page()
        await page.goto("data:text/html,<title>runtime-ready</title><p>ready</p>")
        if await page.text_content("p") != "ready":
            raise RuntimeError("CloakBrowser renderer did not return the smoke page")
        return product
    finally:
        await browser.close()


def main() -> None:
    if sys.platform not in {"darwin", "win32"}:
        raise RuntimeError("Native runtime smoke only supports macOS and Windows")
    data_dir = Path(tempfile.mkdtemp(prefix="cloakbrowser-native-smoke-"))
    try:
        binary, assets = asyncio.run(ensure_xray_runtime(data_dir))
        expected_xray_name = "xray.exe" if os.name == "nt" else "xray"
        assert binary.name == expected_xray_name, binary
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

        from cloakbrowser.download import ensure_binary

        expected = get_effective_chromium_version()
        chromium = Path(ensure_binary())
        assert chromium.is_file() and chromium.stat().st_size > 0, chromium
        product = asyncio.run(_verify_chromium_runtime(expected))
        print(f"CloakBrowser: {product} (package effective version {expected})")
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
