"""7777 事故回归：后续轮次未携带 Skill 名时，按项目 usedSkills 兜底绑定执行器。

事故现场：项目 7777 上传 Skill 后自动注册成功，但用户后续输入
「继续拆分分镜」等消息未携带 skill_name/skill_slug，后端查注册表时
用空名 → 「当前 Skill「未指定」未注册 storyboard_* 执行器」→
模型退化为手动建组，流程偏离 Skill，最终空转转圈。

修复：单一实现 `registry.fallback_skill_from_state`（P1 单一事实源），
chat_service / planner / agent_loop 统一回退 usedSkills 末位。
"""

import pytest

from src.video_agent.skill_runtime import registry


def test_fallback_skill_from_state_last_used():
    assert registry.fallback_skill_from_state({"usedSkills": ["剧本生视频", "AI-短剧一站式生成"]}) == "AI-短剧一站式生成"
    assert registry.fallback_skill_from_state({"usedSkills": []}) == ""
    assert registry.fallback_skill_from_state({}) == ""
    assert registry.fallback_skill_from_state(None) == ""


def test_chat_resolver_falls_back_to_used_skills():
    from src.video_agent.web.chat_service import _resolve_skill_name_for_injection

    state = {"usedSkills": ["AI-短剧一站式生成"]}
    assert _resolve_skill_name_for_injection("", "", state) == "AI-短剧一站式生成"
    assert _resolve_skill_name_for_injection("", "", {}) == ""


def test_chat_resolver_request_skill_wins():
    from src.video_agent.web.chat_service import _resolve_skill_name_for_injection

    state = {"usedSkills": ["旧 Skill"]}
    assert _resolve_skill_name_for_injection("新选中 Skill", "", state) == "新选中 Skill"


def test_fallback_skill_executors_resolvable():
    """兜底 Skill（项目最近使用）必须能解析出执行器章节，否则回退后仍会「未注册」。"""
    entry = registry.resolve_entry("AI-短剧一站式生成")
    assert entry is not None
    assert registry.tool_available("AI-短剧一站式生成", "storyboard_shots") is True
    assert registry.tool_available("AI-短剧一站式生成", "write_media_prompt") is True


@pytest.mark.asyncio
async def test_agent_loop_falls_back_to_used_skills(tmp_path, monkeypatch):
    """agent_loop 用 usedSkills 末位解析当前 Skill（唯一口径；
    原 executor.skill_name 恒空字段已随 2026-09-03 兼容层根除批删除）
    （7777；audit-0819b：探针改钉 fallback_skill_from_state 调用，
    原 _wizard_active 探针随文本块路径退役）。"""
    from src.video_agent.core import agent_loop as al_mod
    from src.video_agent.core.agent_loop import run_agent_loop
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core.action_executor import StateOperationExecutor

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["usedSkills"] = ["AI-短剧一站式生成"]
    ex = StateOperationExecutor(svc, gate_enabled=True)

    seen = {}
    orig_fallback = al_mod.fallback_skill_from_state

    def spy_fallback(state):
        seen["called"] = True
        return orig_fallback(state)

    monkeypatch.setattr(al_mod, "fallback_skill_from_state", spy_fallback)

    async def llm(system_prompt, messages, stream_hook=None):
        return ("请确认", "stop", 0, 0.0,
                {"confirmation": "确认", "confirmation_options": []})

    result = await run_agent_loop(
        "继续", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )
    assert seen.get("called") is True
    assert result.confirmation == "确认"
