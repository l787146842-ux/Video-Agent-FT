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
from tests.fakes import FakeCanvasSession


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
    async def test_no_canvas_connection_raises(self, backend):
        """L2：无浏览器连接时直接报错（不再有 HTTP sidecar 可连）"""
        backend._session_override = FakeCanvasSession(connected=False, has_canvas=False)
        backend._session_override.call_tool = AsyncMock(  # type: ignore[method-assign]
            side_effect=AdapterError("当前没有已连接画布")
        )
        with pytest.raises(AdapterError, match="没有已连接画布"):
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
        """L2：会话等待浏览器回执超时 → AdapterError（不再有 HTTP 读超时）"""
        backend._session_override = FakeCanvasSession(
            lambda name, payload: AdapterError("画布操作超时")
        )
        with pytest.raises(AdapterError, match="超时"):
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

    def test_video_maps_to_video_with_abs_content(self):
        ic = _to_infinite_node({
            "id": "v1", "type": "video", "title": "成片",
            "url": "/workspace/assets/final.mp4", "x": 10, "y": 20,
        })
        assert ic["nodeType"] == "video"
        assert ic["metadata"]["content"].startswith("http")
        assert ic["metadata"]["content"].endswith("/workspace/assets/final.mp4")
        assert ic["position"] == {"x": 10.0, "y": 20.0}

    def test_unknown_type_rejected(self):
        with pytest.raises(AdapterError, match="不支持的节点类型"):
            _to_infinite_node({"id": "x1", "type": "unsupported"})

    def test_image_without_url_rejected(self):
        with pytest.raises(AdapterError, match="缺少 url"):
            _to_infinite_node({"id": "s2", "type": "smart-image", "images": []})

    def test_video_without_url_rejected(self):
        with pytest.raises(AdapterError, match="缺少 url"):
            _to_infinite_node({"id": "v2", "type": "video"})


class TestAddVideoNode:
    @pytest.mark.asyncio
    async def test_places_below_existing_nodes(self, backend):
        backend.get_canvas = AsyncMock(return_value=STATE)
        backend._get_state = AsyncMock(return_value=STATE)
        captured = []

        async def fake_apply(ops):
            captured.extend(ops)
            return []

        backend._apply_ops = fake_apply
        res = await backend.add_video_node(
            "p1", url="/workspace/assets/final.mp4", name="成片")
        assert res["canvas_id"] == "p1" and res["node_id"]
        op = captured[0]
        assert op["type"] == "add_node"
        assert op["nodeType"] == "video"
        assert op["metadata"]["content"].endswith("/workspace/assets/final.mp4")
        assert op["position"]["y"] == -2000 + 260  # 现有节点最下方之外

    @pytest.mark.asyncio
    async def test_explicit_position_used_as_is(self, backend):
        backend.get_canvas = AsyncMock(return_value=STATE)
        captured = []

        async def fake_apply(ops):
            captured.extend(ops)
            return []

        backend._apply_ops = fake_apply
        await backend.add_video_node(
            "p1", url="/workspace/assets/f.mp4", position=(12.0, 34.0))
        op = captured[0]
        assert op["position"] == {"x": 12.0, "y": 34.0}


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
        backend._session_override = FakeCanvasSession(has_canvas=True)
        assert await backend.is_online() is True

    @pytest.mark.asyncio
    async def test_service_online_but_canvas_closed(self, backend):
        """会话在但画布页未上报快照 → is_online False（health() 仍可区分）"""
        backend._session_override = FakeCanvasSession(has_canvas=False)
        assert await backend.is_online() is False
        h = await backend.health()
        assert h["ok"] is True
        assert h["hasCanvas"] is False

    @pytest.mark.asyncio
    async def test_offline(self, backend):
        backend._session_override = FakeCanvasSession(connected=False, has_canvas=False)
        assert await backend.is_online() is False


