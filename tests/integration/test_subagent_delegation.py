# -*- coding: utf-8 -*-
"""正宗子代理委派 + 完成盖章 端到端回归（scripted 模型，不连真供应商）。

钉死两条链路（真过闸机、真写工作台，只把模型换成脚本）：
① 父经 FC `run_subagent` 委派 → 子在隔离上下文（独立 messages + 类型白名单）连续
   跑完并真落账 → 只回摘要给父（子的中间步不进父上下文）→ 子线程事件流自描述落流；
② 假停机械续跑开关关时的放手形态：零工具纯口头收尾一轮即止（开关开的结构性
   机械续跑语义由 test_fc_leak_fakestop 钉死，2026-09-14 翻案批）。
"""
import json

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core import session_log
from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.analysis_tools import register_analysis_tools
from src.video_agent.tools.document_tools import register_document_tools
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.storyboard_tools import register_storyboard_tools

SKILL = "AI-短剧一站式生成"


@pytest.fixture(autouse=True)
def _ensure_tools():
    # 显式重注册全套（同 worker 其它文件会 ToolManager.reset() 清全局表，
    # 跨文件污染先例见 test_hybrid_boundaries / test_subagent_run_subagent）：
    # 委派链父子两端都要真工具在册（子在白名单内建组落账）。
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


@pytest.fixture
def fakestop_off():
    """假停机械续跑显式关：本文件两测钉隔离/放手形态，不随环境 runtime_settings 漂移。"""
    from src.video_agent.config import settings
    original = settings.fakestop_auto_resume_enabled
    object.__setattr__(settings, "fakestop_auto_resume_enabled", False)
    yield
    object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    st = instance.state_dict
    # 客观前置就位（分析已落账 + 规格在盘），但结构为空：
    # 委派与未盖章判定都只认这些客观事实
    st["usedSkills"] = [SKILL]
    st["analysis"] = {"summary": "一句话总结：程心苏醒。"}
    st["documents"] = [{"name": "制片规格.md", "content": "画幅：16:9"}]
    for key in ("keyElements", "shots", "audioItems"):
        st[key] = []
    yield instance
    StateManager.reset_instance()


