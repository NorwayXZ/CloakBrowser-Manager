"""scripts/compare_check_reports.py: the old-vs-new detection report check used for release acceptance."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_check_reports.py"
spec = importlib.util.spec_from_file_location("compare_check_reports", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def report(statuses: dict[str, str], *, kernel="145.0.1", ip="192.0.2.55", extra: dict[str, dict] | None = None) -> dict:
    results = [
        {"site": site, "name": site.title(), "status": status, "summary": f"{site} is {status}", **(extra or {}).get(site, {})}
        for site, status in statuses.items()
    ]
    return {
        "id": "r", "overall": "pass",
        "environment": {"profile_name": "Etsy UK", "host_os": "macos", "kernel_version": kernel, "exit_ip": ip, "exit_country": "GB"},
        "results": results,
    }


def test_identical_verdicts_are_not_a_difference():
    result = tool.compare(report({"creepjs": "pass", "pixelscan": "pass"}), report({"creepjs": "pass", "pixelscan": "pass"}))
    assert result == {"differences": [], "warnings": [], "notes": []}


def test_a_changed_verdict_is_a_difference_and_says_which_way():
    result = tool.compare(report({"creepjs": "pass"}), report({"creepjs": "fail"}))
    assert len(result["differences"]) == 1 and "变差" in result["differences"][0]
    better = tool.compare(report({"creepjs": "fail"}), report({"creepjs": "pass"}))
    assert "变好" in better["differences"][0]


def test_a_site_only_one_report_has_is_a_difference():
    result = tool.compare(report({"creepjs": "pass"}), report({"creepjs": "pass", "pixelscan": "pass"}))
    assert result["differences"] == ["Pixelscan：只有新报告里有这一项"]


def test_a_verdict_that_depends_on_the_exit_ip_is_only_a_warning():
    note = {"fingerprint": {"ip_note": "受出口 IP 信誉影响"}}
    result = tool.compare(report({"fingerprint": "pass"}, extra=note), report({"fingerprint": "warn"}, extra=note))
    assert result["differences"] == []
    assert "出口 IP" in result["warnings"][0]


def test_a_kernel_update_is_a_note_and_a_different_exit_is_a_warning():
    result = tool.compare(report({"creepjs": "pass"}, kernel="145.0.1", ip="192.0.2.1"), report({"creepjs": "pass"}, kernel="146.0.2", ip="192.0.2.9"))
    assert result["differences"] == []
    assert any("出口 IP不同" in w for w in result["warnings"])
    assert any("145.0.1 → 146.0.2" in n for n in result["notes"])


def test_same_verdict_with_different_page_text_is_only_a_note():
    old, new = report({"creepjs": "pass"}), report({"creepjs": "pass"})
    new["results"][0]["summary"] = "different wording"
    result = tool.compare(old, new)
    assert result["differences"] == [] and len(result["notes"]) == 1


def test_loads_a_folder_a_report_file_and_an_exported_zip(tmp_path: Path):
    data = report({"creepjs": "pass"})
    folder = tmp_path / "20261024-100000-Etsy_UK"
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps(data), encoding="utf-8")
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("20261024-100000-Etsy_UK/report.json", json.dumps(data))
    assert tool.load_report(folder) == data
    assert tool.load_report(folder / "report.json") == data
    assert tool.load_report(archive) == data
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(ValueError):
        tool.load_report(empty)


def test_exit_status_follows_the_differences(tmp_path: Path, capsys):
    for name, status in (("old", "pass"), ("same", "pass"), ("worse", "fail")):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "report.json").write_text(json.dumps(report({"creepjs": status})), encoding="utf-8")
    assert tool.main(["x", str(tmp_path / "old"), str(tmp_path / "same")]) == 0
    assert "一致" in capsys.readouterr().out
    assert tool.main(["x", str(tmp_path / "old"), str(tmp_path / "worse")]) == 1
    assert tool.main(["x"]) == 2