class TestIsSiteReachable:
    """画布“能否嵌入加载”口径：只探站点本体，不看画布页是否已连 agent"""

    @staticmethod
    def _patch_site_client(monkeypatch, handler):
        """把站点探测用的 httpx.AsyncClient 换成 MockTransport（其余参数原样透传）"""
        orig = httpx.AsyncClient
        monkeypatch.setattr(
            icb.httpx, "AsyncClient",
            lambda **kw: orig(transport=httpx.MockTransport(handler), **kw),
        )

    @staticmethod
    def _set_site_url(value: str):
        """临时设置画布站点地址（frozen dataclass 须走 object.__setattr__）。"""
        original = icb.settings.infinite_canvas_url
        object.__setattr__(icb.settings, "infinite_canvas_url", value)
        return original

    @pytest.mark.asyncio
    async def test_any_http_response_means_reachable(self, backend, monkeypatch):
        """站点返回 404 也说明服务在跑（只判可达，不判内容）"""
        self._patch_site_client(monkeypatch, lambda req: httpx.Response(404))
        original = self._set_site_url("http://localhost:3000")
        try:
            assert await backend.is_site_reachable() is True
        finally:
            self._set_site_url(original)

    @pytest.mark.asyncio
    async def test_connect_error_unreachable(self, backend, monkeypatch):
        def _refused(req):
            raise httpx.ConnectError("connection refused")

        self._patch_site_client(monkeypatch, _refused)
        original = self._set_site_url("http://localhost:3000")
        try:
            assert await backend.is_site_reachable() is False
        finally:
            self._set_site_url(original)

    @pytest.mark.asyncio
    async def test_blank_site_url_unreachable(self, backend):
        orig = icb.settings.infinite_canvas_url
        object.__setattr__(icb.settings, "infinite_canvas_url", "")
        try:
            assert await backend.is_site_reachable() is False
        finally:
            object.__setattr__(icb.settings, "infinite_canvas_url", orig)


class TestOnlineCached:
    """planner 工具裁剪口径（L2 后为内存事实，无 TTL/网络）：
    None = 从未有画布页连过（保持现状、不裁剪）；True/False = 当前会话可用性。
    """

    def test_none_before_first_connection(self, backend):
        backend._session_override = FakeCanvasSession(connected=False, has_canvas=False)
        assert backend.online_cached() is None

    def test_true_when_canvas_connected(self, backend):
        backend._session_override = FakeCanvasSession(has_canvas=True)
        assert backend.online_cached() is True

    def test_false_when_connected_but_no_snapshot(self, backend):
        backend._session_override = FakeCanvasSession(connected=True, has_canvas=False)
        assert backend.online_cached() is False


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
    async def test_noop_after_l2(self, backend):
        """L2：画布产物与后端同仓同版本发布，外部漂移不存在。"""
        assert await backend.check_version_drift() is None
        info = await backend.get_app_info()
        assert info["protocolVersion"] == icb.PROTOCOL_VERSION


class TestGroupNodes:
    """打组/解散组：对端工具转发与本地前置校验"""

    @pytest.mark.asyncio
    async def test_group_forwards_ids(self, backend):
        backend.get_canvas = AsyncMock(return_value=STATE)
        backend._call_tool = AsyncMock(return_value={"ok": True})
        result = await backend.group_nodes("p1", node_ids=["n1", "n2", "n3"])
        backend._call_tool.assert_awaited_once_with(
            "canvas_group_nodes", {"ids": ["n1", "n2", "n3"]})
        assert result == {"canvas_id": "p1", "grouped": 3}

    @pytest.mark.asyncio
    async def test_group_rejects_less_than_two(self, backend):
        """画布无空分组：不足 2 个节点在本地就拒，不打扰对端"""
        backend.get_canvas = AsyncMock(return_value=STATE)
        with pytest.raises(AdapterError, match="至少需要 2 个节点"):
            await backend.group_nodes("p1", node_ids=["n1"])

    @pytest.mark.asyncio
    async def test_ungroup_forwards_ids(self, backend):
        backend.get_canvas = AsyncMock(return_value=STATE)
        backend._call_tool = AsyncMock(return_value={"ok": True})
        result = await backend.ungroup_nodes("p1", node_ids=["g1"])
        backend._call_tool.assert_awaited_once_with(
            "canvas_ungroup_nodes", {"ids": ["g1"]})
        assert result == {"canvas_id": "p1", "ungrouped": 1}

    @pytest.mark.asyncio
    async def test_ungroup_rejects_empty(self, backend):
        backend.get_canvas = AsyncMock(return_value=STATE)
        with pytest.raises(AdapterError, match="至少 1 个节点"):
            await backend.ungroup_nodes("p1", node_ids=[])


