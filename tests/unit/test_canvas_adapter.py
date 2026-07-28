"""
CanvasAdapter 单元测试 — mock httpx 响应。
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from src.video_agent.adapters.canvas_adapter import CanvasAdapter, get_canvas_adapter, reset_canvas_adapter
from src.video_agent.exceptions import AdapterError


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_canvas_adapter()
    yield
    reset_canvas_adapter()


@pytest.fixture
def adapter():
    return CanvasAdapter(base_url="http://test-canvas:8000", timeout=5)


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
        resp.text = str(json_data)
    return resp


class TestListCanvases:
    @pytest.mark.asyncio
    async def test_success(self, adapter):
        mock_resp = _mock_response({"canvases": [{"id": "c1", "title": "画布1"}]})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.list_canvases()
        assert len(result) == 1
        assert result[0]["id"] == "c1"

    @pytest.mark.asyncio
    async def test_connect_error(self, adapter):
        with patch(
            "httpx.AsyncClient.request",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(AdapterError, match="无法连接画布服务"):
                await adapter.list_canvases()


class TestGetCanvas:
    @pytest.mark.asyncio
    async def test_success(self, adapter):
        canvas_data = {"id": "c1", "nodes": [{"id": "n1", "type": "smart-image"}]}
        mock_resp = _mock_response({"canvas": canvas_data})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.get_canvas("c1")
        assert result["id"] == "c1"
        assert len(result["nodes"]) == 1


class TestSaveCanvas:
    @pytest.mark.asyncio
    async def test_success(self, adapter):
        mock_resp = _mock_response({"canvas": {"id": "c1", "updated_at": 123}})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.save_canvas("c1", nodes=[{"id": "n1"}], base_updated_at=100)
        assert result["updated_at"] == 123

    @pytest.mark.asyncio
    async def test_conflict_409(self, adapter):
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(AdapterError, match="画布写入冲突"):
                await adapter.save_canvas("c1", nodes=[])


class TestCreateCanvas:
    @pytest.mark.asyncio
    async def test_success(self, adapter):
        mock_resp = _mock_response({"canvas": {"id": "new1", "title": "测试画布"}})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.create_canvas(title="测试画布")
        assert result["id"] == "new1"


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_adapter_error(self, adapter):
        with patch(
            "httpx.AsyncClient.request",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            with pytest.raises(AdapterError, match="响应超时"):
                await adapter.list_canvases()


class TestSingleton:
    def test_get_canvas_adapter_returns_same_instance(self):
        a1 = get_canvas_adapter()
        a2 = get_canvas_adapter()
        assert a1 is a2

    def test_reset_creates_new_instance(self):
        a1 = get_canvas_adapter()
        reset_canvas_adapter()
        a2 = get_canvas_adapter()
        assert a1 is not a2
