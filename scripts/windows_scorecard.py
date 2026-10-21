"""Run one Windows profile through the Manager's own site checks in CI.

Starts from an already-running Manager server (see the windows-scorecard
workflow), creates a throwaway Windows / CloakBrowser profile, triggers
POST /api/profiles/{id}/site-check, waits for the job, and renders the
saved report as SCORECARD.md plus the raw report.json.

This is a measurement, not a gate: verdicts from the detection sites are
reported as-is and the script exits 0 unless the check itself failed to
run. CI caveats that belong in every reading of the result: the runner has
a datacenter IP (hurts IP-reputation verdicts) and no real GPU (WebGL
renders in software), neither of which says anything about the kernel or
the profile configuration.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ.get("SCORECARD_BASE", "http://127.0.0.1:18080")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "scorecard-out")
TIMEOUT_SECONDS = int(os.environ.get("SCORECARD_TIMEOUT", "1500"))


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def main() -> int:
    # Windows consoles default to a legacy code page; the report is Chinese.
    # Without this the final print raises UnicodeEncodeError after all the
    # work is done and the step fails for a cosmetic reason (run #2).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "windows-scorecard",
        "browser_engine": "cloakbrowser",
        "platform": "windows",
    }
    proxy = os.environ.get("SCORECARD_PROXY", "").strip()
    if proxy:
        # Value comes from a GitHub Actions secret; never print it.
        payload["proxy"] = proxy
        print("profile will use the configured proxy (value hidden)", flush=True)
    fp_options = os.environ.get("SCORECARD_FP_OPTIONS", "").strip()
    if fp_options:
        # A/B experiments: JSON object of fingerprint_options from the
        # workflow_dispatch input, e.g. {"noise": false}.
        payload["fingerprint_options"] = json.loads(fp_options)
        print(f"fingerprint_options override: {fp_options}", flush=True)
    profile = call("POST", "/api/profiles", payload)
    profile_id = profile["id"]
    print(f"created profile {profile_id}", flush=True)
    try:
        state = call("POST", f"/api/profiles/{profile_id}/site-check")
        print(f"site check started: {state.get('phase')}", flush=True)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            state = call("GET", "/api/site-checks/current")
            phase = state.get("phase")
            print(f"phase={phase} site={state.get('site')} "
                  f"{state.get('index')}/{state.get('total')}", flush=True)
            if phase in {"done", "failed"}:
                break
            time.sleep(10)
        if state.get("phase") != "done":
            print(f"check did not finish cleanly: {state}", flush=True)
            return 2
        reports = call("GET", "/api/site-checks")
        if not reports:
            print("no report was saved", flush=True)
            return 2
        report = call("GET", f"/api/site-checks/{reports[0]['id']}")
    finally:
        try:
            call("DELETE", f"/api/profiles/{profile_id}")
        except Exception:
            pass

    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    env = report.get("environment") or {}
    lines = [
        "# Windows 检测成绩单（GitHub Actions windows-latest）",
        "",
        f"- 总评：**{report.get('overall')}**",
        f"- 画像：{env.get('profile_name')} / 内核 {env.get('kernel_version')} / "
        f"宿主 {env.get('host_os')}（{env.get('host_os_version')}）",
        f"- 出口：{env.get('proxy_type')} {env.get('exit_ip') or ''} "
        f"{env.get('exit_country') or ''}",
        "- 注意：CI 是机房 IP 且没有真实 GPU，IP 信誉类和 WebGL 类结果要打折看；"
        "这两项以真机验收为准。",
        "",
        "| 检测站 | 结果 | 判据 | 摘要 |",
        "| --- | --- | --- | --- |",
    ]
    for result in report.get("results", []):
        summary = str(result.get("summary") or "").replace("|", "/")
        lines.append(
            f"| {result.get('name')} | {result.get('status')} | "
            f"{result.get('criteria')} | {summary} |")
        for detail in result.get("details") or []:
            lines.append(f"|  |  |  | {str(detail).replace('|', '/')} |")
    (OUT / "SCORECARD.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
