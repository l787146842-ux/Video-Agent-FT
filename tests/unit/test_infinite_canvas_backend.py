"""
InfiniteCanvasBackend 单元测试 — 协议层打桩（mock _call_tool/_get_json），
与 test_canvas_drop 的打桩点同构（阶段 1 只保证适配层自身可测）。
"""
import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

import src.video_agent.adapters.infinite_canvas_backend as icb
from src.video_agent.adapters.infinite_canvas_backend import (
    APPLY_OPS_BATCH_SIZE,
    InfiniteCanvasBackend,
    _resolve_drop_point,
    _to_infinite_node,
    get_infinite_canvas_backend,
    reset_infinite_canvas_backend,
)
from src.video_agent.exceptions import AdapterError


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_infinite_canvas_backend()
    yield
    reset_infinite_canvas_backend()


@pytest.fixture
def backend():
    return InfiniteCanvasBackend(base_url="http://test-agent:17371", token="t", timeout=5)


STATE = {
    "projectId": "p1",
    "title": "测试画布",
    "nodes": [
        {"id": "image-1", "type": "image", "title": "图1", "position": {"x": -2000, "y": -2000},
         "width": 320, "height": 320, "metadata": {"content": "http://x/a.png"}},
    ],
    "connections": [],
    "selectedNodeIds": [],
    "viewport": {"x": 0, "y": 0, "k": 1},
}


