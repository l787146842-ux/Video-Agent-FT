# -*- coding: utf-8 -*-
"""
7777 二轮复盘修复回归测试。

覆盖（4-4 双轨退役后，ADR-0001）：
1. 降级开关新语义：同模型跨厂商（模型不换），仅列同名模型的供应商
   入链，空列表不入链；覆盖聊天/生图/出视频三类候选链与重试判定。
（普通 JSON 不受动作块误伤的解析侧反向断言已随任务#27 文本轨残留
退役删除：被测对象 web/action_parser.py 整文件退役。）
"""
import pytest

from src.video_agent.exceptions import AdapterError


# TestConfirmationToolKeyAlias（_extract_confirmation 别名归一）已随
# S16 删除退役（audit-0819d）：暂停确认唯一经 workflow_pause FC 工具上抛。


# TestLegitimateJsonUntouched（普通 json 围栏不被误认为动作的解析侧断言）
# 已随任务#27 文本轨残留退役删除：被测对象（action_parser.parse_actions_from_reply）
# 整模块退役，动作通道唯一 = FC 工具调用（ADR-0001）。


# ---------- 降级新语义：同模型跨厂商 ----------

_PROVIDERS = [
    {"id": "main", "name": "主厂商", "enabled": True,
     "chat_models": ["gemini-3.1-pro"], "image_models": ["nano-banana"],
     "video_models": ["seedance-2.5"]},
    {"id": "alt1", "name": "备用一", "enabled": True,
     "chat_models": ["gemini-3.1-pro", "gemini-3.6-flash"],
     "image_models": ["nano-banana"], "video_models": ["seedance-2.5"]},
    {"id": "alt2", "name": "空列表厂商", "enabled": True,
     "chat_models": [], "image_models": [], "video_models": []},
    {"id": "alt3", "name": "禁用厂商", "enabled": False,
     "chat_models": ["gemini-3.1-pro"], "image_models": [], "video_models": []},
    {"id": "alt4", "name": "只备同名聊天", "enabled": True,
     "chat_models": ["gemini-3.1-pro"], "image_models": ["other-img"],
     "video_models": ["other-vid"]},
]


def _patch_providers(monkeypatch, module):
    async def _load():
        return list(_PROVIDERS)

    async def _not_mock(pid, model=None):
        return False

    monkeypatch.setattr(module, "load_merged_providers_async", _load)
    monkeypatch.setattr(module, "is_mock_provider_async", _not_mock)


class TestSameModelCrossProviderCandidates:
    """批 C 裁决（2026-08-20）：聊天链路退役 fallback，单一候选 = 用户所选；
    生图/生视频 fallback 属独立机制（generation.py），不在裁决范围。
    聊天链路单一候选的源码锁源在 test_transport_wiring_four.test_b0_f4
    （P2d：本处重复钉死删除）。"""

    @pytest.mark.asyncio
    async def test_image_candidates_by_image_models(self, monkeypatch):
        from src.video_agent.web import generation

        _patch_providers(monkeypatch, generation)
        cands = await generation._gen_fallback_candidates("main", "nano-banana", "image")
        pids = [p for p, _ in cands]
        assert pids == ["main", "alt1"]  # alt4 的 image_models 无同名模型

    @pytest.mark.asyncio
    async def test_video_candidates_by_video_models(self, monkeypatch):
        from src.video_agent.web import generation

        _patch_providers(monkeypatch, generation)
        cands = await generation._gen_fallback_candidates("main", "seedance-2.5", "video")
        pids = [p for p, _ in cands]
        assert pids == ["main", "alt1"]


class TestGenRetryableJudgement:
    """只有失败才降级：可重试性判定"""

    def test_adapter_retryable_flag_respected(self):
        from src.video_agent.web.generation import _is_retryable_gen_error

        assert _is_retryable_gen_error(AdapterError("上游 502", retryable=True)) is True
        assert _is_retryable_gen_error(AdapterError("鉴权失败", retryable=False)) is False

    def test_cause_chain_flag_respected(self):
        from src.video_agent.web.generation import _is_retryable_gen_error

        try:
            try:
                raise AdapterError("超时", retryable=True)
            except AdapterError as inner:
                raise RuntimeError("生成失败") from inner
        except RuntimeError as outer:
            assert _is_retryable_gen_error(outer) is True

    def test_moderation_not_retryable(self):
        from src.video_agent.web.generation import _is_retryable_gen_error

        assert _is_retryable_gen_error(RuntimeError("内容审核未通过")) is False
        assert _is_retryable_gen_error(RuntimeError("供应商未配置")) is False

    def test_plain_failure_retryable(self):
        from src.video_agent.web.generation import _is_retryable_gen_error

        assert _is_retryable_gen_error(RuntimeError("任务排队超时后失败")) is True


