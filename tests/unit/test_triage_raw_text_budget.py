"""audit-0819f 钉死回归（批 12 迁移）：闸预检只认用户原话。

1111 事故根治：附件预览里的剧本对白问号不得参与意图判定
（闸预检认 raw_user_text）。
（阶段 2 用例——执行器预算按任务定（exec_spec.initial_json_budget）与
截断重试可见（_llm_json_call 进度下发）——已随任务#36 B5 执行器一步
退役删除：被测对象属执行器内部机制，不复存在。）
"""
from pathlib import Path

import pytest

from src.video_agent.core import stage_probes as po
from src.video_agent.state.manager import StateManager

ROOT = Path(__file__).resolve().parent.parent.parent

_SKILL = "AI-短剧一站式生成"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    yield instance
    StateManager.reset_instance()


# ---------- 闸预检只认用户原话 ----------

@pytest.mark.asyncio
async def test_precheck_attachment_question_mark_not_counted(svc):
    """1111 现场：剧本预览含「？」。原话为豁免话术时，附件问号不得干扰判定。"""
    # 剧本缺失（不预置 uploadedDocs）；附件预览问号只存在于拼装消息，原话无问号
    out = await po.gate_precheck(svc, _SKILL, "waive_script")
    assert out is None
    assert (svc.state_dict.get("interaction") or {}).get("script_waived") is True


@pytest.mark.asyncio
async def test_precheck_raw_question_still_reminds(svc):
    """剧本缺失时，原话为提问（非豁免/回执话术）→ 原料闸提醒卡语义不 regress"""
    out = await po.gate_precheck(svc, _SKILL, "为什么还没好？")
    assert out is not None and out.kind == "script_pending"


def test_handle_message_precheck_wired_to_raw_text():
    """钉死：handle_message 闸预检取 context.raw_user_text（多模态拼装不得参与）"""
    src = (ROOT / "src/video_agent/core/planner.py").read_text(encoding="utf-8")
    assert "context.raw_user_text or user_message" in src
