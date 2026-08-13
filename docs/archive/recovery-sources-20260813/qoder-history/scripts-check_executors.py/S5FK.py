# -*- coding: utf-8 -*-
"""核查：每个已导入 Skill 实际注册了哪些执行器。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.skill_runtime import registry  # noqa: E402

registry.sync_all(force=True)
lines = []
for e in sorted(registry.list_entries(), key=lambda x: x.name):
    tools = e.available_tools
    missing = [t for t in registry.SKILL_EXECUTOR_TOOLS if t not in tools]
    lines.append(f"{e.name}: {len(tools)}/7 | 缺失: {missing or '无'}")
out = pathlib.Path(__file__).parent / "executor_check_report.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"written: {out}")