# ---------- 规格制作参数：分辨率/分镜最大时长 ----------

_SPEC_TEXT = (
    "- 视频标题：太阳系逐渐二维化\n"
    "- 画幅：16:9\n"
    "- 图片分辨率：2K\n"
    "- 视频分辨率：720p\n"
    "- 分镜最大时长：12秒\n"
)


class TestSpecProductionParams:
    """制作参数唯一来源：顶部全局设置（6666 二轮，规格文档不再参与）"""

    def test_global_settings_sole_source(self, set_global_setting):
        from src.video_agent.state.provider_prefs import extract_production_params

        set_global_setting("default_image_resolution", "2K")
        set_global_setting("default_video_resolution", "720p")
        set_global_setting("max_shot_duration", 12)
        p = extract_production_params(_SPEC_TEXT)
        assert p == {
            "image_resolution": "2K",
            "video_resolution": "720p",
            "shot_max_duration": 12,
        }

    def test_legacy_spec_rows_ignored(self, set_global_setting):
        from src.video_agent.state.provider_prefs import extract_production_params

        set_global_setting("default_image_resolution", "4K")
        set_global_setting("max_shot_duration", 8)
        p = extract_production_params("- 图像分辨率：4K\n- 单镜头最大时长：8 秒\n")
        assert p["image_resolution"] == "4K"
        assert p["shot_max_duration"] == 8

    def test_unconfigured_uses_global_defaults(self, set_global_setting):
        from src.video_agent.state.provider_prefs import extract_production_params

        set_global_setting("default_image_resolution", "")
        set_global_setting("default_video_resolution", "")
        set_global_setting("max_shot_duration", 0)
        p = extract_production_params("- 视频标题：无参数\n")
        assert p == {"image_resolution": "", "video_resolution": "", "shot_max_duration": 0}

    def test_resolve_from_state_uses_global_settings(self, set_global_setting):
        from src.video_agent.state.provider_prefs import resolve_spec_production_params

        set_global_setting("max_shot_duration", 12)
        state = {"documents": [{"name": "制片规格.md", "content": _SPEC_TEXT}]}
        p = resolve_spec_production_params(state)
        assert p["shot_max_duration"] == 12


class TestNewWizardDimensions:
    """规格向导新维度归组：图片分辨率/视频分辨率/分镜最大时长"""

    def test_classify_image_resolution(self):
        from src.video_agent.core.option_groups import classify_option

        assert classify_option("2K 高清") == "图片分辨率"
        assert classify_option("图片分辨率选 1K") == "图片分辨率"

    def test_classify_video_resolution(self):
        from src.video_agent.core.option_groups import classify_option

        assert classify_option("720p 标准") == "视频分辨率"
        assert classify_option("1080p 高消") == "视频分辨率"

    def test_classify_shot_max_duration_before_total_duration(self):
        from src.video_agent.core.option_groups import classify_option

        assert classify_option("单镜头 12 秒") == "分镜最大时长"
        assert classify_option("分镜最大时长 8 秒") == "分镜最大时长"

    def test_total_duration_still_classified(self):
        from src.video_agent.core.option_groups import classify_option

        assert classify_option("3-5 分钟") == "时长"


# TestProductionParamNote（executors._production_param_note 制作参数注入）
# 已随任务#36 B5 执行器一步退役删除：制作参数改由通用主路径随 Skill
# 全文直注/章节注入下发，不再有执行器专属注入点。


# ---------- 引导消息轮间注入（7777 三轮） ----------

@pytest.fixture
def svc(tmp_path):
    from src.video_agent.state.manager import StateManager

    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    from src.video_agent.web.action_executor import StateOperationExecutor

    return StateOperationExecutor(svc)


