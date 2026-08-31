# -*- coding: utf-8 -*-
"""F1 裁决 2026-08-31：装饰器式工具注册（签名即 schema）。

新注册样板：普通函数经 @tool 装饰直接生成 BaseTool 实例——函数签名转
入参 schema（参数名+类型注解 → pydantic 模型；带默认值 = 可选参数），
注册仍经 ToolManager.register 同一闸口（risk 必填校验不放宽）。
存量类式工具不强制迁移（两样板并存，治理轴单一 = risk）。

用法：
    from src.video_agent.tools.decorated import tool

    @tool(name="demo_echo", description="回声示例", risk="low")
    def echo(text: str, times: int = 1) -> ToolResult:
        return ToolResult(success=True, data={"echo": text * times})

    ToolManager.register(echo)
"""
import inspect
from typing import Any, Callable, Dict, Type, get_type_hints

from pydantic import BaseModel, create_model

from .base import BaseTool, ToolResult


def build_input_schema_from_signature(fn: Callable) -> Type[BaseModel]:
    """签名即 schema：函数签名 → 入参 pydantic 模型。

    无默认值参数 = 必填，带默认值 = 可选；类型注解透传（无注解回落 str）；
    返回值注解不进 schema；self/cls 跳过。"""
    hints = get_type_hints(fn)
    fields: Dict[str, Any] = {}
    for pname, param in inspect.signature(fn).parameters.items():
        if pname in ("self", "cls"):
            continue
        ptype = hints.get(pname, str)
        if param.default is inspect.Parameter.empty:
            fields[pname] = (ptype, ...)
        else:
            fields[pname] = (ptype, param.default)
    return create_model(f"{fn.__name__}_Input", **fields)


def tool(*, name: str, description: str, risk: str,
         detail_tier: str = "", costly: bool = False):
    """工具注册装饰器（F1）：把普通同步/异步函数包装成 BaseTool 实例。

    参数即类属性声明（name/description/risk 必填；detail_tier/costly 可选）；
    返回装饰后的实例，调用方经 ToolManager.register 注册（deny-by-default
    校验链与原样板同口径）。"""
    def deco(fn: Callable) -> BaseTool:
        schema = build_input_schema_from_signature(fn)

        async def _aexecute(self, params: BaseModel) -> ToolResult:
            result = fn(**params.model_dump())
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, data={"result": result})

        cls = type(
            f"{name.title().replace('_', '')}Tool",
            (BaseTool,),
            {
                "name": name,
                "description": description,
                "risk": risk,
                "detail_tier": detail_tier,
                "costly": costly,
                "get_input_schema": staticmethod(lambda: schema),
                "aexecute": _aexecute,
            },
        )
        return cls()
    return deco
