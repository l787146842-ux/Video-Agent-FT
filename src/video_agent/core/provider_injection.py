"""Provider 注入统一分派器（I-3 声明驱动，2026-09-03 裁决）。

修复根因：原 core/fc_tool_runner.py 的 execute() 内对 image_generate（single/batch
双分支）与 generate_video 按工具名字面量写 if/elif 特例注入 provider，违背项目
policy-as-data 范式且让本已很大的调度器继续膨胀。

正向设计：
- 工具在 tools/base.py 声明 provider_kind（与 risk/costly/detail_tier 同轴的注册期
  属性，注册期校验见 ToolManager.register）；
- 「补哪些 provider 入参、single/batch 等内部形态如何分流」实现为工具自身的
  apply_provider_defaults（工具内部形态下沉到工具，调度器不感知）；
- 本模块是调度器与工具声明之间唯一的 provider 注入分派面：按工具名解析其
  provider_kind 声明 → 命中则调工具的 apply_provider_defaults 原地补齐入参。
  调度器不再出现任何具体工具名字面量（消除 if/elif 特例）。

provider_kind 从工具**类声明**解析（经 BaseTool 子类发现，不依赖运行时注册表），
对 ToolManager.reset() 与 stub 管理器免疫；新增 provider 工具只需声明 provider_kind
+ 实现 apply_provider_defaults，本模块零改动自动纳管（单一事实源 = 工具类声明）。
"""
from typing import Any, Dict, Optional, Type

# 导入 tools 包会执行 tools/__init__（其导入并注册 document_tools/generate_video
# 等全部工具模块），故本模块导入完成时所有 BaseTool 子类均已定义、可被 _discover()
# 的子类发现纳管。此处用**顶层**显式导入固化该依赖（不用方法内 lazy import——
# 宪法第六章禁令 + check_func_imports 门禁），防未来若把下行 base 导入改为
# TYPE_CHECKING 等形态时静默丢失子类发现完整性。core→tools 非 web 方向，
# 不违层间导入闸（check_layer_imports 只禁 core/tools→web）。
import src.video_agent.tools  # noqa: F401  确保全部工具子类已定义（provider 发现完整）
from src.video_agent.tools.base import BaseTool, ProviderInjectionContext  # noqa: F401

# name → 声明了 provider_kind 的工具类（首次解析后缓存；类声明不可变，缓存恒有效）
_PROVIDER_TOOLS: Optional[Dict[str, Type[BaseTool]]] = None


def _discover() -> Dict[str, Type[BaseTool]]:
    """经 BaseTool 子类发现声明了 provider_kind 的工具类（name → class）。

    全部工具子类在本模块导入时即已加载（见顶部 tools 包导入说明），此处直接
    递归遍历 BaseTool.__subclasses__()；类声明不可变，发现结果缓存后恒有效，
    对 ToolManager.reset() 与 stub 管理器免疫。
    """
    out: Dict[str, Type[BaseTool]] = {}
    seen: set = set()
    stack: list = [BaseTool]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            stack.append(sub)
            kind = str(getattr(sub, "provider_kind", "") or "").strip()
            name = str(getattr(sub, "name", "") or "").strip()
            if kind and name:
                out[name] = sub
    return out


def _provider_tools() -> Dict[str, Type[BaseTool]]:
    global _PROVIDER_TOOLS
    if _PROVIDER_TOOLS is None:
        _PROVIDER_TOOLS = _discover()
    return _PROVIDER_TOOLS


def is_provider_tool(name: str) -> bool:
    """该工具是否为声明了 provider_kind 的生成类工具（生图/生视频）。

    供批末对账客观账本（生成成败记录）等按声明判定，替代「认工具名字面量」；
    与注入分派同源（工具类声明），对 stub 管理器/注册表 reset 免疫。
    """
    return name in _provider_tools()


def inject(name: str, args: Dict[str, Any], ctx: ProviderInjectionContext) -> None:
    """按工具声明补齐 provider 入参（原地修改 args）；未声明 provider_kind 者 no-op。"""
    cls = _provider_tools().get(name)
    if cls is None:
        return
    cls().apply_provider_defaults(args, ctx)
