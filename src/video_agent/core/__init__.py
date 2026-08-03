"""core 包入口：惰性导出（PEP 562），避免 web.agent_loop ↔ core.planner 循环导入。"""
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
