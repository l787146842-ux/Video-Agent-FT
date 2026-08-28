"""
画布后端分发入口（Rule4: 外部调用走 Adapter）。

唯一后端 = infinite-canvas（canvas-agent HTTP 协议），实现见
adapters/infinite_canvas_backend.py；端口定义见 adapters/canvas_port.py。
本模块只保留全局单例工厂与健康探测缓存的对外口径，
调用方（路由/工具/装配）一律经 get_canvas_adapter() 取后端。
"""
from typing import TYPE_CHECKING, Optional

from src.video_agent.adapters.infinite_canvas_backend import (
    get_infinite_canvas_backend,
    reset_infinite_canvas_backend,
)

if TYPE_CHECKING:
    from src.video_agent.adapters.canvas_port import CanvasBackend


# ---------- 模块级单例 ----------

_adapter_instance: Optional["CanvasBackend"] = None


def canvas_online_cached() -> Optional[bool]:
    """返回最近一次画布健康探测的缓存结果（不触发网络请求）。

    None = 尚未探测过（调用方应保持现状，不做裁剪）；
    True/False = 最近一次探测结果（可能已过 TTL，仅作尽力而为的提示）。
    """
    return get_infinite_canvas_backend().online_cached()


def get_canvas_adapter() -> "CanvasBackend":
    """获取全局画布后端单例（infinite-canvas 唯一实现）"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = get_infinite_canvas_backend()
    return _adapter_instance


def reset_canvas_adapter():
    """重置单例与健康检查缓存（测试用，避免测试间缓存串味）"""
    global _adapter_instance
    _adapter_instance = None
    reset_infinite_canvas_backend()