class _ScriptedAdapter(BaseChatAdapter):
    """按脚本依次吐响应；记录每轮收到的 messages（父子上下文隔离的取证面）。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        item = self._script.pop(0) if self._script else {"text": "收到。"}
        if item.get("tool"):
            return ChatResponse(
                content=item.get("content", ""), finish_reason="tool_calls",
                tool_calls=[{"id": f"call_{len(self.calls)}", "type": "function",
                             "function": {"name": item["tool"],
                                          "arguments": json.dumps(
                                              item.get("args", {}),
                                              ensure_ascii=False)}}],
            )
        return ChatResponse(content=item.get("text", ""), finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        response = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        if response.tool_calls:
            fn = (response.tool_calls[0].get("function") or {})
            # 真实契约（openai_compat._stream_once:879-886）：tool_args 是**已解析的
            # dict**（解析失败才走 tool_args_raw/tool_args_error 旁路）。
            # 本桩此前恒不触发（父与子都走非流式），2026-09-21 批G 让子代理改走
            # 流式通道后才被激活——原先传 JSON 字符串给 dict() 会 ValueError。
            yield StreamChunk(type="tool_call", tool_name=str(fn.get("name")),
                              tool_args=json.loads(fn.get("arguments") or "{}"))
        else:
            yield StreamChunk(type="text_delta", text=response.content)
        yield StreamChunk(type="done", finish_reason=response.finish_reason)


def _tool_call_names(messages) -> list:
    out = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            out.append(str(((tc or {}).get("function") or {}).get("name") or ""))
    return out


async def test_delegation_runs_child_in_isolated_context_and_returns_summary(svc, fakestop_off):
    """父发 run_subagent → 子真建组落账 → 只回摘要；子的中间步不出现在父上下文。

    假停机械续跑显式关：本测钉的是子代理上下文隔离，收尾轮次形态不在此设防
    （开关开的机械续跑语义由 test_fc_leak_fakestop 覆盖）。"""
    adapter = _ScriptedAdapter([
        # 1) 父：委派（通用子代理，无类型）
        {"tool": "run_subagent", "args": {
            "task": "按已确认规格拆解关键元素：程心、阶梯计划"}},
        # 2) 子：真调建组工具（经同一闸机链、写同一工作台）
        {"tool": "storyboard_create_group", "args": {
            "group_type": "keyElement", "title": "程心",
            "draft": {"label": "程心", "desc": "主角"}}},
        # 3) 子：摘要收尾（本轮调过工具 = 说法有据，不被盖章闸驳回）
        {"text": "已建 1 组关键元素（1 卡：程心）。"},
        # 4) 父：向用户交代
        {"text": "结构搭建已由子代理完成。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "把剧本拆成关键元素",
        PlannerContext(skill_name=SKILL, use_studio_context=True))

    # ① 子的产物真的落进共享工作台（账本合流，B4 结论）
    ke = svc.state_dict.get("keyElements") or []
    assert any(g.get("title") == "Element_程心" for g in ke), "子级建组未落账"
    # ② 父收到子的摘要，并向用户交付
    assert "结构搭建已由子代理完成" in (result.text or "")
    parent_last = adapter.calls[-1]
    joined = json.dumps(parent_last, ensure_ascii=False)
    assert "已建 1 组关键元素" in joined, "子的摘要未回喂进父上下文"
    # ③ 隔离：调用序列 = 父→子(2 步)→父（子在内联跑完，父等摘要）；
    #    子的建组调用只出现在子自己的历史里（calls[1]/calls[2]），
    #    父的上下文（calls[0]/calls[-1]）只有 run_subagent 那一次调用
    assert len(adapter.calls) == 4, f"调用序列不符（实为 {len(adapter.calls)}）"
    assert "storyboard_create_group" in _tool_call_names(adapter.calls[2]), \
        "测试前提：子级确已在自己上下文里发起建组调用"
    for parent_idx in (0, len(adapter.calls) - 1):
        assert "storyboard_create_group" not in _tool_call_names(adapter.calls[parent_idx]), \
            "子的中间步灌进了父上下文（隔离失效）"
    # ④ 子线程落流自描述（任务 + 过程 + 摘要），供左栏只读记录
    threads = svc.subagent_threads()
    assert len(threads) == 1, "子代理隐藏线程未创建"
    events = session_log.load_events(svc, threads[0]["conversation_id"])
    types = [e.get("type") for e in events]
    assert "user/message" in types and "assistant/message" in types
    assert any("程心" in str(e.get("content") or "")
               for e in events if e.get("type") == "assistant/message")


async def test_zero_action_stop_ends_in_one_round(svc, fakestop_off):
    """开关关 = 无检测放行（dsh 默认不配 hook 的放手形态）：零工具纯口头收尾一轮即止。

    2026-09-14 翻案 2026-09-10「模型自决收尾即收尾」：开关开时 Skill 进行中纯文本
    收尾轮会被结构性机械续跑，该语义由 test_fc_leak_fakestop 钉死；本测显式关开关，
    钉住另一侧形态，不随环境 runtime_settings 漂移。"""
    adapter = _ScriptedAdapter([
        {"text": "已完成关键元素与分镜拆解，请查看故事板。"},
        {"text": "不该到达"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "继续", PlannerContext(skill_name=SKILL, use_studio_context=True))

    assert len(adapter.calls) == 1, "零动作纯文本轮一轮收尾（无未盖章续跑预算）"
    assert "请查看故事板" in (result.text or "")
    # 一次也没建成：工作台仍为空（平台只做事实对账，不拦人）
    assert not (svc.state_dict.get("keyElements") or [])


async def test_stage_delegation_injects_only_stage_section(svc, fakestop_off):
    """阶段执行器（2026-09-15 试点，对齐 Flova 章节隔离；2026-09-19 主代理
    纯编排批：委派集 = 素材分析 + 故事板三阶段 + 提示词撰写）端到端：
    委派带 stage=write_media_prompt
    → 子级任务文本精准携带该阶段章节全文，storyboard_shots 章节探针零在场
    （跨阶段污染根除）；子级真建组落账、只回摘要；子线程 meta 记阶段名。
    用真实 Skill（data/skills）验证章节切割。"""
    # 客观前置：分镜结构已由 storyboard_shots 阶段建好（结构属上一阶段），
    # write_media_prompt 只往既有草稿卡里写提示词——与 2222 实跑同序。
    svc.state_dict["shots"] = [{
        "id": "grp-s01", "title": "Shot_S01 开场", "group_type": "shot",
        "desc": "【空间锚点 / 舱内】固定参照物：舷窗。人物动作与对白：程心苏醒。"
                "分镜语法：中景+平视+缓推。",
        "summary": "含内部剪辑（约10s）", "sceneRefs": ["星环号球形舱"], "drafts": [],
    }]
    adapter = _ScriptedAdapter([
        # 1) 父：委派媒体提示词编写阶段
        {"tool": "run_subagent", "args": {
            "task": "为已建分镜编写媒体提示词",
            "stage": "write_media_prompt"}},
        # 2) 子：真调本阶段工具把提示词写进既有草稿卡。
        #    2026-09-21 批0（事故 2222/Q5）：write_media_prompt 的 _STAGE_TOOLS
        #    = {add_draft, patch_draft}——建组不属本阶段（分镜结构由
        #    storyboard_shots 阶段建好），故改用 add_draft 落卡。
        {"tool": "storyboard_add_draft", "args": {
            "group_id": "current", "group_type": "shot",
            "draft": {"label": "S01 提示词", "mediaType": "video", "genType": "video",
                      "prompt": "[镜头]: Medium waist shot, fixed camera, eye-level",
                      "desc": "程心苏醒的首镜提示词"}}},
        # 3) 子：摘要收尾
        {"text": "已为 1 组分镜写入提示词。"},
        # 4) 父：向用户交代
        {"text": "提示词编写已由子代理完成。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "开始写提示词",
        PlannerContext(skill_name=SKILL, use_studio_context=True))

    # ① 落账与摘要回父（委派链路基本盘）
    shots = svc.state_dict.get("shots") or []
    drafts = [d for g in shots for d in (g.get("drafts") or [])]
    assert drafts, "stage 子级写提示词未落账"
    assert "Medium waist shot" in str(drafts[0].get("prompt") or "")
    assert "提示词编写已由子代理完成" in (result.text or "")

    # ② 章节隔离：子级首轮模型调用的 user 消息（= build_subagent_task 包装文本）
    #    含 write_media_prompt 章节真身探针，零含 storyboard_shots 章节探针
    #   （真实 Skill 文本切割）；落流 user/message 是原始任务书（只读记录首行）
    threads = svc.subagent_threads()
    assert len(threads) == 1
    scope = svc.get_conversation_scope(threads[0]["conversation_id"])
    assert scope.get("subagent_kind") == "stage:write_media_prompt"
    child_first = adapter.calls[1]
    task_text = next(str(m.get("content") or "") for m in child_first
                     if m.get("role") == "user")
    assert "本次委派阶段：提示词编写" in task_text
    assert "内切镜时长估算" in task_text, "write_media_prompt 章节未精准注入"
    assert "分镜语法三件套" not in task_text, "storyboard_shots 章节泄漏进子代理"
    assert "章节内容截断" not in task_text, "精准注入不应走全文截断路径"


async def test_stage_delegation_storyboard_shots(svc, fakestop_off):
    """主代理纯编排批（2026-09-19）：故事板设计委派子代理端到端——
    ① 主代理面结构性缺 storyboard_create_group/patch_draft（只能委派）；
    ② 委派带 stage=storyboard_shots → 子级任务精准注入 storyboard_shot 章节
      （「分镜语法三件套」探针在场），write_media_prompt 章节探针零在场；
    ③ 子级真建 shot 组落账、只回摘要；子线程 meta 记 stage:storyboard_shots。
    用真实 Skill（data/skills）验证章节切割与结构锁。"""
    # ① 主代理（顶级生产轮）结构性缺故事板执行写入工具（纯编排）
    planner = Planner(state_manager=svc, llm_adapter=None, tool_manager=ToolManager)
    main_excluded = planner._compute_excluded_tools(
        PlannerContext(skill_name=SKILL, use_studio_context=True))
    assert "storyboard_create_group" in main_excluded
    assert "storyboard_patch_draft" in main_excluded

    adapter = _ScriptedAdapter([
        # 1) 父：委派分镜设计阶段
        {"tool": "run_subagent", "args": {
            "task": "按已确认规格与关键元素拆解分镜",
            "stage": "storyboard_shots"}},
        # 2) 子：真调建组工具（shot 组 sceneRefs 强非空是闸机硬要求，带上引用）
        {"tool": "storyboard_create_group", "args": {
            "group_type": "shot", "title": "S01 开场",
            "desc": "【空间锚点 / 舱内】固定参照物：舷窗。人物动作与对白：程心苏醒。"
                    "分镜语法：中景+平视+缓推。",
            "summary": "含内部剪辑（约10s）",
            "scene_refs": ["星环号球形舱"]}},
        # 3) 子：摘要收尾
        {"text": "已建 1 组分镜（S01 开场）。"},
        # 4) 父：向用户交代
        {"text": "分镜设计已由子代理完成。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "开始拆分镜",
        PlannerContext(skill_name=SKILL, use_studio_context=True))

    # ③ 落账与摘要回父
    shots = svc.state_dict.get("shots") or []
    assert any(g.get("title") == "Shot_S01 开场" for g in shots), \
        "storyboard_shots 子级建组未落账"
    assert "分镜设计已由子代理完成" in (result.text or "")

    threads = svc.subagent_threads()
    assert len(threads) == 1
    scope = svc.get_conversation_scope(threads[0]["conversation_id"])
    assert scope.get("subagent_kind") == "stage:storyboard_shots"
    child_first = adapter.calls[1]
    task_text = next(str(m.get("content") or "") for m in child_first
                     if m.get("role") == "user")
    assert "本次委派阶段：分镜" in task_text
    # ② 章节隔离：storyboard_shot 章节真身在场、write_media_prompt 章节零在场
    assert "分镜语法三件套" in task_text, "storyboard_shots 章节未精准注入"
    assert "内切镜时长估算" not in task_text, "write_media_prompt 章节泄漏进分镜子代理"
    assert "章节内容截断" not in task_text, "精准注入不应走全文截断路径"


async def test_key_elements_child_can_build_voice_card_but_not_image_card(
        svc, fakestop_off):
    """批4 端到端（用户裁决）：key_elements 子代理**能**建音色卡、**不能**建图像卡。

    真过闸机链、真写工作台（只把模型换成脚本）：
    ① 子代理建 mediaType=audio 的音色卡 → 放行落账（该阶段的正经产出，
       Skill 明文「声音特征单独登记为 key_element_audio」）；
    ② 子代理建 mediaType=image 的图像卡 → **被建卡媒体闸拒收**、不落账
       （用户裁决：图像卡含壳与提示词均归 write_media_prompt 阶段）；
    ③ 拒收文案要告诉模型"去哪里做"，防其原地重试。
    """
    adapter = _ScriptedAdapter([
        # 1) 父：委派关键元素阶段
        {"tool": "run_subagent", "args": {
            "task": "登记关键元素与角色音色", "stage": "storyboard_key_elements"}},
        # 2) 子：先建元素组（不带卡=纯结构动作，应放行）
        {"tool": "storyboard_create_group", "args": {
            "group_type": "keyElement", "title": "程心",
            "desc": "女主，东方年轻女性，约27岁，温婉而坚毅。"}},
        # 3) 子：建音色卡（该阶段唯一允许的卡型）→ 应放行
        {"tool": "storyboard_add_draft", "args": {
            "group_id": "current", "group_type": "keyElement",
            "draft": {"label": "Audio_程心", "mediaType": "audio",
                      "tag": "key_element_audio",
                      "timbre": "女中音，温润略带沙哑，语速舒缓",
                      "desc": "声音特征：女中音，音色温润略带沙哑"}}},
        # 4) 子：试图建图像卡 → 应被拒收
        {"tool": "storyboard_add_draft", "args": {
            "group_id": "current", "group_type": "keyElement",
            "draft": {"label": "程心-角色设定图", "mediaType": "image",
                      "genType": "character",
                      "prompt": "写实科幻电影质感，东亚年轻女性…"}}},
        # 5) 子：摘要收尾
        {"text": "已登记 1 位角色与音色卡；图像卡被拒收，留待提示词阶段。"},
        # 6) 父：交代
        {"text": "关键元素已完成。"},
    ])
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=ToolManager)
    result = await planner.handle_message(
        "开始登记关键元素",
        PlannerContext(skill_name=SKILL, use_studio_context=True))

    # ① 音色卡落账
    ke = svc.state_dict.get("keyElements") or []
    assert any(g.get("title") == "Element_程心" for g in ke), "元素组未落账"
    drafts = [d for g in ke for d in (g.get("drafts") or [])]
    assert len(drafts) == 1, f"应只落 1 张音色卡，实际 {len(drafts)} 张：{drafts}"
    assert drafts[0].get("mediaType") == "audio", "落账的应是音色卡"
    assert drafts[0].get("timbre"), "音色卡应带音色描述"
    # ② 图像卡未落账（被拒）
    assert not [d for d in drafts if d.get("mediaType") == "image"], \
        "图像卡被拒收后不得落账"
    assert "关键元素已完成" in (result.text or "")

    # ③ 拒收文案指向正确阶段（回喂给子代理的 tool 结果里可见）
    #    子代理被拒后会带着 tool 结果再发一轮，故在**全部**调用里搜（索引不稳）
    blob = json.dumps(adapter.calls, ensure_ascii=False)
    assert "只允许 mediaType=audio" in blob, "建卡媒体闸未生效（图像卡未拒收）"
    assert "write_media_prompt" in blob, "拒收文案须告诉模型去哪里建图像卡"
