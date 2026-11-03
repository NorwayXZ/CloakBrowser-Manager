"""Write skills/cloakbrowser-manager/references/tool-reference.md from the live tool registry.

The Skill's tool list must never drift from the Manager's, so it is generated:

    python scripts/gen_skill_reference.py          # rewrite the file
    python scripts/gen_skill_reference.py --check  # exit 1 if it is stale (CI / tests)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import agent_tools  # noqa: E402

TARGET = ROOT / "skills" / "cloakbrowser-manager" / "references" / "tool-reference.md"

LAYER_TITLES = {
    "read": ("只读工具", "`read-only` 档以上都能用"),
    "action": ("动作与管理工具", "需要 `full` 档（令牌范围 `control`）"),
    "browser": ("浏览器与页面工具", "需要 `automation` 档（令牌范围 `cdp`）；能读到页面里的 Cookie，只在需要时开"),
}


def _param_rows(schema: dict) -> list[str]:
    required = set(schema.get("required", []))
    rows = []
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type", "")
        if "enum" in spec:
            kind = " / ".join(str(v) for v in spec["enum"])
        elif kind == "array":
            kind = f"array<{(spec.get('items') or {}).get('type', 'any')}>"
        note = str(spec.get("description", "")).replace("|", "\\|").replace("\n", " ")
        default = f"（默认 {spec['default']}）" if "default" in spec else ""
        rows.append(f"| `{name}` | {kind} | {'是' if name in required else ''} | {note}{default} |")
    return rows


def render() -> str:
    lines = [
        "# 工具参考（自动生成，请勿手改）",
        "",
        "由 `python scripts/gen_skill_reference.py` 从 Manager 的工具注册表生成；`pytest` 会检查它没有过期。",
        "",
        f"共 {len(agent_tools.TOOLS)} 个工具。每个工具的“触发词”是用户常用说法，用来对上你该选哪个工具。",
        "",
    ]
    for layer, (title, gate) in LAYER_TITLES.items():
        tools = [t for t in agent_tools.TOOLS.values() if t.layer == layer]
        lines += [f"## {title}（{len(tools)}）", "", gate, ""]
        for tool in tools:
            lines += [f"### `{tool.name}`", "", tool.description, ""]
            english = agent_tools.TOOL_EN.get(tool.name)
            if english:
                lines += [f"*{english}*", ""]
            lines += [f"触发词：{agent_tools.TRIGGERS.get(tool.name, '')}", ""]
            rows = _param_rows(tool.input_schema)
            if rows:
                lines += ["| 参数 | 类型 | 必填 | 说明 |", "| --- | --- | --- | --- |", *rows, ""]
            else:
                lines += ["无参数。", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("tool-reference.md is stale: run python scripts/gen_skill_reference.py", file=sys.stderr)
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
