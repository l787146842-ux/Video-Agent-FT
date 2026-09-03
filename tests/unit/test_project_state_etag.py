"""评审返修批回归：Critical-1 ETag 跨项目串台 + Warn PUT 整板 422。

Critical-1（routes/project.py）：
- _state_etag 改 project_id + board_version 双因子弱校验子（W/"{pid}-{bv}"），
  修复「仅 board_version 派生」的非单射——每项目独立账本、新建/分叉都从 0 起算，
  跨项目相同 bv 会让浏览器 304 命中另一项目缓存体（串台）；
- get_project_state 补 Cache-Control: private, no-cache（私有缓存 + 每次回源校验）；
- _etag_matches 改 RFC9110 弱比较（剥 W/ 前缀比 opaque-tag）+ 引号感知逗号列表
  解析 + 列表内 `*` 匹配。

Warn PUT（routes/project.py）：
- ProjectStateUpdate 五列表改 List[Dict] 收料 + 路由层 _coerce_elements 逐元素
  model_validate：单个退化元素（老落盘数据缺 id/text 等必填字段）不再拖垮整板
  → 整板 422；非法元素丢弃 + record_degradation("project_state.element_rejected")
  计数（可观测非静默）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager
from src.video_agent.web.routes.project import (
    _etag_matches,
    _opaque_tag,
    _parse_if_none_match,
    _state_etag,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def client(svc):
    from src.video_agent.web.routes import project as project_routes
    from src.video_agent.web.app import video_agent_error_handler
    from src.video_agent.exceptions import VideoAgentError
    app = FastAPI()
    app.include_router(project_routes.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _reload_from_disk(tmp_path) -> StateManager:
    """强制从磁盘重载（新实例走 _load），验证真实持久化往返而非内存态。"""
    StateManager.reset_instance()
    reloaded = StateManager(str(tmp_path))
    StateManager._instance = reloaded
    return reloaded


# ===================== Critical-1：ETag 双因子（单元） =====================

def test_state_etag_double_factor_injective():
    """双因子单射：相同 bv 不同 project_id → 不同 ETag（修复非单射串台根因）。"""
    assert _state_etag({"project_id": "p1", "board_version": 3}) == 'W/"p1-3"'
    assert _state_etag({"project_id": "p2", "board_version": 3}) == 'W/"p2-3"'
    # 关键：bv 同为 0（新建项目都从 0 起算），project_id 不同 → ETag 必须不同
    assert _state_etag({"project_id": "p1", "board_version": 0}) != \
        _state_etag({"project_id": "p2", "board_version": 0})
    # 缺 project_id 退化为空前缀（不抛异常）
    assert _state_etag({"board_version": 5}) == 'W/"-5"'


def test_opaque_tag_strips_weak_prefix():
    """RFC9110 弱比较只比 opaque-tag：剥 W/ 前缀（大小写不敏感）。"""
    assert _opaque_tag('W/"p1-3"') == '"p1-3"'
    assert _opaque_tag('w/"p1-3"') == '"p1-3"'
    assert _opaque_tag('"p1-3"') == '"p1-3"'
    assert _opaque_tag("") == ""


def test_parse_if_none_match_quote_aware_comma():
    """逗号列表解析：引号内逗号不作分隔（opaque-tag 可含逗号）。"""
    assert _parse_if_none_match('W/"a,b", W/"c"') == ['W/"a,b"', 'W/"c"']
    assert _parse_if_none_match('W/"x"') == ['W/"x"']
    assert _parse_if_none_match("*") == ["*"]
    assert _parse_if_none_match("") == []


def test_etag_matches_rfc9110_weak_and_list_and_star():
    """弱比较 + 多候选列表 + 列表内 `*` 匹配。"""
    # 弱比较：剥 W/ 前缀比 opaque-tag（强/弱混合，opaque-tag 相同即命中）
    assert _etag_matches('W/"p1-3"', 'W/"p1-3"') is True
    assert _etag_matches('"p1-3"', 'W/"p1-3"') is True
    assert _etag_matches('W/"p1-3"', 'W/"p1-4"') is False
    # 跨项目：opaque-tag 不同（串台根因）→ 不匹配
    assert _etag_matches('W/"p1-0"', 'W/"p2-0"') is False
    # 多候选列表：任一命中即匹配
    assert _etag_matches('W/"p1-1", W/"p1-3"', 'W/"p1-3"') is True
    # 引号内逗号不被误拆：候选 W/"a,b" 整体比对
    assert _etag_matches('W/"a,b", W/"c"', 'W/"a,b"') is True
    # 列表内 `*` 匹配任意现有表示
    assert _etag_matches('W/"p1-1", *', 'W/"p1-9"') is True
    assert _etag_matches("*", 'W/"anything"') is True
    # 空 If-None-Match 不匹配
    assert _etag_matches("", 'W/"p1-3"') is False


# ===================== Critical-1：ETag 跨项目串台（HTTP 集成） =====================

def test_etag_cross_project_no_false_304(client, svc):
    """核心回归：两项目 bv 相同（新建都从 0 起算）但 body 不同，
    带项目甲旧 ETag 请求项目乙必须 200（非 304）——否则浏览器回吐甲缓存体（串台）。"""
    # 项目甲：新建 → bv=0
    ra = client.post("/api/project/new", json={"name": "项目甲"})
    assert ra.status_code == 200
    pid_a = ra.json()["project_id"]
    ga = client.get("/api/project/state")
    assert ga.status_code == 200
    etag_a = ga.headers["ETag"]
    assert etag_a == f'W/"{pid_a}-0"'
    # 私有缓存 + no-cache（杜绝共享缓存留存/跨用户回吐）
    assert ga.headers["Cache-Control"] == "private, no-cache"

    # 项目乙：新建（active 切到乙）→ bv 同为 0，但 project_id 不同
    rb = client.post("/api/project/new", json={"name": "项目乙"})
    assert rb.status_code == 200
    pid_b = rb.json()["project_id"]
    assert pid_b != pid_a

    # 带甲的旧 ETag 请求乙：bv 相同但双因子 ETag 不同 → 必须 200（非 304）
    gb = client.get("/api/project/state", headers={"If-None-Match": etag_a})
    assert gb.status_code == 200, "跨项目相同 bv 被 304 命中（ETag 串台回归）"
    assert gb.headers["ETag"] == f'W/"{pid_b}-0"'
    assert gb.headers["Cache-Control"] == "private, no-cache"
    body_b = gb.json()
    # 回吐的必须是项目乙本体（非甲缓存体）
    assert body_b["project_id"] == pid_b
    assert body_b["project_name"] == "项目乙"


def test_etag_same_project_304_still_works(client, svc):
    """同项目未变（bv 不变）带自身 ETag → 304：双因子未破坏正常条件请求。"""
    g1 = client.get("/api/project/state")
    assert g1.status_code == 200
    etag = g1.headers["ETag"]
    g2 = client.get("/api/project/state", headers={"If-None-Match": etag})
    assert g2.status_code == 304
    assert g2.headers["ETag"] == etag
    assert g2.headers["Cache-Control"] == "private, no-cache"


def test_etag_invalidated_after_board_change(client, svc):
    """状态变更（bv 递增）后旧 ETag 失效 → 200（弱校验子仅实质变更失效）。"""
    g1 = client.get("/api/project/state")
    etag_old = g1.headers["ETag"]
    # 整板保存触发 bv 递增
    r = client.put("/api/project/state", json={"keyElements": [{"id": "ke-1"}]})
    assert r.status_code == 200
    g2 = client.get("/api/project/state", headers={"If-None-Match": etag_old})
    assert g2.status_code == 200
    assert g2.headers["ETag"] != etag_old


# ===================== Warn PUT：退化元素不整板 422 =====================

@pytest.mark.allow_degradation
def test_put_degraded_elements_not_whole_board_422(client, svc, tmp_path):
    """老落盘数据回放 PUT：单个退化元素（缺 id）不得整板 422；
    合法元素照常落盘，非法元素被丢弃 + record_degradation 计数（可观测非静默）。"""
    from src.video_agent.utils import live_metrics

    payload = {
        "keyElements": [
            {"id": "ke-ok", "title": "合法组"},      # 合法
            {"title": "退化组无 id"},                 # 非法：缺 group_id(alias id)
        ],
        "shots": [
            {"id": "sh-ok"},                          # 合法
            {"roughDesc": "退化分镜无 id"},           # 非法
        ],
        "audioItems": [
            {"id": "au-ok"},                          # 合法
            {"prompt": "退化音频无 id"},              # 非法
        ],
        "assets": [
            {"id": "as-ok", "name": "合法素材"},      # 合法
            {"name": "退化素材无 id"},                # 非法：缺 asset_id(alias id)
        ],
    }
    resp = client.put("/api/project/state", json=payload)
    # 关键回归：整板不再 422（强类型化时 4 个退化元素会拖垮整次保存）
    assert resp.status_code == 200, f"退化元素导致整板 {resp.status_code}（应软丢弃）"
    assert resp.json()["ok"] is True

    # 合法元素落盘、非法元素被丢弃（重载验证真实持久化）
    snap = _reload_from_disk(tmp_path).get_full_snapshot()
    assert snap["keyElements"] == [{"id": "ke-ok", "title": "合法组"}]
    assert snap["shots"] == [{"id": "sh-ok"}]
    assert snap["audioItems"] == [{"id": "au-ok"}]
    assert snap["assets"] == [{"id": "as-ok", "name": "合法素材"}]

    # 4 个非法元素各触发一次 record_degradation（可观测非静默）
    hits = live_metrics.get_degradations()
    rejected = [h for h in hits if h["point"] == "project_state.element_rejected"]
    assert rejected and rejected[0]["count"] == 4, \
        f"退化元素未计数或计数不符: {hits}"


@pytest.mark.allow_degradation
def test_put_degraded_chat_message_missing_text_dropped(client, svc):
    """chatMessages 退化元素（老落盘缺 text）被丢弃，合法消息保留。"""
    from src.video_agent.utils import live_metrics

    payload = {"chatMessages": [
        {"sender": "user", "text": "合法消息"},   # 合法
        {"sender": "agent"},                       # 非法：缺 content(alias text)
    ]}
    resp = client.put("/api/project/state", json=payload)
    assert resp.status_code == 200
    # 合法消息落盘（state_dict 直接验证；chatMessages 不经重载——多对话不变式重绑）
    assert svc.state_dict["chatMessages"] == [{"sender": "user", "text": "合法消息"}]
    hits = live_metrics.get_degradations()
    assert any(h["point"] == "project_state.element_rejected" and h["count"] == 1
               for h in hits), f"退化消息未计数: {hits}"


def test_put_all_valid_elements_no_degradation(client, svc, tmp_path):
    """全合法元素：零退化计数（软校验不误伤正常保存），往返零丢字段。"""
    payload = {
        "keyElements": [{"id": "ke-1", "title": "组", "badgeLabel": "已确认"}],
        "shots": [{"id": "sh-1", "title": "分镜"}],
    }
    resp = client.put("/api/project/state", json=payload)
    assert resp.status_code == 200
    snap = _reload_from_disk(tmp_path).get_full_snapshot()
    # extra="allow" 透传未建模额外字段（badgeLabel）
    assert snap["keyElements"] == [{"id": "ke-1", "title": "组", "badgeLabel": "已确认"}]
    assert snap["shots"] == [{"id": "sh-1", "title": "分镜"}]
