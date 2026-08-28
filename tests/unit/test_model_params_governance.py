"""B7 回归：模型能力参数治理——注入优先级（草稿 > 全局设置）与 Skill 写死参数 lint。"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.tools.base import ToolResult


class _Recorder:
    """记录 image_generate（mode='single'）实际收到的参数（B7 优先级验证用）。"""

    def __init__(self):
        self.last_args = None

    async def invoke_tool(self, name, args):
        self.last_args = dict(args)
        return ToolResult(success=True, data={"image_urls": ["http://x/1.png"]})


def _fc_call(args: dict) -> ChatResponse:
    args = dict(args)
    args.setdefault("mode", "single")
    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "image_generate",
            "arguments": json.dumps(args, ensure_ascii=False)}},
    ])


def test_b7_draft_provider_wins_over_global_settings(monkeypatch):
    """B7 用户裁决：草稿自身（中间面板直接选择）优先于全局设置。"""
    import src.video_agent.core.provider_config as pc

    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    monkeypatch.setattr(pc, "spec_media_preference", lambda state, kind="image": ("provG", "mG"))
    recorder = _Recorder()
    runner = FCToolRunner(recorder)
    asyncio.run(runner.execute(
        _fc_call({"prompt": "一只猫", "adapter_provider": ""}),
        image_provider="provD",
    ))
    assert recorder.last_args["adapter_provider"] == "provD"  # 草稿选择优先


def test_b7_global_settings_fallback_when_no_draft(monkeypatch):
    """无草稿选择时回落全局设置。"""
    import src.video_agent.core.provider_config as pc

    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    monkeypatch.setattr(pc, "spec_media_preference", lambda state, kind="image": ("provG", "mG"))
    recorder = _Recorder()
    runner = FCToolRunner(recorder)
    asyncio.run(runner.execute(
        _fc_call({"prompt": "一只猫", "adapter_provider": ""}),
        image_provider="",
    ))
    assert recorder.last_args["adapter_provider"] == "provG"  # 全局设置兜底


def test_b7_skill_lint_flags_hardcoded_model_params():
    """Skill 写死模型参数 lint：提示已作废（全局设置为唯一权威源）。"""
    from src.video_agent.web.skill_docs import lint_skill_content

    content = (
        "# 演示\n> 调用规则：测试\n"
        "<write_media_prompt>\n以 Seedance 2.5 480p 为核心视频生成模型\n</write_media_prompt>\n"
    )
    result = lint_skill_content(content)
    assert any("已作废" in w and "全局设置" in w for w in result["warnings"])


def test_b7_skill_lint_silent_without_model_params():
    from src.video_agent.web.skill_docs import lint_skill_content

    content = "# 演示\n> 调用规则：测试\n<write_media_prompt>\n中文叙事式写法\n</write_media_prompt>\n"
    result = lint_skill_content(content)
    assert not any("已作废" in w for w in result["warnings"])
