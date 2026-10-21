"""Regression tests: Chromium JSON files must be read as UTF-8 explicitly.

On zh-CN Windows the Python default text encoding is GBK. Chromium writes
Preferences/Local State as UTF-8; once a profile has real browsing state,
its Preferences contain UTF-8 byte runs that GBK cannot decode (an odd-length
CJK run before a quote is enough). ``Path.read_text()`` without an encoding
then raises UnicodeDecodeError inside profile launch — which is neither an
OSError nor a JSONDecodeError, so it escaped the old ``except`` and failed
the launch with HTTP 400 ("'gbk' codec can't decode byte 0x91 ...").
Found on a physical zh-CN Windows machine, 2026-10-21.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.browser_manager import _read_json_file, _write_json_file

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_read_json_file_survives_invalid_utf8(tmp_path: Path) -> None:
    """Bytes that are not valid UTF-8 must degrade to {}, never raise."""
    prefs = tmp_path / "Preferences"
    prefs.write_bytes(b'{"intl": {"name": "\xff\xfe invalid"}}')
    assert _read_json_file(prefs) == {}


def test_read_json_file_roundtrip_non_ascii(tmp_path: Path) -> None:
    prefs = tmp_path / "Preferences"
    data = {"intl": {"accept_languages": "zh-HK", "name": "港"}}
    _write_json_file(prefs, data)
    assert _read_json_file(prefs) == data


@pytest.mark.skipif(os.name == "nt", reason="hostile locale is forced via POSIX env vars")
def test_read_json_file_utf8_under_non_utf8_default_encoding(tmp_path: Path) -> None:
    """Simulate a non-UTF-8 default locale (GBK on zh-CN Windows, ASCII here).

    The Preferences file is written as raw UTF-8 bytes with an odd-length CJK
    run before a closing quote — the exact shape that broke GBK decoding in
    production. The helper must still parse it.
    """
    prefs = tmp_path / "Preferences"
    prefs.write_bytes('{"intl": {"name": "港"}}'.encode("utf-8"))
    snippet = (
        "import json, locale, sys\n"
        "from pathlib import Path\n"
        "enc = locale.getpreferredencoding(False)\n"
        "if enc.lower().replace('-', '').replace('_', '') in ('utf8',):\n"
        "    print('VACUOUS'); sys.exit(3)\n"
        "from backend.browser_manager import _read_json_file\n"
        f"result = _read_json_file(Path({str(prefs)!r}))\n"
        "print(json.dumps(result))\n"
    )
    env = dict(
        os.environ,
        LC_ALL="C",
        PYTHONUTF8="0",
        PYTHONCOERCECLOCALE="0",
        PYTHONPATH=str(REPO_ROOT),
    )
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
    )
    if proc.returncode == 3:
        pytest.skip("could not force a non-UTF-8 default encoding in subprocess")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip()) == {"intl": {"name": "港"}}
