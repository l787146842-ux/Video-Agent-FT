# -*- coding: utf-8 -*-
"""Skill 流程跑通修复批 4：机器门禁线束（15 份 skill × 标准产物序列）。

两层形态之「机器层」（V3-2/V3-3）：只考平台事实，不考模型行为——
scripted 假模型按固定序列驱动真工具链，逐份 skill 断言 §五 机器门禁 7 条：

1. 无假成功：工具报成功 ⇒ 状态里真有对应变化（A1 分析落点 / A2 desc /
   规格文档 / 草稿提示词逐一断言）；
2. 会喊疼：白名单外参数 ⇒ 明确报错可见（error_code=validation）；
3. 事件卡：每张卡在触发时刻弹出（批 2 表），写产物卡进模型上下文
   （flowEvents），规格二次更新复弹（V4-2）；
4. 无干扰：平台建议动作无 kind="next"，无平台计算的"下一步"文案；
5. 不死锁：脚本化全流程（含 workflow_pause 暂停 → 用户回复 → 续作）跑通到底；
6. 失败留痕与原子性：失败报错含保留声明，既有状态零污染（哈希比对）；
7. 能力缺口逃生口（M4）：本线束的通用序列不含 skill 声明的平台缺口步骤
   （如音乐 MV 唇形同步），该条由判官层人工判（scripts/judge_replay.py）。

skill 感知（M6/V3-5）：script_analyze 章节为空/不存在的 skill（如商品宣传
短片）不要求分析产物——跳不跳过分析是模型的判断，线束按章节存在性同步
跳过分析断言。生成类工具不打网络：AdapterFactory 在工具命名空间内被
patch 为假适配器；高危确认闸经 gate_overrides 登记一次性放行（留痕）。
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core import workflow_runtime
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

# 生产 skill 清单（collection 期直接枚举磁盘，单一事实源 = data/skills 目录）
SKILL_SLUGS = sorted(
    p.name for p in SKILLS_DIR.iterdir()
    if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").exists()
)


class ScriptedAdapter(BaseChatAdapter):
    """剧本假模型：按轮次回放 (文本, [(工具名, 参数)]) 序列（FC 轨）。"""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kw) -> ChatResponse:
        step = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        text, calls = step
        return ChatResponse(
            content=text,
            finish_reason="tool_calls" if calls else "stop",
            tool_calls=[
                {"id": f"c{self._i}-{j}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a)}}
                for j, (n, a) in enumerate(calls)
            ],
        )

    async def chat_stream(self, messages, **kw):
        resp = await self.chat(messages, **kw)
        if resp.content:
            yield StreamChunk(type="text_delta", text=resp.content)
        for tc in resp.tool_calls or []:
            yield StreamChunk(
                type="tool_call", tool_name=tc["function"]["name"],
                tool_args=tc["function"]["arguments"],
                finish_reason="tool_calls")
        yield StreamChunk(type="done", finish_reason=resp.finish_reason)


class _FakeImageAdapter:
    """假图片适配器：generate 同步出图（wait_until_complete 短路不轮询）。"""

    async def generate_image(self, **kw):
        return type("R", (), {"status": "completed", "image_urls": ["http://fake/img-1.png"],
                              "task_id": "t-img", "error_msg": ""})()

    async def fetch_result(self, task_id):
        return type("R", (), {"status": "completed", "image_urls": ["http://fake/img-1.png"],
                              "task_id": task_id, "error_msg": ""})()


class _FakeVideoAdapter:
    """假视频适配器：generate 提交任务，fetch_result 返回 completed
    （wait_until_complete 出口判据 = status=='completed' + video_url）。"""

    async def generate(self, **kw):
        return type("R", (), {"status": "processing", "task_id": "t-vid",
                              "error_msg": ""})()

    async def fetch_result(self, task_id):
        return type("R", (), {"status": "completed", "video_url": "http://fake/vid-1.mp4",
                              "task_id": task_id, "error_msg": ""})()


def _board_hash(svc) -> str:
    return hashlib.sha256(json.dumps(
        {k: svc.state_dict.get(k) for k in ("keyElements", "shots", "audioItems")},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _flow_kinds(svc) -> list:
    return [e.get("kind") for e in (svc.state_dict.get("flowEvents") or [])]


def _card_details(svc, card: str) -> list:
    return [e.get("detail") or "" for e in (svc.state_dict.get("flowEvents") or [])
            if e.get("kind") == "event_card" and str(e.get("detail") or "").startswith(card)]


def _run_skill_smoke(slug: str) -> None:
    """对单份 skill 跑标准产物序列，逐条断言机器门禁（失败信息带 slug）。"""
    svc = StateManager.get_instance()
    for cat in ("keyElements", "shots", "audioItems", "assets"):
        svc.state_dict[cat] = []
    svc.state_dict["flowEvents"] = []
    registry.reset_registry()
    registry.sync_all(force=True)
    ToolManager.reset()
    from src.video_agent.tools import register_analysis_tools, register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    from src.video_agent.tools.video.generate_video import GenerateVideoTool
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()
    ToolManager.register(GenerateVideoTool())

    entry = registry.get_entry(slug)
    assert entry is not None, f"[{slug}] skill 未通过注册（镜像目录缺包/坏 frontmatter）"
    needs_analysis = bool((entry.sections.get("planning") or "").strip())

    # 生成不打网络：patch 工具命名空间的 AdapterFactory（先例 test_bounded_media_batch）
    import src.video_agent.tools.document_tools as doc_tools
    import src.video_agent.tools.video.generate_video as gen_video_mod
    from src.video_agent.adapters.factory import AdapterFactory

    class _PatchedFactory:
        @staticmethod
        def get_adapter(kind, provider):
            assert provider == "fake", f"[{slug}] 生成须走线束假适配器"
            return _FakeImageAdapter() if kind == "image_generation" else _FakeVideoAdapter()

    doc_tools.AdapterFactory = _PatchedFactory
    gen_video_mod.AdapterFactory = _PatchedFactory

    script = [
        ("我先分析剧本并写好制片规格。", [
            *([("script_analysis_report", {
                "doc_name": "三体简短版.md",
                "summary": f"[{slug}] 太空打击危机，主角程心。",
                "report_markdown": (
                    f"[{slug}] 剧本分类：A 类（成熟分镜剧本）\n"
                    "- 角色清单：程心（太空电梯，黑色短发）\n"
                    "- 场景清单：太空电梯（碳纳米管井道，镜头 1-3）\n"
                    "- 关键道具：二向箔\n"
                    "- 幕次结构：开篇（约 3 镜）"
                ),
            })] if needs_analysis else []),
            ("document_write", {"name": "制片规格.md", "content":
                f"# 制片规格（{slug}）\n- 画幅：16:9\n- 时长：30s\n- 风格：写实"}),
        ]),
        ("规格就绪，开始搭故事板并落第一张卡。", [
            ("storyboard_create_group", {"group_type": "keyElement", "title": "角色"}),
            ("storyboard_add_draft", {"group_type": "keyElement", "draft": {
                "id": f"{slug}-d1", "label": "程心",
                "desc": "年龄 28；外貌：黑色短发；服装：作训服",
                "prompt": "一位黑色短发的年轻女性，作训服，写实风格"}}),
        ]),
        ("规格有一处更新，同时把提示词补齐。", [
            ("document_write", {"name": "制片规格.md", "content":
                f"# 制片规格（{slug}）\n- 画幅：2.39:1\n- 时长：30s\n- 风格：写实\n- 声音：无旁白"}),
            ("storyboard_patch_draft", {"draft_id": f"{slug}-d1", "draft_type": "keyElement",
                                        "patch": {"prompt": "一位黑色短发的年轻女性，作训服，电影感布光"}}),
        ]),
        ("出关键元素设定图。", [
            ("image_generate", {"mode": "single", "prompt": "程心设定图",
                                "adapter_provider": "fake"}),
        ]),
        ("生成第一段镜头视频。", [
            ("generate_video", {"prompt": "程心走向太空电梯", "duration": 5,
                                "image_url": "http://fake/img-1.png",
                                "adapter_provider": "fake"}),
        ]),
        ("关键内容已就绪，请确认后我继续。", [
            ("workflow_pause", {"message": "请确认以上内容，确认后我将继续。"}),
        ]),
        ("收到确认，全部完成。", []),
    ]
    planner = Planner(state_manager=svc, llm_adapter=ScriptedAdapter(script),
                      tool_manager=ToolManager)

    # 高危确认闸一次性放行（模拟用户点「本次放行」，登记留痕）
    workflow_runtime.reduce_gate_overrides(
        svc, ["platform.tool_risk", "platform.gen_confirm"], flush=True)

    # --- 消息 1：标准产物序列（末步 workflow_pause 问即停）---
    # 2026-09-15 铺满批更新：本测试钉的是平台事实落盘（state 记录），非路由架构。
    # 可委派阶段生产工具（script_analysis_report / storyboard_create_group 等）
    # 在顶级生产轮由 PRODUCTION_MAIN_PRUNE 裁剪，主代理直调会被 turn_excluded
    # 拒执行（one visibility = one permission）。
    # 本测试经 subagent_depth=1 模拟阶段执行器上下文（子级不继承顶级生产裁剪），
    # 工具面完整可用；路由改造（主代理经 run_subagent 委派）由 test_subagent_delegation 覆盖。
    ctx = PlannerContext(use_studio_context=True, skill_name=slug, subagent_depth=1)
    result = asyncio.run(planner.handle_message("请按 Skill 流程开始", ctx))
    assert not result.warnings or all("上限" not in w for w in result.warnings), \
        f"[{slug}] 意外警告: {result.warnings}"

    # §五-1 无假成功：分析落点（M6 感知）
    if needs_analysis:
        analysis = svc.state_dict.get("analysis") or {}
        assert analysis.get("summary"), f"[{slug}] script_analysis_report 报成功但 state.analysis 空"
        assert "程心" in (analysis.get("report") or ""), f"[{slug}] 分析报告全文未落盘"
    else:
        assert not (svc.state_dict.get("analysis") or {}), \
            f"[{slug}] 无分析章节却产生了分析产物（M6 违背：平台不应强求）"
    # 规格文档两轮写入（建立 + 更新）
    docs = [d for d in (svc.state_dict.get("documents") or [])
            if d.get("name") == "制片规格.md"]
    assert len(docs) == 1 and "2.39:1" in docs[0]["content"], \
        f"[{slug}] 规格文档未落盘/未更新"
    # 故事板结构与卡片
    groups = svc.state_dict.get("keyElements") or []
    assert groups and groups[0]["title"] == "角色", f"[{slug}] 分组未落盘"
    draft = (groups[0].get("drafts") or [{}])[0]
    assert draft.get("desc") == "年龄 28；外貌：黑色短发；服装：作训服", \
        f"[{slug}] A2 desc 静默丢弃（假成功）"
    assert draft.get("prompt"), f"[{slug}] patch_draft 报成功但提示词未落卡"

    # §五-3 事件卡：逐卡触发时刻（批 2 表）+ 写产物卡进模型上下文
    kinds = _flow_kinds(svc)
    assert "event_card" in kinds, f"[{slug}] 写产物事件卡未进模型上下文"
    assert len(_card_details(svc, "规格已完成")) == 2, \
        f"[{slug}] 规格卡应建立+更新各发一次（V4-2），实际: {_card_details(svc, '规格已完成')}"
    assert len(_card_details(svc, "故事板已更新")) >= 3, f"[{slug}] 故事板卡缺失"
    assert _card_details(svc, "素材已完成"), f"[{slug}] 素材已完成卡缺失"
    assert _card_details(svc, "时间线已更新"), f"[{slug}] 时间线已更新卡缺失"

    # §五-2 会喊疼：白名单外参数明确报错（不静默丢弃）
    bad_res = asyncio.run(ToolManager.invoke_tool("storyboard_add_draft", {
        "group_id": "ghost", "group_type": "keyElement",
        "draft": {"label": "x", "content": "正文", "tags": ["a"]}}))
    assert bad_res.success is False and bad_res.error_code == "validation", \
        f"[{slug}] 白名单外参数未报错（静默丢弃回潮）"
    assert "保持原样" in bad_res.error and "重新提交" in bad_res.error, \
        f"[{slug}] 失败报错缺保留声明/补救指引"

    # §五-6 失败原子性基线：失败后与暂停前哈希一致
    hash_before_pause = _board_hash(svc)

    # --- §五-5 前半：workflow_pause 停得住（问即停在消息 1 末步）---
    assert result.confirmation and result.pause_id, \
        f"[{slug}] workflow_pause 未产生暂停卡（confirmation={result.confirmation!r}）"
    active = (svc.state_dict.get("interaction") or {}).get("active_pause") or {}
    assert active.get("pause_id") == result.pause_id, f"[{slug}] 暂停槽未登记"
    assert _board_hash(svc) == hash_before_pause, f"[{slug}] 暂停卡发行污染了故事板状态"

    # --- 消息 2：用户回复续作到底（§五-5 后半：不死锁）---
    workflow_runtime.reduce_gate_overrides(
        svc, ["platform.tool_risk", "platform.gen_confirm"], flush=True)
    ctx3 = PlannerContext(use_studio_context=False, skill_name=slug)
    final = asyncio.run(planner.handle_message("确认，继续", ctx3))
    assert final.text, f"[{slug}] 续作轮无正文（假停/死锁）"

    # §五-4 无干扰：平台建议动作无 kind="next"，无平台"下一步"计算文案
    for act in (final.suggested_actions or []):
        assert act.get("kind") != "next", f"[{slug}] 平台计算的下一步建议回潮: {act}"
    tail = json.dumps(svc.state_dict.get("interaction") or {}, ensure_ascii=False)
    assert "请先搭建关键元素" not in tail, f"[{slug}] 状态里残留指令式平台引导"


@pytest.mark.parametrize("slug", SKILL_SLUGS)
def test_skill_smoke_platform_facts(slug, tmp_path):
    """机器门禁：15 份 skill 逐份跑标准产物序列（§五 平台事实 1-6）。"""
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    try:
        _run_skill_smoke(slug)
    finally:
        StateManager.reset_instance()
        ToolManager.reset()
        registry.reset_registry()


# ---------- 批 11 · 9999 场景端到端冒烟（V6 计划 §五 机器断言 1-4） ----------

def _patch_fake_image_factory() -> None:
    """生成不打网络：patch 工具命名空间的 AdapterFactory（同线束先例）。"""
    import src.video_agent.tools.document_tools as doc_tools
    from src.video_agent.adapters.factory import AdapterFactory

    class _PatchedFactory:
        @staticmethod
        def get_adapter(kind, provider):
            assert provider == "fake", "生成须走线束假适配器"
            return _FakeImageAdapter()

    doc_tools.AdapterFactory = _PatchedFactory


def test_9999_consent_flow_smoke(tmp_path):
    """9999 死锁场景端到端重放（confirm_before_gen 默认档 + 无本次放行）：

    模型建组后直接调 image_generate → tool_risk 闸拦（无同意）→
    批 9 修复后回合不再终止、拒因指引被下一轮消费 → 模型发暂停卡 →
    用户接受（同意账本登记）→ 重提放行（consent=pause_accept 留痕）→
    新一轮无同意再拦（fail-closed 保持）。
    修复前此处回合以模型过期口播终止（假话）+ 死锁。"""
    from src.video_agent.config import settings
    from src.video_agent.core.tracer import AgentTracer
    from src.video_agent.web.chat_consume import consume_pause_response

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    old_pref = settings.execution_preference
    object.__setattr__(settings, "execution_preference", "confirm_before_gen")
    try:
        for cat in ("keyElements", "shots", "audioItems", "assets"):
            svc.state_dict[cat] = []
        svc.state_dict["flowEvents"] = []
        registry.reset_registry()
        registry.sync_all(force=True)
        ToolManager.reset()
        from src.video_agent.tools import register_analysis_tools, register_document_tools
        from src.video_agent.tools.storyboard_tools import register_storyboard_tools
        register_storyboard_tools()
        register_document_tools()
        register_analysis_tools()
        _patch_fake_image_factory()

        # 默认档确认（防其他测试泄漏档位）
        assert settings.execution_preference == "confirm_before_gen"
        # 无 gate_overrides：拦截必须来自「缺同意」，修复不得依赖本次放行按钮
        assert not (svc.state_dict.get("interaction") or {}).get("gate_overrides")

        # --- 消息 1：建组后直接生成 → 闸拦 → 指引回喂 → 模型发暂停卡 ---
        # 轮始模拟（web 层 chat_opening 职责）：轮序递增
        svc.state_dict["turn_seq"] = 1
        script = [
            ("好的！关键元素已创建。现在生成男女主形象参考图。", [
                ("storyboard_create_group", {"group_type": "keyElement",
                                             "title": "女主·沈晚"}),
                ("image_generate", {"mode": "single", "prompt": "女主形象图",
                                    "adapter_provider": "fake"}),
            ]),
            ("收到拦截指引，先暂停请求您的确认。", [
                ("workflow_pause", {"message": "我将生成女主形象参考图，请确认。",
                                    "options": [
                                        {"label": "确认生成",
                                         "description": "按已写提示词生成"},
                                        {"label": "先调整",
                                         "description": "告诉我要改什么"}]}),
            ]),
        ]
        planner = Planner(state_manager=svc,
                          llm_adapter=ScriptedAdapter(script),
                          tool_manager=ToolManager)
        ctx = PlannerContext(use_studio_context=False,
                             skill_name="古风甜宠短剧")
        result1 = asyncio.run(planner.handle_message("可以", ctx))

        # ① 全拒收轮不死锁：循环继续到第 2 轮并发行暂停卡（修复前回合
        #    以第 1 轮口播终止、无暂停卡）
        assert result1.confirmation and result1.pause_id, \
            f"[9999] 全拒收轮后未发行暂停卡（死锁未修复）: {result1.text!r}"
        # 闸拦截警告随消息可见（fc_warnings 并入）
        assert any("高风险工具确认闸拦截" in w for w in (result1.warnings or [])), \
            f"[9999] 闸拦截警告未随消息可见: {result1.warnings}"
        # 全程未动用「本次放行」
        assert not (svc.state_dict.get("interaction") or {}).get("gate_overrides"), \
            "[9999] 冒烟不应依赖本次放行按钮"

        # --- 用户接受暂停卡（模拟 web 层轮始递增 + 结构化消费）---
        svc.state_dict["turn_seq"] = 2
        marker = consume_pause_response(
            svc, {"pause_id": result1.pause_id, "value": "确认生成",
                  "label": "确认生成"})
        assert marker and marker["decision"] == "accept"
        assert (svc.state_dict.get("interaction") or {})\
            .get("generation_consented_turn") == 2, "同意账本未登记"

        # --- 消息 2：接受后重提 → 放行（consent=pause_accept 留痕）---
        script2 = [
            ("收到确认，现在生成形象图。", [
                ("image_generate", {"mode": "single", "prompt": "女主形象图",
                                    "adapter_provider": "fake"}),
            ]),
            ("形象图已生成完毕。", []),
        ]
        planner.llm_adapter = ScriptedAdapter(script2)
        AgentTracer.reset()
        ctx2 = PlannerContext(use_studio_context=False,
                              skill_name="古风甜宠短剧")
        result2 = asyncio.run(planner.handle_message("确认生成", ctx2))
        assert result2.applied_actions >= 1, \
            f"[9999] 接受后重提仍被拦（同意账本未生效）: {result2.warnings}"
        assert not any("高风险工具确认闸拦截" in w for w in (result2.warnings or []))
        assert _card_details(svc, "素材已完成"), "[9999] 生成成功但素材卡缺失"
        consent_verdicts = [g for g in AgentTracer.get_instance().get_recent_gates(80)
                            if g.get("rule_id") == "platform.tool_risk"
                            and g.get("ok") and "consent=pause_accept" in (g.get("message") or "")]
        assert consent_verdicts, "[9999] 同意放行未留痕 consent=pause_accept"

        # --- 消息 3：新一轮无同意 → 生成再拦（fail-closed 保持，端到端）---
        svc.state_dict["turn_seq"] = 3  # 轮始推进：上一轮同意自然过期
        script3 = [
            ("再生成一张形象图。", [
                ("image_generate", {"mode": "single", "prompt": "女主形象图二",
                                    "adapter_provider": "fake"}),
            ]),
            ("上一轮同意已过期，先暂停请求您的确认。", [
                ("workflow_pause", {"message": "将再生成一张形象图，请确认。"}),
            ]),
        ]
        planner.llm_adapter = ScriptedAdapter(script3)
        ctx3 = PlannerContext(use_studio_context=False,
                              skill_name="古风甜宠短剧")
        result3 = asyncio.run(planner.handle_message("再生成一张", ctx3))
        # 生成调用必须被拦（轮次推进后同意失效）且指引再次回喂、模型补发暂停卡
        assert any("高风险工具确认闸拦截" in w for w in (result3.warnings or [])), \
            "[9999] 新一轮无同意的生成未被拦（fail-closed 破防）"
        assert result3.confirmation and result3.pause_id, \
            "[9999] 再拦后模型未发行暂停卡（自纠闭环断裂）"
    finally:
        object.__setattr__(settings, "execution_preference", old_pref)
        StateManager.reset_instance()
        ToolManager.reset()


def test_1000_spec_write_consent_flow_smoke(tmp_path):
    """1000 事故场景端到端重放（2026-09-07 外部标杆对齐后语义迁移）：

    原场景（未同意的规格写入被 tool_risk 闸硬拦 → 批 12 同意章程兑现放行）
    已随 document_write 降 medium 退役——写入不再入确认闸、直接执行。
    本冒烟保留三条仍然成立的回归：
    ① 规格写入经 planner 全链路落盘 + 「规格已完成」事件卡（1000 事故的
    最终产物语义，对齐外部标杆 进度播报）；
    ② 混合轮（读 + 写 + 暂停卡）问即停发行与 accept 消费链路；
    ③ 同意账本登记仍在（costly 生成确认仍在消费）。"""
    from src.video_agent.config import settings
    from src.video_agent.core.tracer import AgentTracer
    from src.video_agent.web.chat_consume import consume_pause_response

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    old_pref = settings.execution_preference
    object.__setattr__(settings, "execution_preference", "confirm_before_gen")
    try:
        for cat in ("keyElements", "shots", "audioItems", "assets"):
            svc.state_dict[cat] = []
        svc.state_dict["flowEvents"] = []
        registry.reset_registry()
        registry.sync_all(force=True)
        ToolManager.reset()
        from src.video_agent.tools import register_document_tools
        register_document_tools()

        # --- 消息 1：混合轮（read_skill 成功 + 写规格直执行 + 规格确认暂停卡）---
        svc.state_dict["turn_seq"] = 1
        script1 = [
            ("我先读取本 Skill 的拆解规范，然后写入制片规格。", [
                ("read_skill", {"name": "未来科幻真人电影"}),
                ("document_write", {"name": "制片规格.md",
                                    "content": "# 制片规格（草稿）"}),
            ]),
            ("规格参数需要您确认，我先暂停。", [
                ("workflow_pause", {"message": "请确认规格：硬核深空探索 / 3分钟 / 5段式？",
                                    "options": [
                                        {"label": "确认规格",
                                         "description": "按此参数写入制片规格"},
                                        {"label": "调整",
                                         "description": "告诉我要改什么"}]}),
            ]),
        ]
        planner = Planner(state_manager=svc,
                          llm_adapter=ScriptedAdapter(script1),
                          tool_manager=ToolManager)
        # 2026-09-15 铺满批更新：本测试钉的是规格写入落盘 + 暂停卡发行链路，
        # 非路由架构。read_skill / document_write 在顶级生产轮被裁剪
        # （PRODUCTION_MAIN_PRUNE + _STUDIO_STATE_TOOLS），经 subagent_depth=1
        # 模拟阶段执行器上下文（子级不继承顶级生产裁剪），工具面完整可用。
        ctx1 = PlannerContext(use_studio_context=True,
                              skill_name="未来科幻真人电影",
                              subagent_depth=1)
        result1 = asyncio.run(planner.handle_message("开始", ctx1))
        # 规格写入（medium）直执行：无确认闸拦截告警，草稿已落盘
        assert not any("高风险工具确认闸拦截" in w
                       for w in (result1.warnings or [])), \
            f"[1000] 规格写入（medium）不应再被拦: {result1.warnings}"
        docs = {d.get("name"): d for d in svc.state_dict.get("documents") or []}
        assert "制片规格.md" in docs, "[1000] 规格草稿未落盘"
        # 混合轮问即停：暂停卡正常发行
        assert result1.confirmation and result1.pause_id, \
            f"[1000] 混合轮未发行暂停卡: {result1.text!r}"

        # --- 用户接受暂停卡（web 层轮始递增 + 结构化消费，同 9999 冒烟）---
        svc.state_dict["turn_seq"] = 2
        marker = consume_pause_response(
            svc, {"pause_id": result1.pause_id, "value": "确认规格",
                  "label": "确认规格"})
        assert marker and marker["decision"] == "accept"
        assert (svc.state_dict.get("interaction") or {})\
            .get("generation_consented_turn") == 2, "同意账本未登记"

        # --- 消息 2：确认后写正式规格 → 落盘 + 兑现事件卡 ---
        spec_content = "# 制片规格\n风格：硬核深空探索\n时长：3分钟\n结构：5段式\n"
        script2 = [
            ("收到确认，现在写入制片规格文档。", [
                ("document_write", {"name": "制片规格.md",
                                    "content": spec_content}),
            ]),
            ("制片规格已确立。", []),
        ]
        planner.llm_adapter = ScriptedAdapter(script2)
        AgentTracer.reset()
        ctx2 = PlannerContext(use_studio_context=True,
                              skill_name="未来科幻真人电影",
                              subagent_depth=1)
        result2 = asyncio.run(planner.handle_message("硬核深空探索 / 3分钟 / 5段式", ctx2))
        assert result2.applied_actions >= 1, \
            f"[1000] 确认后写规格未执行: {result2.warnings}"
        assert not any("高风险工具确认闸拦截" in w for w in (result2.warnings or []))
        # 规格落盘（skill 阶段 1 产物兑现）
        docs = {d.get("name"): d for d in svc.state_dict.get("documents") or []}
        assert "制片规格.md" in docs and (docs["制片规格.md"].get("content") or "").strip(), \
            "[1000] 规格文档未落盘"
        # 兑现事件卡（「规格已完成」，与 外部标杆同款进度播报）
        assert _card_details(svc, "规格已完成"), "[1000] 规格落盘但事件卡缺失"
    finally:
        object.__setattr__(settings, "execution_preference", old_pref)
        StateManager.reset_instance()
        ToolManager.reset()
        registry.reset_registry()
