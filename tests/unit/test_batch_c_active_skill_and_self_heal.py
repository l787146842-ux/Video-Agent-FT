"""批 C：Skill 激活归项目态 + 轮始自愈对账。

钉死：
- StateManager.set_active_skill 写 activeSkill 绑定（source 归一；空串=显式自由对话）；
- registry.fallback_skill_from_state 优先 activeSkill；未登记绑定的存量项目
  保持 usedSkills 末位旧口径（向后兼容）；
- /api/skills/active 端点激活（校验存在+留账）/摘除/未知 404；
- _record_active_skill 随消息激活同步写项目态绑定；
- 轮始 turn_seq 递增；自愈对账退役过期残留暂停卡
  （缺戳存量立即退役/超阈退役/阈值内保留/本轮正回应跳过）；
- 暂停登记两处戳发行轮次（供卡龄计算）。
"""
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.video_agent.core.planner import Planner, PlannerResponse
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.web.chat_consume import (
    PAUSE_STALE_AFTER_TURNS,
    advance_turn_seq,
    reconcile_stale_active_pause,
)
from src.video_agent.web.routes import plugins

_SKILL = "AI-短剧一站式生成"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class TestSetActiveSkill:
    def test_writes_binding(self, svc):
        svc.set_active_skill(_SKILL, "user")
        assert svc.state_dict["activeSkill"] == {"slug": _SKILL, "source": "user"}

    def test_source_normalized(self, svc):
        svc.set_active_skill("demo", "suggested")
        assert svc.state_dict["activeSkill"]["source"] == "suggested"
        svc.set_active_skill("demo", "任意其它值")
        assert svc.state_dict["activeSkill"]["source"] == "user"

    def test_empty_slug_is_explicit_free_chat(self, svc):
        svc.set_active_skill(_SKILL)
        svc.set_active_skill("")
        assert svc.state_dict["activeSkill"] == {"slug": "", "source": "user"}


class TestFallbackActiveSkillPriority:
    # M2（2026-08-30 裁决停用=真停用）：兜底候选须命中可加载性门户，
    # 探针改用真实注册条目（未注册候选不再被兜底返回）。
    def test_active_binding_wins_over_used(self):
        entries = registry.loadable_entries()
        a, b = entries[0].slug, entries[1].slug
        state = {"activeSkill": {"slug": a, "source": "user"}, "usedSkills": [b]}
        assert registry.fallback_skill_from_state(state) == a

    def test_empty_slug_explicit_free_chat_no_fallback(self):
        entries = registry.loadable_entries()
        state = {"activeSkill": {"slug": "", "source": "user"},
                 "usedSkills": [entries[0].slug]}
        assert registry.fallback_skill_from_state(state) == ""

    def test_legacy_project_keeps_last_used(self):
        entries = registry.loadable_entries()
        a, b = entries[0].slug, entries[1].slug
        assert registry.fallback_skill_from_state({"usedSkills": [a, b]}) == b
        assert registry.fallback_skill_from_state({}) == ""


class TestActiveSkillEndpoint:
    @pytest.fixture
    def client(self, svc):
        app = FastAPI()
        app.include_router(plugins.router, prefix="/api")

        @app.exception_handler(VideoAgentError)
        async def _vae_handler(request, exc):  # noqa: ARG001
            return JSONResponse(status_code=exc.status_code, content={"message": str(exc)})

        return TestClient(app)

    def test_activate_writes_project_state(self, client, svc):
        r = client.post("/api/skills/active", json={"slug": _SKILL, "source": "user"})
        assert r.status_code == 200
        assert svc.state_dict["activeSkill"] == {"slug": _SKILL, "source": "user"}
        assert _SKILL in (svc.state_dict.get("usedSkills") or [])

    def test_deactivate_returns_to_free_chat(self, client, svc):
        r = client.post("/api/skills/active", json={"slug": ""})
        assert r.status_code == 200
        assert svc.state_dict["activeSkill"] == {"slug": "", "source": "user"}

    def test_unknown_slug_rejected(self, client, svc):
        r = client.post("/api/skills/active", json={"slug": "不存在的技能"})
        assert r.status_code == 404
        assert "activeSkill" not in svc.state_dict


