"""五轮 S3：确定性按钮化回归（#3/#11/#13）。

- #3 suggested_actions：空响应/坏输出 → retry（max_steps 截断的 continue
  按钮随步数上限退役，2026-09-10；假停兜底的「继续」由轮末策略发射）；
- #11 豁免入口按钮化（C5：正则 NLU 语料快照随入口退役，行为钉死
  迁 test_prompt_gates 的 C5 段）；
- #13 scope 枚举显式化 + planner 消费逻辑引用常量。
"""
from pathlib import Path

from src.video_agent.core import prompt_gates

ROOT = Path(__file__).resolve().parents[2]


# ---------- #13 scope 枚举 ----------

def test_s3_override_scope_enum_values():
    assert prompt_gates.GATE_OVERRIDE_SCOPE_ALL == "all"
    assert prompt_gates.GATE_OVERRIDE_SCOPE_FLOW == "flow"


def test_s3_planner_consumes_scope_enum():
    """豁免消费逻辑必须引用显式枚举；
    批 7 拆分：实现体迁 planner_gate_session（planner 同名委托）"""
    src = (ROOT / "src/video_agent/core/planner_gate_session.py").read_text(encoding="utf-8")
    assert "prompt_gates.GATE_OVERRIDE_SCOPE_ALL" in src
    # 消费即留痕：record_gate 携带 scope
    assert "scope=str(gate_override_scope)" in src


# ---------- #3 suggested_actions 发射点 ----------

def test_s3_suggested_actions_emitted():
    loop_src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    # 空响应兜底与坏输出终止 → retry（两处）
    assert loop_src.count('{"kind": "retry", "label": "重试", "value": ""}') == 2
    # max_steps 截断的「继续完成」按钮随步数上限退役（2026-09-10）：
    # agent_loop 不再发射 continue 动作（假停兜底的「继续」在轮末策略发射）
    assert '{"kind": "continue"' not in loop_src
    # planner 透传进 done payload
    planner_src = (ROOT / "src/video_agent/core/planner.py").read_text(encoding="utf-8")
    assert '"suggested_actions": result.suggested_actions' in planner_src
