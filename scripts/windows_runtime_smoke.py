"""Windows-only runtime smoke test used by GitHub Actions."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.xray_runtime import XRAY_DATA_FILES, ensure_xray_runtime


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

        # The wrapper download is intentionally exercised only for --version;
        # launching a visible browser is not reliable on a hosted runner.
        from cloakbrowser.download import ensure_binary

        chromium = Path(ensure_binary())
        assert chromium.exists(), chromium
        version = subprocess.run(
            [str(chromium), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print("CloakBrowser:", (version.stdout or version.stderr).strip())
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
