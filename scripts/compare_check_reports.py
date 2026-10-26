"""Compare two one-click detection reports: did the new build change what detectors see?

Run the one-click check (检测 › 检测报告) for the same environment with the old
release and with the new one, export both reports (zip) or point at their
folders, then:

    python scripts/compare_check_reports.py OLD NEW

OLD and NEW are a report folder (holding report.json), a report.json, or an
exported .zip. Sites are matched by id. A site whose verdict differs, or that
only one report has, is a difference and the exit status is 1. Verdicts that
the report itself marks as depending on the exit IP (an IP-reputation note) are
shown as a warning instead, because a different exit address can change them
without any change to the browser. The kernel version differing is reported but
is not a difference: it is what an update is supposed to change.

Reads reports only; it never starts a browser.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

STATUS_RANK = {"pass": 0, "warn": 1, "unknown": 2, "error": 3, "fail": 4}


def load_report(source: Path) -> dict:
    if source.is_dir():
        source = source / "report.json"
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            names = [n for n in archive.namelist() if n.rsplit("/", 1)[-1] == "report.json"]
            if not names:
                raise ValueError(f"{source}: no report.json inside")
            return json.loads(archive.read(names[0]).decode("utf-8"))
    return json.loads(source.read_text(encoding="utf-8"))


def compare(old: dict, new: dict) -> dict:
    """{"differences": [...], "warnings": [...], "notes": [...]} in plain sentences."""
    old_sites = {r["site"]: r for r in old.get("results", [])}
    new_sites = {r["site"]: r for r in new.get("results", [])}
    differences: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    for site in sorted(set(old_sites) | set(new_sites)):
        before, after = old_sites.get(site), new_sites.get(site)
        name = (after or before).get("name", site)
        if before is None or after is None:
            differences.append(f"{name}：只有{'新' if before is None else '旧'}报告里有这一项")
            continue
        if before["status"] == after["status"]:
            if before.get("summary") != after.get("summary"):
                notes.append(f"{name}：结论相同（{after['status']}），但页面文字不同：{before.get('summary')} → {after.get('summary')}")
            continue
        sentence = f"{name}：{before['status']} → {after['status']}（{before.get('summary')} → {after.get('summary')}）"
        if before.get("ip_note") or after.get("ip_note"):
            warnings.append(sentence + "；这一项受出口 IP 信誉影响，先确认两次的出口 IP 是否相同")
        else:
            worse = STATUS_RANK.get(after["status"], 0) > STATUS_RANK.get(before["status"], 0)
            differences.append(sentence + ("（变差）" if worse else "（变好）"))

    old_env, new_env = old.get("environment", {}), new.get("environment", {})
    for key, label in (("profile_name", "环境"), ("host_os", "系统"), ("exit_ip", "出口 IP"), ("exit_country", "出口地区")):
        if old_env.get(key) != new_env.get(key):
            warnings.append(f"{label}不同：{old_env.get(key)} → {new_env.get(key)}，两份报告不是在同一条件下做的")
    if old_env.get("kernel_version") != new_env.get("kernel_version"):
        notes.append(f"内核版本：{old_env.get('kernel_version')} → {new_env.get('kernel_version')}")
    return {"differences": differences, "warnings": warnings, "notes": notes}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    old, new = load_report(Path(argv[1])), load_report(Path(argv[2]))
    result = compare(old, new)
    print(f"旧：{old.get('id')}（{old.get('overall')}）    新：{new.get('id')}（{new.get('overall')}）")
    for title, key in (("差异", "differences"), ("需要留意", "warnings"), ("备注", "notes")):
        if result[key]:
            print(f"\n{title}：")
            for line in result[key]:
                print(f"  - {line}")
    if not any(result.values()):
        print("\n每一项的结论都一致。")
    elif not result["differences"]:
        print("\n没有结论上的差异。")
    return 1 if result["differences"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