class TestGuidanceQueue:
    """轮间引导登记/取走（B0 新机制：任务级队列，agent_task_manager；
    原 web/guidance.py 队列为死代码，B6/F42 删除，测试迁移至新 API）"""

    def test_enqueue_drain_roundtrip(self):
        import asyncio

        from src.video_agent.web.agent_task_manager import get_agent_task_manager

        async def main():
            tm = get_agent_task_manager()

            async def noop():
                return None

            tm.create("proj-x", noop, task_id="gq-1")
            assert tm.add_pending_guidance("gq-1", {"id": "m1", "text": "先回答我一个问题"}) is True
            assert tm.drain_pending_guidance("gq-1") == [{"id": "m1", "text": "先回答我一个问题"}]
            assert tm.drain_pending_guidance("gq-1") == []  # 取走即清空
            tm.stop("gq-1")

        asyncio.run(main())

    def test_empty_rejected_and_task_isolated(self):
        import asyncio

        from src.video_agent.web.agent_task_manager import get_agent_task_manager

        async def main():
            tm = get_agent_task_manager()

            async def noop():
                return None

            tm.create("proj-a", noop, task_id="gq-a")
            tm.create("proj-b", noop, task_id="gq-b")
            assert tm.add_pending_guidance("gq-a", {"id": "m2", "text": ""}) is False  # 空文本拒绝
            assert tm.add_pending_guidance("", {"id": "m3", "text": "hi"}) is False     # 任务不存在拒绝
            tm.add_pending_guidance("gq-a", {"id": "m4", "text": "A"})
            tm.add_pending_guidance("gq-b", {"id": "m5", "text": "B"})
            assert [i["text"] for i in tm.drain_pending_guidance("gq-a")] == ["A"]  # 任务级隔离
            assert [i["text"] for i in tm.drain_pending_guidance("gq-b")] == ["B"]
            tm.stop("gq-a")
            tm.stop("gq-b")

        asyncio.run(main())


class TestGuidanceRoundInjection:
    """轮间注入：上一轮操作完成后才送达，不打断执行；模型上下文可见"""

    async def test_injected_between_rounds_not_first(self, svc, executor):
        from src.video_agent.core.agent_loop import run_agent_loop

        # audit-0819b：多步链改以 FC 桩模拟（finish=tool_calls 续轮）；
        # 轮间引导注入语义不变（上轮操作完成后才送达，不打断首轮）
        seen = {"msgs": []}
        calls = {"n": 0}

        async def llm(system_prompt, messages, stream_hook=None):
            seen["msgs"].append([str(m.get("content")) for m in messages])
            calls["n"] += 1
            if calls["n"] == 1:
                return ("处理中", "tool_calls", 1)
            return ("完成", "stop", 0)

        events: list = []

        async def on_event(ev):
            events.append(ev)

        # 第 1 轮前无操作完成不注入，注入器只在第 2 轮边界被调用
        pending = [[{"id": "g1", "text": "把第二个元素的颜色调暗一点"}]]

        def injector():
            return pending.pop(0) if pending else []

        result = await run_agent_loop(
            "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor,
            history=[], on_event=on_event, pending_injector=injector,
        )
        # 第一轮未见注入（消息在第二轮才送达，不打断首轮操作）
        assert not any("调暗" in m for m in seen["msgs"][0])
        # 第二轮上下文包含注入的引导消息（带处理要求）
        assert any("调暗" in m and "任务执行期间" in m for m in seen["msgs"][1])
        # SSE 事件下发（携带 id/text，供前端渲染气泡并移除排队条目）
        injected = [e for e in events if e.get("type") == "guidance_injected"]
        assert len(injected) == 1
        assert injected[0]["id"] == "g1" and "调暗" in injected[0]["text"]
        assert result.steps == 2

    async def test_no_injector_keeps_legacy_behavior(self, svc, executor):
        from src.video_agent.core.agent_loop import run_agent_loop

        reply = ('完成', "stop")

        async def llm(system_prompt, messages, stream_hook=None):
            return reply[0], reply[1], 0

        result = await run_agent_loop(
            "x", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
        )
        assert result.steps == 1
