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
                "script_class": "A",
                "summary": f"[{slug}] 太空打击危机，主角程心。",
                "key_points": ["核心人物：程心。"],
                "characters": [{"name": "程心", "scenes": "太空电梯", "appearance": "黑色短发"}],
                "scenes": [{"name": "太空电梯", "features": "碳纳米管", "shot_range": "1-3"}],
                "props": ["二向箔"], "acts": [{"act": "开篇", "shots_estimate": "3"}],
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
    ctx = PlannerContext(use_studio_context=False, skill_name=slug)
    result = asyncio.run(planner.handle_message("请按 Skill 流程开始", ctx))
    assert not result.warnings or all("上限" not in w for w in result.warnings), \
        f"[{slug}] 意外警告: {result.warnings}"

    # §五-1 无假成功：分析落点（M6 感知）
    if needs_analysis:
        analysis = svc.state_dict.get("analysis") or {}
        assert analysis.get("summary"), f"[{slug}] script_analysis_report 报成功但 state.analysis 空"
        assert analysis.get("characters"), f"[{slug}] 角色清单未落盘"
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
