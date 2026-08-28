# -*- coding: utf-8 -*-
"""infinite-canvas canvas-agent 通道契约测试。

背景：InfiniteCanvasBackend 硬编码了 canvas-agent 的工具协议（/api/tools 请求体、
{ok, result} 响应包装、34 工具闭集、8 ops 闭集、协议版本 6、/health /config 结构）。
画布是快速迭代的第三方项目，协议漂移会让本项目静默产生坏数据。本测试用录制的
真实响应夹具（tests/fixtures/infinite_canvas/）守住契约：

- 协议版本：/config 与 /health 的 protocolVersion 必须等于代码钉住值（PROTOCOL_VERSION）；
- 工具白名单：项目使用的工具必须全部属于 schemas.ts 34 工具闭集；
- ops 闭集：canvas_apply_ops 的 op 类型集合与 canvas_schema.py 一致；
- adapter 读路径：用 httpx.MockTransport 重放夹具，验证解析逻辑。

夹具录制：连上画布页后通过 HTTP 调用录制（/health、/config、canvas_list_projects、
canvas_get_state、canvas_apply_ops(add/update/delete)、canvas_get_selection、
assets_list、assets_add）；tool_names.json 为对端只读契约文书
canvas-agent/src/canvas/schemas.ts 的 toolNames/canvasOpSchema 转录。
本测试不需要画布在线。
"""
import json
from pathlib import Path

import httpx
import pytest

from src.video_agent.adapters.canvas_schema import (
    INFINITE_CANVAS_OP_TYPES,
    INFINITE_CANVAS_USED_TOOLS,
)
from src.video_agent.adapters.infinite_canvas_backend import (
    PROTOCOL_VERSION,
    InfiniteCanvasBackend,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "infinite_canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def health() -> dict:
    return _load("health.json")


@pytest.fixture(scope="module")
def config() -> dict:
    return _load("config.json")


@pytest.fixture(scope="module")
def tool_spec() -> dict:
    return _load("tool_names.json")


@pytest.fixture(scope="module")
def canvas_state() -> dict:
    return _load("tools/canvas_get_state.json")["response"]["result"]


# ---------- (a) 协议版本钉住 ----------

class TestProtocolVersion:
    def test_config_protocol_version_matches_pinned(self, config):
        assert config.get("ok") is True
        assert config.get("protocolVersion") == PROTOCOL_VERSION

    def test_health_protocol_version_matches_pinned(self, health):
        assert health.get("ok") is True
        assert health.get("protocolVersion") == PROTOCOL_VERSION


# ---------- (b) 工具白名单属于 34 工具闭集 ----------

class TestToolWhitelist:
    def test_closed_set_size(self, tool_spec):
        assert len(set(tool_spec["toolNames"])) == 34, "schemas.ts toolNames 闭集应为 34 个"

    def test_used_tools_all_registered(self, tool_spec):
        registered = set(tool_spec["toolNames"])
        missing = set(INFINITE_CANVAS_USED_TOOLS) - registered
        assert not missing, f"项目使用的工具不在对端闭集中: {sorted(missing)}"


# ---------- (c) ops 闭集一致 ----------

class TestOpsClosedSet:
    def test_op_types_match_schema_module(self, tool_spec):
        assert set(tool_spec["opTypes"]) == set(INFINITE_CANVAS_OP_TYPES)

    def test_recorded_apply_ops_within_closed_set(self):
        for fx in FIXTURES.glob("tools/canvas_apply_ops*.json"):
            data = json.loads(fx.read_text(encoding="utf-8"))
            ops = data["request"]["input"]["ops"]
            assert ops, f"{fx.name} 夹具请求应至少含一个 op"
            for op in ops:
                assert op["type"] in INFINITE_CANVAS_OP_TYPES, (
                    f"{fx.name} 出现闭集外 op 类型: {op['type']}"
                )


# ---------- 夹具结构契约 ----------

class TestFixtureContract:
    def test_health_fields(self, health):
        for field in ("ok", "protocolVersion", "hasCanvas", "clients"):
            assert field in health, f"/health 缺少字段: {field}"
        assert isinstance(health["hasCanvas"], bool)
        assert isinstance(health["clients"], int)

    def test_config_fields(self, config):
        for field in ("ok", "protocolVersion", "url", "hasToken"):
            assert field in config, f"/config 缺少字段: {field}"

    def test_canvas_state_node_schema(self, canvas_state):
        # adapter 读路径依赖的节点字段（对端 compactNode 透出口径）
        nodes = canvas_state.get("nodes")
        assert isinstance(nodes, list)
        for n in nodes:
            for field in ("id", "type", "position", "width", "height"):
                assert field in n, f"画布节点缺少字段: {field}"
            assert isinstance(n["position"].get("x"), (int, float))
            assert isinstance(n["position"].get("y"), (int, float))

    def test_canvas_state_viewport_schema(self, canvas_state):
        viewport = canvas_state.get("viewport") or {}
        for key in ("x", "y", "k"):
            assert isinstance(viewport.get(key), (int, float)), f"viewport.{key} 应为数值"

    def test_list_projects_item_schema(self):
        result = _load("tools/canvas_list_projects.json")["response"]["result"]
        assert isinstance(result.get("total"), int)
        assert isinstance(result.get("items"), list)
        for item in result["items"]:
            for field in ("id", "title", "nodeCount", "connectionCount"):
                assert field in item, f"画布列表项缺少字段: {field}"

    def test_assets_list_schema(self):
        result = _load("tools/assets_list.json")["response"]["result"]
        assert isinstance(result.get("total"), int)
        assert isinstance(result.get("items"), list)

    def test_assets_add_schema(self):
        result = _load("tools/assets_add.json")["response"]["result"]
        assert result.get("ok") is True
        assert result.get("id")

    def test_get_selection_schema(self):
        result = _load("tools/canvas_get_selection.json")["response"]["result"]
        assert isinstance(result.get("nodes"), list)


# ---------- adapter 读路径（MockTransport 重放夹具） ----------

def _backend_with_fixtures() -> InfiniteCanvasBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json=_load("health.json"))
        if path == "/config":
            return httpx.Response(200, json=_load("config.json"))
        if path == "/api/tools":
            body = json.loads(request.content)
            name = body.get("name") or ""
            if name == "canvas_apply_ops":
                op_type = ((body.get("input") or {}).get("ops") or [{}])[0].get("type", "")
                fx_name = f"tools/canvas_apply_ops_{op_type}.json"
            else:
                fx_name = f"tools/{name}.json"
            return httpx.Response(200, json=_load(fx_name)["response"])
        return httpx.Response(404, json={"ok": False, "error": "not found"})

    backend = InfiniteCanvasBackend(base_url="http://fixture.local", token="t", timeout=5)
    backend.client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://fixture.local", transport=httpx.MockTransport(handler), timeout=5
    )
    return backend


