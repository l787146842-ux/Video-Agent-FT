# -*- coding: utf-8 -*-
"""F1 裁决 2026-08-31：装饰器式工具注册（签名即 schema）钉死测试。

钉死：① 签名转 schema（必填/可选/类型注解）；② 装饰产物可经
ToolManager.register 同一闸口注册（risk 必填校验不放宽）；
③ 生效审批档由 risk 单轴推导；④ 同步/异步函数均可包装，
非 ToolResult 返回值自动包装。
"""
import pytest

from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.decorated import build_input_schema_from_signature, tool
from src.video_agent.tools.manager import ToolManager


def _echo(text: str, times: int = 1) -> ToolResult:
    return ToolResult(success=True, data={"echo": text * times})


def test_signature_to_schema_required_and_optional():
    schema = build_input_schema_from_signature(_echo)
    fields = schema.model_fields
    assert "text" in fields and fields["text"].is_required()
    assert "times" in fields and not fields["times"].is_required()
    assert fields["times"].default == 1
    # 校验生效：缺必填参数拒收
    with pytest.raises(Exception):
        schema.model_validate({})
    ok = schema.model_validate({"text": "a"})
    assert ok.times == 1


def test_decorator_tool_registers_and_derives_tier():
    @tool(name="_probe_deco_low", description="只读示例", risk="low")
    def low_tool(query: str) -> ToolResult:
        return ToolResult(success=True, data={"q": query})

    ToolManager.register(low_tool)
    try:
        assert ToolManager.get_tool_risk("_probe_deco_low") == "low"
        # 单轴推导：low → 自动过
        assert ToolManager.get_tool_approval_tier("_probe_deco_low") == "none"
        assert low_tool.get_input_schema().model_fields["query"].is_required()
    finally:
        ToolManager._tools.pop("_probe_deco_low", None)
        ToolManager._schema_cache = None


def test_decorator_high_risk_derives_confirm():
    @tool(name="_probe_deco_high", description="破坏性示例", risk="high", costly=True)
    async def high_tool(target: str) -> ToolResult:
        return ToolResult(success=True, data={"target": target})

    ToolManager.register(high_tool)
    try:
        # 单轴推导：high → confirm（确认只挂高危）；花钱声明轴透传
        assert ToolManager.get_tool_approval_tier("_probe_deco_high") == "confirm"
        assert ToolManager.is_costly_tool("_probe_deco_high")
    finally:
        ToolManager._tools.pop("_probe_deco_high", None)
        ToolManager._schema_cache = None


def test_decorator_undeclared_risk_rejected():
    """未声明=最严：装饰器缺 risk 参数直接 TypeError（注册闸口不放宽）。"""
    with pytest.raises(TypeError):
        @tool(name="_probe_deco_norisk", description="缺 risk")  # type: ignore[call-arg]
        def bad(x: str):
            return ToolResult(success=True)


@pytest.mark.asyncio
async def test_decorator_executes_sync_and_plain_return():
    @tool(name="_probe_deco_exec", description="执行示例", risk="low")
    def plain(x: int = 2) -> int:
        return x * 21

    ToolManager.register(plain)
    try:
        res = await plain.aexecute(plain.get_input_schema()(x=2))
        assert res.success and res.data == {"result": 42}
        # 缺省参数生效
        res2 = await plain.aexecute(plain.get_input_schema()())
        assert res2.data == {"result": 42}
    finally:
        ToolManager._tools.pop("_probe_deco_exec", None)
        ToolManager._schema_cache = None
