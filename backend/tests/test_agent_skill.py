"""The Skill that ships in skills/cloakbrowser-manager must agree with the Manager's tools."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from backend import agent_tools

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "cloakbrowser-manager"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_skill_reference", ROOT / "scripts" / "gen_skill_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_reference_is_not_stale():
    expected = _generator().render()
    actual = (SKILL_DIR / "references" / "tool-reference.md").read_text(encoding="utf-8")
    assert actual == expected, "run: python scripts/gen_skill_reference.py"


def test_skill_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"---\nname: (\S+)\ndescription: \"(.+)\"\n---\n", text)
    assert match, "SKILL.md needs name + description frontmatter"
    assert match.group(1) == "cloakbrowser-manager" == SKILL_DIR.name
    assert len(match.group(2)) > 80


def test_skill_only_mentions_real_tools():
    """Every `tool_name(` or backticked snake_case tool in the skill must exist."""
    names = set(agent_tools.TOOLS)
    known_non_tools = {"proxy_id", "profile_id", "group_name", "launch_mode", "total_pages", "request_id", "read_only", "mode_read_only", "next_step"}
    for path in [SKILL_DIR / "SKILL.md", *(SKILL_DIR / "references").glob("*.md")]:
        if path.name == "tool-reference.md":
            continue
        text = path.read_text(encoding="utf-8")
        for token in set(re.findall(r"`([a-z]+(?:_[a-z]+)+)(?:\(|`)", text)):
            if token in known_non_tools or token in names:
                continue
            # reasons (profile_leased, seat_busy...) are not tools either
            if token in agent_tools.NEXT_STEPS:
                continue
            raise AssertionError(f"{path.name} mentions unknown tool-like name `{token}`")


def test_skill_covers_the_tool_choices_it_promises():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for tool in (
        "list_profiles", "create_profile", "update_profile", "rotate_proxy_ip", "regenerate_fingerprint",
        "launch_profile", "stop_all_profiles", "list_running", "create_group", "move_profiles",
        "restore_profile", "run_site_check", "open_browser", "account_prepare",
    ):
        assert tool in agent_tools.TOOLS and tool in text, tool
