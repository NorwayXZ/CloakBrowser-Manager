"""The panel redesign must not lose any API the current panel or MCP uses.

docs/redesign/openapi-baseline.json is the v0.7.2 contract (regenerate with
scripts/export_openapi.py only when an endpoint is removed on purpose). New
endpoints are fine; a missing method + path, or a request body that changed
its schema, fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend import main

BASELINE = Path(__file__).resolve().parents[2] / "docs" / "redesign" / "openapi-baseline.json"
METHODS = {"get", "post", "put", "patch", "delete"}


def _operations(spec: dict) -> dict[tuple[str, str], dict]:
    return {
        (method.upper(), path): op
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in METHODS
    }


def _body_ref(op: dict) -> str | None:
    content = op.get("requestBody", {}).get("content", {})
    for media in content.values():
        return json.dumps(media.get("schema"), sort_keys=True)
    return None


def test_every_baseline_operation_still_exists():
    baseline = _operations(json.loads(BASELINE.read_text(encoding="utf-8")))
    current = _operations(main.app.openapi())
    missing = sorted(set(baseline) - set(current))
    assert not missing, f"endpoints removed since the baseline: {missing}"


def test_request_bodies_keep_their_schema():
    baseline = _operations(json.loads(BASELINE.read_text(encoding="utf-8")))
    current = _operations(main.app.openapi())
    changed = sorted(
        key for key, op in baseline.items()
        if key in current and _body_ref(op) != _body_ref(current[key])
    )
    assert not changed, f"request body schema changed since the baseline: {changed}"
