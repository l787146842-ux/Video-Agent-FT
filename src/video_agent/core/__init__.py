"""core 包入口：惰性导出（PEP 562），避免循环导入。

多步循环已下沉至 core.agent_loop（P1-1）；
StudioActionExecutor 因依赖 web 层生成管线仍留在 web.action_executor，
属已登记的层级例外（见 ARCHITECTURE_RULES.md Rule2 注记）。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import VideoAgent
    from .planner import Planner

__all__ = ["Planner", "VideoAgent"]


def __getattr__(name: str):
    if name == "Planner":
        from .planner import Planner
        return Planner
    if name == "VideoAgent":
        from .agent import VideoAgent
        return VideoAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
