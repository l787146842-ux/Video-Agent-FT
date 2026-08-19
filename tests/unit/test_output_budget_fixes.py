"""输出预算截断修复回归（1111 项目事故）：
script_analyze 在 max_tokens=2048 上被推理模型思考占满额度，四次连续 finish=length 失败。
修复：模型输出上限查表 + 截断/空内容自动扩额重试一次 + 到顶仍截断抛明确错误。
audit-0819f C1：初始预算按任务定（下限 8192，消灭「先撞墙」白烧）。
"""
import pytest

from src.video_agent.config import settings
from src.video_agent.core.token_budget import output_limit_for_model
from src.video_agent.exceptions import GenerationError
from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.web import generation as gen_mod


# ---------- 输出上限查表 ----------

def test_output_limit_known_models():
    assert output_limit_for_model("deepseek-v4-flash") == 8_192
    assert output_limit_for_model("gemini-3.1-pro") == 32_768
    assert output_limit_for_model("Qwen/Qwen3-235B-A22B") == 8_192


def test_output_limit_unknown_model_falls_back():
    assert output_limit_for_model("some-unknown-model") == settings.llm_output_limit
    assert output_limit_for_model("") == settings.llm_output_limit


# ---------- 截断/空内容自动扩额重试 ----------

def _patch_chat(monkeypatch, responses, model="deepseek-v4-flash"):
    """按序返回 (content, finish) 或抛异常；记录每次调用的 max_tokens/timeout。"""
    calls = []

    async def fake(provider, model_, messages, *, max_tokens, timeout=120, **kwargs):
        calls.append({"max_tokens": max_tokens, "timeout": timeout})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake)
    # exec_spec 经 exec_common 模块属性调用，补丁必须打在 exec_common 上
    from src.video_agent.skill_runtime import exec_common as ec_mod
    monkeypatch.setattr(
        ec_mod, "_resolve_chat_provider", lambda p="", m="": ("custom", model)
    )
    monkeypatch.setattr(
        ex_mod, "_resolve_chat_provider", lambda p="", m="": ("custom", model)
    )
    return calls


@pytest.mark.asyncio
async def test_truncated_then_retry_with_double_budget(monkeypatch):
    # audit-0819f C1：gemini 上限 32768，初始预算下限 8192（不再 4096 先撞墙）
    calls = _patch_chat(monkeypatch, [
        ('{"summary": "半截', "length"),
        ('{"summary": "完整"}', "stop"),
    ], model="gemini-3.1-pro")
    data = await ex_mod._llm_json_call("s", "u", max_tokens=4096)
    assert data == {"summary": "完整"}
    assert [c["max_tokens"] for c in calls] == [8192, 16384]
    assert all(c["timeout"] == settings.llm_json_timeout for c in calls)


@pytest.mark.asyncio
async def test_empty_content_then_retry_with_double_budget(monkeypatch):
    calls = _patch_chat(monkeypatch, [
        GenerationError("LLM 返回了空内容"),
        ('{"summary": "完整"}', "stop"),
    ], model="gemini-3.1-pro")
    data = await ex_mod._llm_json_call("s", "u", max_tokens=4096)
    assert data == {"summary": "完整"}
    assert [c["max_tokens"] for c in calls] == [8192, 16384]


@pytest.mark.asyncio
async def test_still_truncated_at_ceiling_raises_clear_error(monkeypatch):
    calls = _patch_chat(monkeypatch, [
        ("", "length"),
        ('{"summary": "半截', "length"),
    ])
    with pytest.raises(RuntimeError, match="截断"):
        await ex_mod._llm_json_call("s", "u", max_tokens=4096)
    # deepseek 上限 8192：初始预算即已到顶（C1 下限=上限），一次即抛明确错误
    assert [c["max_tokens"] for c in calls] == [8192]


@pytest.mark.asyncio
async def test_budget_clamped_to_model_ceiling(monkeypatch):
    calls = _patch_chat(monkeypatch, [
        ('{"a": 1}', "stop"),
    ])
    data = await ex_mod._llm_json_call("s", "u", max_tokens=100_000)
    assert data == {"a": 1}
    # 初始预算被钳到 deepseek 输出上限，不允许发出超限请求
    assert calls[0]["max_tokens"] == 8_192