class TestRecordActiveSkillBinding:
    def test_message_activation_writes_binding(self, svc):
        from src.video_agent.web.chat_opening import _record_active_skill
        from src.video_agent.web.routes.agent import ChatRequest

        body = ChatRequest(message="hi", skill_slug=_SKILL)
        _record_active_skill(svc, body)
        assert svc.state_dict["activeSkill"] == {"slug": _SKILL, "source": "user"}
        assert _SKILL in (svc.state_dict.get("usedSkills") or [])

    def test_no_skill_fields_no_write(self, svc):
        from src.video_agent.web.chat_opening import _record_active_skill
        from src.video_agent.web.routes.agent import ChatRequest

        _record_active_skill(svc, ChatRequest(message="hi"))
        assert "activeSkill" not in svc.state_dict


class TestTurnSeqAndSelfHeal:
    def _seed_pause(self, svc, pause_id="pid", issued=None):
        inter = svc.state_dict.setdefault("interaction", {})
        ap = {"pause_id": pause_id, "message": "m", "options": []}
        if issued is not None:
            ap["issued_turn_seq"] = issued
        inter["active_pause"] = ap

    def test_advance_turn_seq(self, svc):
        assert advance_turn_seq(svc) == 1
        assert advance_turn_seq(svc) == 2
        assert svc.state_dict["turn_seq"] == 2

    def test_stampless_stock_residue_retired(self, svc):
        self._seed_pause(svc)
        assert reconcile_stale_active_pause(svc, None) is True
        assert "active_pause" not in (svc.state_dict.get("interaction") or {})

    def test_fresh_pause_kept(self, svc):
        svc.state_dict["turn_seq"] = 5
        self._seed_pause(svc, issued=5)
        assert reconcile_stale_active_pause(svc, None) is False
        assert (svc.state_dict.get("interaction") or {}).get("active_pause")

    def test_overdue_retired(self, svc):
        svc.state_dict["turn_seq"] = 5 + PAUSE_STALE_AFTER_TURNS
        self._seed_pause(svc, issued=5)
        assert reconcile_stale_active_pause(svc, None) is True
        assert "active_pause" not in (svc.state_dict.get("interaction") or {})

    def test_matching_response_skipped(self, svc):
        self._seed_pause(svc, pause_id="abc")
        assert reconcile_stale_active_pause(svc, {"pause_id": "abc"}) is False
        assert (svc.state_dict.get("interaction") or {}).get("active_pause")

    def test_no_active_pause_noop(self, svc):
        assert reconcile_stale_active_pause(svc, None) is False


class TestPauseIssueTurnStamp:
    def test_planner_issue_pause_stamps_turn_seq(self, svc):
        svc.state_dict["turn_seq"] = 7
        planner = Planner(state_manager=svc, llm_adapter=None)
        resp = PlannerResponse(text="t", confirmation="请确认")
        planner._issue_pause(resp)
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("issued_turn_seq") == 7

    @pytest.mark.asyncio
    async def test_fc_pause_stamps_turn_seq(self, svc):
        from src.video_agent.adapters.base_chat import ChatResponse
        from src.video_agent.core.fc_tool_runner import FCToolRunner
        from src.video_agent.tools.document_tools import register_document_tools
        from src.video_agent.tools.manager import ToolManager

        # 显式重注册：同 worker 其它用例的 ToolManager.reset() 可能清空全局注册表，
        # 本用例不依赖导入副作用（与 test_fc_tool_feedback 同口径）
        register_document_tools()
        svc.state_dict["turn_seq"] = 9
        runner = FCToolRunner(ToolManager)
        resp = ChatResponse(content="", finish_reason="tool_calls", tool_calls=[
            {"id": "wp1", "type": "function", "function": {
                "name": "workflow_pause",
                "arguments": '{"message": "请确认是否继续"}'}}])
        result = await runner.execute(resp)
        assert result.pause_id
        active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
        assert active.get("issued_turn_seq") == 9
