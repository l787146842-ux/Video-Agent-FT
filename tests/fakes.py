"""测试替身：画布会话假实现（L2 后适配层的唯一外部依赖）。"""
from typing import Any, Callable, Dict, List, Optional


class FakeCanvasSession:
    """记录 call_tool 调用并按 handler 返回；health/has_canvas 可独立设定。"""

    def __init__(
        self,
        handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        *,
        connected: bool = True,
        has_canvas: bool = True,
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._handler = handler
        self._connected = connected
        self._has_canvas = has_canvas

    async def call_tool(self, name: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        data = dict(payload or {})
        self.calls.append({"name": name, "input": data})
        if self._handler is None:
            return {}
        result = self._handler(name, data)
        if isinstance(result, Exception):
            raise result
        return result

    def health(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "protocolVersion": 6,
            "hasCanvas": self.has_canvas(),
            "clients": 1 if self._connected else 0,
            "codexBusy": False,
        }

    def has_canvas(self) -> bool:
        return self._connected and self._has_canvas

    def ever_connected(self) -> bool:
        return self._connected

    def set_offline(self) -> None:
        self._has_canvas = False