class TestAdapterReadPaths:
    @pytest.mark.asyncio
    async def test_list_canvases_parsing(self):
        backend = _backend_with_fixtures()
        canvases = await backend.list_canvases()
        fx_items = _load("tools/canvas_list_projects.json")["response"]["result"]["items"]
        assert len(canvases) == len(fx_items)
        assert all("id" in c for c in canvases)

    @pytest.mark.asyncio
    async def test_get_canvas_returns_state(self):
        backend = _backend_with_fixtures()
        canvas = await backend.get_canvas("")
        assert "nodes" in canvas and "viewport" in canvas

    @pytest.mark.asyncio
    async def test_get_canvas_ttl_cache(self):
        """TTL 内重复读命中缓存（只发一次 canvas_get_state）"""
        calls = []
        backend = _backend_with_fixtures()
        raw_client = backend.client

        def counting_client():
            client = raw_client()
            original_post = client.post

            async def post(url, **kwargs):
                calls.append(url)
                return await original_post(url, **kwargs)

            client.post = post  # type: ignore[method-assign]
            return client

        backend.client = counting_client  # type: ignore[method-assign]
        await backend.get_canvas("")
        await backend.get_canvas("")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_get_selection_parsing(self):
        """canvas_get_selection 夹具重放：选中态解析为 {supported, nodes}"""
        backend = _backend_with_fixtures()
        sel = await backend.get_selection()
        fx_nodes = _load("tools/canvas_get_selection.json")["response"]["result"]["nodes"]
        assert sel["supported"] is True
        assert sel["nodes"] == fx_nodes

    @pytest.mark.asyncio
    async def test_is_online_matches_health_has_canvas(self):
        backend = _backend_with_fixtures()
        expected = _load("health.json")
        assert await backend.is_online() == bool(expected["ok"] and expected["hasCanvas"])

    @pytest.mark.asyncio
    async def test_get_app_info_maps_protocol_version(self):
        backend = _backend_with_fixtures()
        info = await backend.get_app_info()
        assert info["version"] == str(PROTOCOL_VERSION)
        assert info["protocolVersion"] == PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_check_version_drift_records(self, tmp_path, monkeypatch):
        import src.video_agent.adapters.infinite_canvas_backend as mod
        record = tmp_path / "canvas_integration.json"
        monkeypatch.setattr(mod, "_CANVAS_VERSION_FILE", record)
        backend = _backend_with_fixtures()
        assert await backend.check_version_drift() is None  # 首次无漂移
        saved = json.loads(record.read_text(encoding="utf-8"))
        assert saved["infinite_canvas"]["protocol_version"] == str(PROTOCOL_VERSION)
        # 记录改为旧版本 → 漂移告警
        saved["infinite_canvas"]["protocol_version"] = "0"
        record.write_text(json.dumps(saved), encoding="utf-8")
        msg = await backend.check_version_drift()
        assert msg and "已更新" in msg

    @pytest.mark.asyncio
    async def test_save_canvas_applies_ops_replay(self):
        """save_canvas 走 canvas_apply_ops 增量通道（重放 add/update/delete 夹具）"""
        backend = _backend_with_fixtures()
        state = _load("tools/canvas_get_state.json")["response"]["result"]
        existing = [n for n in state.get("nodes", [])][:2]
        # 保留一个既有节点（产生 update）+ 一个新节点（产生 add），其余被删（产生 delete）
        nodes = []
        if existing:
            kept = existing[0]
            nodes.append({
                "id": kept["id"],
                "type": "image" if kept.get("type") == "image" else "text",
                "title": kept.get("title") or "t",
                "x": 10, "y": 10,
                "images": [{"url": "http://fixture.local/x.png"}] if kept.get("type") == "image" else None,
                "content": "hi",
            })
        nodes.append({
            "id": "image-new-node", "type": "image", "title": "新图",
            "x": 200, "y": 200, "images": [{"url": "http://fixture.local/y.png"}],
        })
        result = await backend.save_canvas(state.get("projectId") or "", nodes=nodes)
        assert isinstance(result, dict)