class TestListCanvases:
    @pytest.mark.asyncio
    async def test_success(self, backend):
        backend._call_tool = AsyncMock(return_value={
            "total": 1, "page": 1, "pageSize": 100,
            "items": [{"id": "p1", "title": "画布1", "nodeCount": 2, "connectionCount": 0}],
        })
        result = await backend.list_canvases()
        backend._call_tool.assert_awaited_once_with("canvas_list_projects", {"page": 1, "pageSize": 100})
        assert len(result) == 1 and result[0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_connect_error(self, backend):
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(AdapterError, match="无法连接 canvas-agent"):
                await backend.list_canvases()

    @pytest.mark.asyncio
    async def test_tool_error_maps_adapter_error(self, backend):
        """{ok:false} 包装错误 → AdapterError 携带对端文案"""
        backend._call_tool = AsyncMock(side_effect=AdapterError(
            "infinite-canvas 工具 canvas_list_projects 失败: 当前没有已连接网页"))
        with pytest.raises(AdapterError, match="没有已连接网页"):
            await backend.list_canvases()


class TestGetCanvas:
    @pytest.mark.asyncio
    async def test_success(self, backend):
        backend._call_tool = AsyncMock(return_value=STATE)
        result = await backend.get_canvas("p1")
        assert result["projectId"] == "p1"
        assert len(result["nodes"]) == 1

    @pytest.mark.asyncio
    async def test_ttl_cache_hit(self, backend):
        backend._call_tool = AsyncMock(return_value=STATE)
        await backend.get_canvas("p1")
        await backend.get_canvas("p1")
        assert backend._call_tool.await_count == 1  # TTL 内命中缓存

    @pytest.mark.asyncio
    async def test_mismatch_navigates_then_rereads(self, backend):
        """当前连接页不是目标画布：先 site_navigate 再重读，命中后返回"""
        calls = []
        opened = {"v": False}

        async def fake_call(name, tool_input=None):
            calls.append((name, tool_input))
            if name == "site_navigate":
                opened["v"] = True
                return {"ok": True}
            if opened["v"]:
                return {**STATE, "projectId": "other-project"}
            return STATE

        backend._call_tool = fake_call
        result = await backend.get_canvas("other-project")
        assert result["projectId"] == "other-project"
        assert ("site_navigate", {"path": "/canvas/other-project"}) in calls

    @pytest.mark.asyncio
    async def test_timeout_raises_adapter_error(self, backend):
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            with pytest.raises(AdapterError, match="响应超时"):
                await backend.get_canvas("p1")


class TestSaveCanvasBatching:
    """写路径：全量 → 增量 ops，分片 20/批 串行提交，单批失败单批重试"""

    def _targets(self, count):
        return [{
            "id": f"image-n{i}", "type": "image", "title": f"图{i}",
            "x": i * 10, "y": 0,
            "images": [{"url": f"http://x/{i}.png", "name": f"{i}.png", "kind": "image"}],
        } for i in range(count)]

    @pytest.mark.asyncio
    async def test_batches_of_20_serial(self, backend):
        empty_state = {**STATE, "nodes": []}  # 空画布，避免删除 op 干扰分片断言
        backend._call_tool = AsyncMock(side_effect=lambda name, inp=None: empty_state if name == "canvas_get_state" else {"ok": True})
        await backend.save_canvas("p1", nodes=self._targets(45))
        apply_calls = [
            c for c in backend._call_tool.await_args_list if c.args and c.args[0] == "canvas_apply_ops"
        ]
        assert len(apply_calls) == 3  # 20 + 20 + 5
        sizes = [len(c.args[1]["ops"]) for c in apply_calls]
        assert sizes == [20, 20, 5]

    @pytest.mark.asyncio
    async def test_single_batch_retry_on_failure(self, backend):
        state_calls = {"n": 0}

        async def fake_call(name, tool_input=None):
            if name == "canvas_get_state":
                return STATE
            state_calls["n"] += 1
            if state_calls["n"] == 1:
                raise AdapterError("infinite-canvas 工具 canvas_apply_ops 失败: 画布操作超时", retryable=True)
            return {"ok": True}

        backend._call_tool = fake_call
        await backend.save_canvas("p1", nodes=self._targets(10))
        assert state_calls["n"] == 2  # 首批失败后重试一次成功

    @pytest.mark.asyncio
    async def test_delete_ops_for_removed_nodes(self, backend):
        captured = []

        async def fake_call(name, tool_input=None):
            if name == "canvas_get_state":
                return STATE
            captured.append(tool_input)
            return {"ok": True}

        backend._call_tool = fake_call
        await backend.save_canvas("p1", nodes=[])  # 清空 → 对既有节点产 delete_node
        all_ops = [op for batch in captured for op in batch["ops"]]
        deletes = [op for op in all_ops if op["type"] == "delete_node"]
        assert deletes and deletes[0]["ids"] == ["image-1"]


class TestToInfiniteNode:
    def test_smart_image_maps_to_image_with_abs_content(self):
        ic = _to_infinite_node({
            "id": "s1", "type": "smart-image", "x": 1, "y": 2,
            "images": [{"url": "/workspace/assets/a.png", "name": "a.png", "kind": "image"}],
        })
        assert ic["nodeType"] == "image"
        assert ic["metadata"]["content"].endswith("/workspace/assets/a.png")
        assert ic["metadata"]["content"].startswith("http")
        assert ic["position"] == {"x": 1.0, "y": 2.0}

    def test_smart_prompt_maps_to_text_content(self):
        ic = _to_infinite_node({"id": "t1", "type": "smart-prompt", "prompt": "赛博朋克"})
        assert ic["nodeType"] == "text"
        assert ic["metadata"]["content"] == "赛博朋克"

    def test_unknown_type_rejected(self):
        with pytest.raises(AdapterError, match="不支持的节点类型"):
            _to_infinite_node({"id": "v1", "type": "video"})

    def test_image_without_url_rejected(self):
        with pytest.raises(AdapterError, match="缺少 url"):
            _to_infinite_node({"id": "s2", "type": "smart-image", "images": []})


class TestUploadFiles:
    @pytest.mark.asyncio
    async def test_success(self, backend, tmp_path, monkeypatch):
        monkeypatch.setattr(icb, "ASSETS_DIR", tmp_path)
        added = []

        async def fake_call(name, tool_input=None):
            assert name == "assets_add"
            added.append(tool_input)
            return {"ok": True, "id": "asset-1", "kind": "image"}

        backend._call_tool = fake_call
        result = await backend.upload_files([("a.png", b"\x89PNG", "image/png")])
        assert len(result) == 1
        assert result[0]["url"].startswith("/workspace/assets/")
        assert result[0]["kind"] == "image"
        assert (tmp_path / result[0]["url"].rsplit("/", 1)[1]).read_bytes() == b"\x89PNG"
        # assets_add 以绝对 imageUrl 注册（画布站点需可回源拉取）
        assert added[0]["imageUrl"].startswith("http")

    @pytest.mark.asyncio
    async def test_empty_list(self, backend):
        assert await backend.upload_files([]) == []

    @pytest.mark.asyncio
    async def test_assets_add_failure_keeps_file(self, backend, tmp_path, monkeypatch):
        monkeypatch.setattr(icb, "ASSETS_DIR", tmp_path)
        backend._call_tool = AsyncMock(side_effect=AdapterError("注册失败"))
        result = await backend.upload_files([("a.png", b"x", "image/png")])
        assert len(result) == 1  # 注册失败不回滚，文件仍可用


class TestFindActiveCanvas:
    @pytest.mark.asyncio
    async def test_returns_connected_page_canvas(self, backend):
        backend._call_tool = AsyncMock(return_value=STATE)
        result = await backend.find_active_canvas()
        assert result["id"] == "p1"
        assert result["title"] == "测试画布"

    @pytest.mark.asyncio
    async def test_smart_alias_same_result(self, backend):
        backend._call_tool = AsyncMock(return_value=STATE)
        assert (await backend.find_active_smart_canvas())["id"] == "p1"

    @pytest.mark.asyncio
    async def test_no_canvas_returns_none(self, backend):
        backend._call_tool = AsyncMock(
            side_effect=AdapterError("infinite-canvas 工具 canvas_get_state 失败: 当前没有已连接画布"))
        assert await backend.find_active_canvas() is None


class TestResolveDropPoint:
    """落点换算：屏幕坐标 → 画布世界坐标（viewport 字段为 k）"""

    def _state(self, viewport):
        return {"viewport": viewport}

    def test_no_drop_point_returns_viewport_center(self):
        state = self._state({"x": 0, "y": 0, "k": 1})
        wx, wy = _resolve_drop_point(state, None, (1000, 600))
        assert (wx, wy) == (500, 300)

    def test_drop_point_with_shell_offset(self):
        state = self._state({"x": 0, "y": 0, "k": 1})
        wx, wy = _resolve_drop_point(state, (596, 216), (1000, 600))
        # 默认外壳偏移 (96, 16)：world = drop - offset
        assert (wx, wy) == (500, 200)

    def test_scale_and_viewport(self):
        state = self._state({"x": 100, "y": 50, "k": 2})
        wx, wy = _resolve_drop_point(state, (496, 266), (1000, 600))
        # world = (drop - offset - viewport) / k
        assert wx == (496 - 96 - 100) / 2
        assert wy == (266 - 16 - 50) / 2

    def test_out_of_view_clamped_into_visible_rect(self):
        state = self._state({"x": 0, "y": 0, "k": 1})
        wx, wy = _resolve_drop_point(state, (-5000, 99999), (1000, 600))
        assert 80 <= wx <= 920
        assert 80 <= wy <= 520

    def test_zero_scale_falls_back_to_one(self):
        state = self._state({"x": 0, "y": 0, "k": 0})
        wx, wy = _resolve_drop_point(state, None, (1000, 600))
        assert (wx, wy) == (500, 300)


class TestAddImageNode:
    @pytest.mark.asyncio
    async def test_appends_image_node_via_apply_ops(self, backend):
        applied = []

        async def fake_call(name, tool_input=None):
            if name == "canvas_get_state":
                return STATE
            applied.append(tool_input["ops"])
            return {"ok": True}

        backend._call_tool = fake_call
        result = await backend.add_image_node(
            "p1",
            image={"url": "/workspace/assets/x.png", "name": "x.png", "kind": "image"},
            view_size=(1000, 600),
        )
        assert result["canvas_id"] == "p1"
        assert result["canvas_title"] == "测试画布"
        ops = applied[0]
        assert len(ops) == 1
        op = ops[0]
        assert op["type"] == "add_node"
        assert op["nodeType"] == "image"
        # metadata.content 为绝对 URL（画布站点可回源拉取）
        assert op["metadata"]["content"].startswith("http")
        assert op["metadata"]["content"].endswith("/workspace/assets/x.png")
        # 默认放视口中心（1000x600 视口，节点半宽 160）
        assert op["position"]["x"] == 500 - 160
        assert op["position"]["y"] == 300 - 160


class TestIsOnline:
    @pytest.mark.asyncio
    async def test_online_requires_has_canvas(self, backend):
        backend._get_json = AsyncMock(return_value={"ok": True, "hasCanvas": True})
        assert await backend.is_online() is True

    @pytest.mark.asyncio
    async def test_service_online_but_canvas_closed(self, backend):
        """服务在线但画布页未开 → is_online False（health() 仍可区分）"""
        backend._get_json = AsyncMock(return_value={"ok": True, "hasCanvas": False})
        assert await backend.is_online() is False
        h = await backend.health()
        assert h["ok"] is True

    @pytest.mark.asyncio
    async def test_offline(self, backend):
        backend._get_json = AsyncMock(side_effect=AdapterError("无法连接"))
        assert await backend.is_online() is False


class TestHealthProbeTimeout:
    """/health 快探独立 2s 超时，不复用写路径 canvas_timeout"""

    @pytest.mark.asyncio
    async def test_health_uses_short_probe_timeout(self, backend):
        backend._get_json = AsyncMock(return_value={"ok": True, "hasCanvas": True})
        await backend.health()
        backend._get_json.assert_awaited_once_with("/health", timeout=icb._HEALTH_PROBE_TIMEOUT)
        assert icb._HEALTH_PROBE_TIMEOUT == 2.0

    @pytest.mark.asyncio
    async def test_get_json_passes_per_request_timeout(self, backend):
        """timeout 参数透传到 httpx 请求（本次请求独立超时）"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"ok": True})
        )
        client = httpx.AsyncClient(
            base_url="http://fixture.local", transport=transport, timeout=30
        )
        recorded = {}
        orig_get = client.get

        async def spy_get(path, **kwargs):
            recorded.update(kwargs)
            return await orig_get(path, **kwargs)

        client.get = spy_get  # type: ignore[method-assign]
        backend._client = client
        await backend._get_json("/health", timeout=2.0)
        assert recorded.get("timeout") == 2.0
        await client.aclose()


class TestStateCacheGeneration:
    """单调代际号：写失效后在途读的旧快照不得回填"""

    @pytest.mark.asyncio
    async def test_stale_backfill_discarded_after_invalidate(self, backend):
        async def fake_call(name, tool_input=None):
            # 模拟读在途期间写方已失效缓存（代际递增）
            backend.invalidate_state_cache()
            return STATE

        backend._call_tool = fake_call
        state = await backend._get_state(use_cache=False)
        assert state["projectId"] == "p1"  # 本次读结果仍正常返回
        assert backend._state_cache is None  # 旧快照弃回填，防覆盖新状态
        assert backend._state_cache_generation == 1

    @pytest.mark.asyncio
    async def test_backfill_kept_when_no_invalidate(self, backend):
        backend._call_tool = AsyncMock(return_value=STATE)
        await backend._get_state()
        assert backend._state_cache is not None  # 无写失效时正常回填


class TestImageTasks:
    @pytest.mark.asyncio
    async def test_submit_maps_canvas_generate_image(self, backend):
        backend._call_tool = AsyncMock(return_value={"ok": True, "config-abc": "config-abc"})
        result = await backend.submit_image_task({"prompt": "风景", "size": "1:1"})
        backend._call_tool.assert_awaited_once()
        name, tool_input = backend._call_tool.await_args.args
        assert name == "canvas_generate_image"
        assert tool_input["prompt"] == "风景"
        assert tool_input["size"] == "1:1"
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_image_task_matches_id(self, backend):
        backend._call_tool = AsyncMock(return_value={
            "total": 1,
            "tasks": [{"id": "config-abc", "status": "running", "source": "canvas"}],
        })
        result = await backend.get_image_task("config-abc")
        assert result["status"] == "running"
        assert result["task_id"] == "config-abc"

    @pytest.mark.asyncio
    async def test_get_image_task_unknown(self, backend):
        backend._call_tool = AsyncMock(return_value={"total": 0, "tasks": []})
        result = await backend.get_image_task("ghost")
        assert result["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_generate_image_online_early_stop_on_missing_task(self, backend, monkeypatch):
        """提交任务连续未出现在 generation_get_status → 早停抛错（不卡满 image_gen_timeout）"""
        monkeypatch.setattr(icb, "_IMAGE_POLL_INTERVAL", 0)
        polls = {"n": 0}

        async def fake_call(name, tool_input=None):
            if name == "canvas_generate_image":
                return {"config-x": "config-x"}
            polls["n"] += 1
            return {"tasks": []}  # 提交的任务始终不出现（任务丢失场景）

        backend._call_tool = fake_call
        with pytest.raises(AdapterError, match="早停降级"):
            await backend.generate_image_online({"prompt": "风景"})
        assert polls["n"] == icb._IMAGE_POLL_MAX_MISSES  # 5 轮即早停，非 180s 卡满

    @pytest.mark.asyncio
    async def test_generate_image_online_succeeds_after_late_appearance(self, backend, monkeypatch):
        """任务前几轮未出现、后出现并成功 → 正常返回（未误触早停）"""
        monkeypatch.setattr(icb, "_IMAGE_POLL_INTERVAL", 0)
        polls = {"n": 0}

        async def fake_call(name, tool_input=None):
            if name == "canvas_generate_image":
                return {"config-y": "config-y"}
            polls["n"] += 1
            if polls["n"] < 3:
                return {"tasks": []}
            return {"tasks": [{"id": "config-y", "status": "succeeded"}]}

        backend._call_tool = fake_call
        result = await backend.generate_image_online({"prompt": "风景"})
        assert result["status"] == "succeeded"
        assert polls["n"] == 3


class TestVersionDrift:
    @pytest.mark.asyncio
    async def test_records_and_detects_drift(self, backend, tmp_path, monkeypatch):
        record = tmp_path / "canvas_integration.json"
        monkeypatch.setattr(icb, "_CANVAS_VERSION_FILE", record)
        backend._get_json = AsyncMock(return_value={"ok": True, "protocolVersion": 6, "url": "u"})
        assert await backend.check_version_drift() is None
        saved = json.loads(record.read_text(encoding="utf-8"))
        assert saved["infinite_canvas"]["protocol_version"] == "6"
        # 模拟对端升级
        backend._get_json = AsyncMock(return_value={"ok": True, "protocolVersion": 7, "url": "u"})
        msg = await backend.check_version_drift()
        assert msg and "已更新" in msg

    @pytest.mark.asyncio
    async def test_preserves_existing_record_sections(self, backend, tmp_path, monkeypatch):
        record = tmp_path / "canvas_integration.json"
        record.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
        monkeypatch.setattr(icb, "_CANVAS_VERSION_FILE", record)
        backend._get_json = AsyncMock(return_value={"ok": True, "protocolVersion": 6, "url": "u"})
        await backend.check_version_drift()
        saved = json.loads(record.read_text(encoding="utf-8"))
        assert saved["version"] == "1.2.3"  # 既有段保留不覆盖
        assert saved["infinite_canvas"]["protocol_version"] == "6"

    @pytest.mark.asyncio
    async def test_offline_returns_none(self, backend):
        backend._get_json = AsyncMock(side_effect=AdapterError("无法连接"))
        assert await backend.check_version_drift() is None


class TestSingleton:
    def test_returns_same_instance(self):
        a1 = get_infinite_canvas_backend()
        a2 = get_infinite_canvas_backend()
        assert a1 is a2

    def test_reset_creates_new_instance(self):
        a1 = get_infinite_canvas_backend()
        reset_infinite_canvas_backend()
        a2 = get_infinite_canvas_backend()
        assert a1 is not a2

    def test_factory_dispatches_infinite_canvas(self):
        """工厂返回 infinite-canvas 单例（协议层接线）"""
        from src.video_agent.adapters.canvas_adapter import (
            get_canvas_adapter,
            reset_canvas_adapter,
        )
        reset_canvas_adapter()
        adapter = get_canvas_adapter()
        assert isinstance(adapter, InfiniteCanvasBackend)
        assert get_canvas_adapter() is adapter
        reset_canvas_adapter()