class TestContainerRefit:
    """大类容器：按成员包围盒重算组位置/宽高（2026-11-11）。"""

    @staticmethod
    def _state(group_pos):
        return {
            "projectId": "p1", "title": "测试画布",
            "nodes": [
                {"id": "g1", "type": "group", "title": "关键元素",
                 "position": dict(group_pos), "width": 360, "height": 220,
                 "metadata": {"container": True}},
                {"id": "n1", "type": "text", "title": "说明",
                 "position": {"x": 100, "y": 100}, "width": 320, "height": 120,
                 "metadata": {"groupId": "g1"}},
                {"id": "n2", "type": "image", "title": "图",
                 "position": {"x": 500, "y": 100}, "width": 340, "height": 240,
                 "metadata": {"groupId": "g1"}},
            ],
            "connections": [], "selectedNodeIds": [],
            "viewport": {"x": 0, "y": 0, "k": 1},
        }

    @pytest.mark.asyncio
    async def test_moves_frame_and_restores_members(self, backend):
        state = self._state({"x": 0, "y": 0})
        applied = []

        async def fake_call(name, payload=None):
            if name == "canvas_get_state":
                return state
            applied.append((name, payload))
            return {"ok": True}

        backend._call_tool = fake_call
        out = await backend.refit_container("p1", "g1")
        # bbox: x 100..840 / y 100..340 → x=76, y=48, w=788, h=316
        assert out == {"canvas_id": "p1", "group_id": "g1",
                       "x": 76.0, "y": 48.0, "width": 788.0, "height": 316.0,
                       "members": 2}
        ops = applied[-1][1]["ops"]
        assert ops[0]["id"] == "g1"
        assert ops[0]["patch"]["position"] == {"x": 76.0, "y": 48.0}
        assert ops[0]["patch"]["width"] == 788.0
        restored = {op["id"]: op["patch"]["position"] for op in ops[1:]}
        assert restored == {"n1": {"x": 100.0, "y": 100.0},
                            "n2": {"x": 500.0, "y": 100.0}}

    @pytest.mark.asyncio
    async def test_size_only_when_anchor_unchanged(self, backend):
        state = self._state({"x": 76, "y": 48})
        applied = []

        async def fake_call(name, payload=None):
            if name == "canvas_get_state":
                return state
            applied.append((name, payload))
            return {"ok": True}

        backend._call_tool = fake_call
        out = await backend.refit_container("p1", "g1")
        assert out["width"] == 788.0 and out["height"] == 316.0
        ops = applied[-1][1]["ops"]
        assert len(ops) == 1, "位置未变时不得产生成员补偿 op"
        assert "position" not in ops[0]["patch"]

    @pytest.mark.asyncio
    async def test_no_members_is_noop(self, backend):
        state = {"projectId": "p1", "nodes": [
            {"id": "g1", "type": "group", "title": "空容器",
             "position": {"x": 0, "y": 0}, "width": 360, "height": 220,
             "metadata": {"container": True}},
        ], "connections": []}
        backend._call_tool = AsyncMock(return_value=state)
        assert await backend.refit_container("p1", "g1") is None
        # get_canvas + refit 各读一次快照；不产生任何写 op
        assert backend._call_tool.await_count == 2
        assert all(call.args[0] == "canvas_get_state"
                   for call in backend._call_tool.await_args_list)


class TestGroupNodeTranslation:
    def test_group_node_and_membership_metadata(self):
        group = _to_infinite_node({
            "id": "g1", "type": "group", "title": "关键元素",
            "x": 100, "y": 100, "width": 360, "height": 220, "container": True,
        })
        assert group["nodeType"] == "group"
        assert group["width"] == 360 and group["height"] == 220
        assert group["metadata"]["container"] is True

        member = _to_infinite_node({
            "id": "n1", "type": "text", "title": "说明",
            "x": 124, "y": 152, "content": "本区说明", "group_id": "g1",
        })
        assert member["metadata"]["groupId"] == "g1"


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
