"""Write the Manager's OpenAPI document as stable, sorted JSON.

The redesigned panel must keep every existing endpoint working, so the
document is committed as a contract snapshot (docs/redesign/openapi-baseline.json)
and later checks compare against it. Importing the app resolves its data
directory at import time, so it is pointed at a throwaway folder first: this
script never reads or creates the user's real profiles.db or .secret_key.

Usage: python scripts/export_openapi.py [output.json]   (default: stdout)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def export() -> str:
    os.environ["CLOAKBROWSER_MANAGER_DATA_DIR"] = tempfile.mkdtemp(prefix="cbm-openapi-data-")
    os.environ["CLOAKBROWSER_MANAGER_BACKUP_COPY_DIR"] = tempfile.mkdtemp(prefix="cbm-openapi-backup-")
    sys.path.insert(0, str(ROOT))
    from backend.main import app

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = export()
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)  # a fresh checkout has no build/
        target.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
