# -*- coding: utf-8 -*-
"""主代理工具面契约单测（2026-09-19 主代理纯编排批更新）。

钉死断言：
① 顶级生产轮主代理结构性缺执行写入工具（MAIN_AGENT_DENY），但保留
   读工具/媒体生成/文档/确认/编排工具；
② 子级面持本阶段声明的生产工具（script_analyze 子级可调 read_uploaded_doc、
   storyboard 子级可调 storyboard_create_group），且**只**持本阶段声明的那部分
   （非本阶段的委派专属写入工具结构性不可见，2026-09-21 批0 事故 2222/Q5）；
③ adjust_scope 不裁剪（微调子对话保留 patch/read 工具）；
④ 轮内 excluded 误调拒执行（one visibility = one permission）；
⑤ stage 映射缺失 fail-loud（装载期校验）；
⑥ 非法 stage fail-loud 拒收。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    MAIN_AGENT_DENY, PIPELINE_STAGE_KINDS, STAGE_TOOL_DENY_EXTRA,
    SUBAGENT_TOOL_DENY, _STAGE_TOOLS, child_deny_set, stage_tools,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult


SKILL = "演示阶段技能"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


# ---------- ① 顶级生产轮面 = 主代理纯编排（锁执行写入工具） ----------

def test_top_level_production_main_agent_deny(svc):
    """主代理纯编排（2026-09-19 用户裁决）：顶级生产轮主代理结构性缺
    MAIN_AGENT_DENY 执行写入工具（只能经委派触达），但保留读工具/
    媒体生成/文档/确认/编排工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)

    # 执行写入工具被锁（故事板结构/素材分析产出/提示词草稿）
    for t in MAIN_AGENT_DENY:
        assert t in excluded, f"{t} 应被主代理结构性裁剪"
    assert "storyboard_create_group" in excluded
    assert "storyboard_delete_group" in excluded
    assert "storyboard_add_draft" in excluded
    assert "storyboard_patch_draft" in excluded
    assert "script_analysis_report" in excluded
    # 读工具不裁（主代理理解需求/读资料）
    assert "read_uploaded_doc" not in excluded
    assert "read_draft" not in excluded
    assert "view_storyboard_media" not in excluded
    assert "read_state_group" not in excluded
    assert "read_skill" not in excluded
    # 媒体生成不裁（例外：花钱生成确认闸留主线程）
    assert "image_generate" not in excluded
    assert "generate_video" not in excluded
    # 编排/文档/确认工具保留
    assert "run_subagent" not in excluded
    assert "workflow_pause" not in excluded
    assert "document_write" not in excluded
    assert "storyboard_confirm_draft" not in excluded
    # structured_output 仍子代理专属（主代理面裁）
    assert "structured_output" in excluded


def test_free_chat_no_prune(svc):
    """自由对话（无 skill）不裁剪：全工具面保留。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(skill_name="", subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)
    # 无 skill → 不触发生产裁剪
    assert "read_uploaded_doc" not in excluded
    assert "storyboard_create_group" not in excluded
    assert "read_skill" not in excluded


# ---------- ② 子级面不继承顶级裁剪 ----------

def test_child_does_not_inherit_main_agent_deny(svc):
    """子级（depth≥1）不继承主代理纯编排 deny——阶段执行器仍持生产工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    # script_analyze 子级：deny 集不含 read_uploaded_doc / script_analysis_report
    ctx_script = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("script_analyze"))
    excluded_script = planner._compute_excluded_tools(ctx_script)
    assert "read_uploaded_doc" not in excluded_script
    assert "script_analysis_report" not in excluded_script

    # 2026-09-22 批6（Q5）：故事板三阶段合并为 storyboard_design →
    # 子级持三原子阶段工具**并集**（建组/删组/加卡/改卡），一次委派干完三件事。
    # 批0 回归修复的「add_draft 必须留」在合并后同样成立（音色卡是该阶段产出）。
    ctx_key = PlannerContext(
        skill_name=SKILL, subagent_depth=1, use_studio_context=True,
        subagent_deny=child_deny_set("storyboard_design"))
    excluded_key = planner._compute_excluded_tools(ctx_key)
    assert "storyboard_create_group" not in excluded_key
    assert "storyboard_delete_group" not in excluded_key
    assert "storyboard_add_draft" not in excluded_key
    # 合并后 patch_draft 也归本阶段（原属 shots 阶段）→ 不再被收走
    assert "storyboard_patch_draft" not in excluded_key
    assert child_deny_set("storyboard_design") == (
        SUBAGENT_TOOL_DENY | STAGE_TOOL_DENY_EXTRA
        | (MAIN_AGENT_DENY - stage_tools("storyboard_design")))
    # 主代理锁掉的 5 件套全在合并阶段集内 ⇒ 合并后无「锁掉即不可达」的孤儿
    assert MAIN_AGENT_DENY <= stage_tools("storyboard_design") | stage_tools(
        "script_analyze")
    # 子代理 read_skill 仍 deny（不能自由读其他章节）
    assert "read_skill" in excluded_key


def test_stage_tools_mapping():
    """stage_tools 返回各阶段生产工具集（_STAGE_TOOLS 单一源）。"""
    assert stage_tools("script_analyze") == frozenset(
        {"read_uploaded_doc", "script_analysis_report"})
    assert stage_tools("media_generate") == frozenset(
        {"storyboard_add_draft", "storyboard_patch_draft"})
    # 2026-09-22 批6（Q5）：故事板三阶段合并为一个委派阶段，工具集 = 三并集
    # （原 key_elements/shots/audio 三份，含批0 回归修复补的 add_draft）。
    # 2026-09-23 批2（Q3）：并入 delete_draft（接线既有 ops.delete_draft，
    # 给模型撤销建错卡的手段——此前建错卡无任何工具可删）。
    # 2026-09-23 批10（事故 4444/P1-1）：并入 patch_group（接线既有
    # ops.patch_group——此前改一个 shotRefs 只能删光整个类目再重建）。
    assert stage_tools("storyboard_design") == frozenset(
        {"storyboard_create_group", "storyboard_delete_group",
         "storyboard_delete_draft", "storyboard_patch_group",
         "storyboard_add_draft", "storyboard_patch_draft"})
    # 三个旧原子阶段已退出委派面（能力名仍在 registry，但不作 stage 解析）
    for legacy in ("storyboard_key_elements", "storyboard_shots",
                   "storyboard_audio"):
        assert stage_tools(legacy) == frozenset(), (
            f"{legacy} 仍在委派面——批6 已合并为 storyboard_design（Q5）")
    # 未知/空阶段返回空集
    assert stage_tools("") == frozenset()
    assert stage_tools("不存在") == frozenset()


def test_main_agent_orchestrator_surface(svc):
    """主代理纯编排（2026-09-19）：生产轮锁掉 5 个执行写入工具，保留
    读工具/媒体生成；委派集 = 素材分析 + 故事板设计 + 媒体生成。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True)
    excluded = planner._compute_excluded_tools(ctx)
    # 执行写入工具被锁
    assert "storyboard_create_group" in excluded
    assert "script_analysis_report" in excluded
    assert "storyboard_add_draft" in excluded
    assert "storyboard_patch_draft" in excluded
    # 读工具保留
    assert "read_skill" not in excluded
    assert "read_uploaded_doc" not in excluded
    # 批6（Q5）：委派面三阶段（故事板三合一）
    # 2026-10-01 媒体生成支（步骤3）：第三阶段名由 write_media_prompt 收敛为
    # media_generate（媒体生成）——Skill 无「提示词编写」流程节点。
    assert PIPELINE_STAGE_KINDS == frozenset({
        "script_analyze", "storyboard_design", "media_generate"})


def test_main_agent_deny_subset_of_stage_tools():
    """MAIN_AGENT_DENY 每个工具都被某个可委派阶段使用（否则锁掉后不可达）。"""
    all_stage_tools = frozenset().union(*_STAGE_TOOLS.values())
    assert MAIN_AGENT_DENY <= all_stage_tools
    # 读工具不在 deny 集（主代理保留读能力）
    assert "read_uploaded_doc" not in MAIN_AGENT_DENY
    # 媒体生成不在 deny 集（例外：留主代理带确认闸）
    assert "image_generate" not in MAIN_AGENT_DENY
    assert "generate_video" not in MAIN_AGENT_DENY


# ---------- ②b 子代理工具面按阶段收口（事故 2222/Q5） ----------

def test_stage_child_face_equals_declared_tools(svc):
    """事故 2222/Q5：子代理工具面必须等于「本阶段声明 + 非专业写入工具」。

    2222 实测：storyboard_key_elements 子代理可见 18/23 个工具，
    storyboard_add_draft / patch_draft / script_analysis_report 全在——
    而注入章节的散文只说它是"登记元素"。散文说没有、手上却有，
    模型只能自行裁决「算不算越权」（该子代理 21.5% 推理花在此），
    最终按"任务书要求 + 工具在手"两票越界写了 17 张提示词卡。

    修法（P2 约束下沉）：让阶段边界由工具面机械保证，不靠散文劝阻。
    """
    sb_write = frozenset({
        "storyboard_create_group", "storyboard_delete_group",
        "storyboard_add_draft", "storyboard_patch_draft",
    })
    planner = Planner(state_manager=svc, llm_adapter=None)
    for stage in sorted(PIPELINE_STAGE_KINDS):
        excluded = planner._compute_excluded_tools(PlannerContext(
            skill_name=SKILL, subagent_depth=1, use_studio_context=True,
            subagent_deny=child_deny_set(stage)))
        visible_pro_write = {
            t for t in MAIN_AGENT_DENY if t not in excluded}
        assert visible_pro_write == set(stage_tools(stage) & MAIN_AGENT_DENY), (
            f"阶段 {stage} 的委派专属写入工具面与 _STAGE_TOOLS 声明不一致："
            f"可见 {sorted(visible_pro_write)}，声明 "
            f"{sorted(stage_tools(stage) & MAIN_AGENT_DENY)}")
        # 故事板写入四件套里，未声明的必须不可见（2222 越界的直接通道）
        assert not ((visible_pro_write & sb_write) - stage_tools(stage))
    # 反向钉：media_generate 正是用 add/patch_draft 的阶段，不得被误收
    assert "storyboard_add_draft" not in child_deny_set("media_generate")
    assert "storyboard_patch_draft" not in child_deny_set("media_generate")


def test_stage_deny_never_starves_declared_tools():
    """防过度收口：任何阶段自己声明的工具都不在它的 deny 集里（断链即 FAIL）。

    与 test_stage_child_face_equals_declared_tools 互补——那边防"收得不够"，
    这边防"收得过头"。1111 批的教训正是过度 allowlist 导致
    script_analysis_report 未授予、分析结论无法提交；批0 回归（key_elements
    被收走 add_draft 致音色卡建不出）是同一类错的第二次发生。
    """
    for stage in sorted(PIPELINE_STAGE_KINDS):
        deny = child_deny_set(stage)
        starved = stage_tools(stage) & deny
        assert not starved, f"阶段 {stage} 的必备工具被自己的 deny 集收走：{sorted(starved)}"
    # 四条硬约束在任何阶段都不被削弱
    for stage in sorted(PIPELINE_STAGE_KINDS):
        assert SUBAGENT_TOOL_DENY <= child_deny_set(stage)
    # 通用委派（无 stage）不并入 MAIN_AGENT_DENY：无阶段即无阶段边界
    assert child_deny_set("") == SUBAGENT_TOOL_DENY
    assert not (MAIN_AGENT_DENY & child_deny_set(""))


# ---------- ②c 阶段建卡媒体类型限定（2026-09-21 批4，用户裁决） ----------

def test_stage_card_media_declaration():
    """声明表单一事实源：故事板设计阶段允许 {audio, video}，image 仍拒。

    用户裁决（2026-09-21 批4）不变：角色/场景/道具的图像卡（含壳）与提示词
    归 media_generate 阶段。
    2026-09-22 批6（Q5）：键随故事板三阶段合并改为 storyboard_design，
    允许集 = 三原子阶段产出并集——audio（关键元素阶段的音色卡）
    + video（分镜阶段的 shot 卡，实跑取证 26 次 create_group 全 shot+video）。
    """
    from src.video_agent.core.subagent import STAGE_CARD_MEDIA, stage_card_media

    assert stage_card_media("storyboard_design") == frozenset({"audio", "video"})
    assert "image" not in stage_card_media("storyboard_design"), (
        "image 卡归提示词撰写阶段（2026-09-21 用户裁决），合并不放开跨阶段产物")
    # 未登记阶段不受限（空集 = 维持现状，不额外收紧）
    for stage in ("media_generate", "script_analyze", ""):
        assert stage_card_media(stage) == frozenset(), \
            f"阶段 {stage} 不应受建卡媒体类型限定"
    # 三个旧原子阶段已退出委派面 ⇒ 不再受限（不再有独立的 ke 阶段）
    for legacy in ("storyboard_key_elements", "storyboard_shots",
                   "storyboard_audio"):
        assert stage_card_media(legacy) == frozenset()
    # 键必须是可委派阶段（装载期校验已保证；此处防表被改坏）
    assert set(STAGE_CARD_MEDIA) <= set(PIPELINE_STAGE_KINDS)


def test_card_media_gate_rejects_image_card_in_storyboard_design():
    """建卡媒体闸：故事板设计阶段建图像卡 → 明确拒收（含"去哪里做"指引）。

    必须是**拒收**而非静默剥离字段——`fc_tool_runner` 记载 2026-09-12 曾有
    「无阶段感知静默剥离 add_draft 内联 prompt」的闸机，造成假成功空提示词卡
    （3333 项目实证），被用户裁决删除。
    """
    from src.video_agent.core.fc_gates import GateContext, card_media_gate

    allowed = frozenset({"audio", "video"})
    ctx = GateContext(stage_card_media=allowed, stage_label="故事板设计")
    # 图像卡拒收，且文案要指向正确阶段
    err = card_media_gate(ctx, "storyboard_add_draft",
                          {"draft": {"mediaType": "image"}})
    assert err and "只允许 mediaType=audio/video" in err
    assert "media_generate" in err, "拒收文案须指明该去哪里做"
    assert "未执行" in err and "保持原样" in err, "缺状态保留声明"
    # 音色卡与分镜卡放行（合并阶段的两类合法产物）
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"mediaType": "audio"}}) is None
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"mediaType": "video"}}) is None
    # mediaType 缺省且**无 audioType** → 构建工厂回落 image，故同样拒收
    # （2026-09-23 批11 订正：原文案写「缺省 → 回落 image」，漏了 audioType
    #  推导这一支；只填 audioType 的音频卡现在推导为 audio，见下方断言）
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"label": "x"}}) is not None
    # 2026-09-23 批11（事故 4444/P1-5）：**只填 audioType 的音频卡不得被误判为 image**。
    # 事故原形：子代理建音频卡只填 audioType（以为声明了种类就够），mediaType 缺省
    # 回落 image ⇒ 被整单拒收，且回喂文案声称「收到 'image'」——那是平台自己的
    # 默认值，模型从未发过。本闸读的是**该卡真实会落库的那个类型**（infer_media_type）。
    # 2026-09-25（用户裁决「故事板设计阶段只建角色音色卡」）：本用例的 ctx 未声明
    # 音频种类维度 ⇒ 判定只到 mediaType 一层，故 bgm 在此仍放行；「设计期 bgm 被拒」
    # 由下方的音频种类用例覆盖（两维正交，勿混）。
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"audioType": "voice"}}) is None, \
        "只填 audioType 的音频卡被误判为 image（4444/P1-5 回归）"
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"audioType": "bgm"}}) is None, \
        "只填 audioType=bgm 的音频卡被误判为 image（4444/P1-5 回归）"
    # 不带卡建组 = 纯结构动作（元素登记要用），放行
    assert card_media_gate(ctx, "storyboard_create_group",
                           {"group_type": "keyElement", "title": "程心"}) is None
    # 带卡建组受同一约束（内联 draft 是同一条写卡通道）
    assert card_media_gate(ctx, "storyboard_create_group",
                           {"group_type": "keyElement",
                            "draft": {"mediaType": "image"}}) is not None
    assert card_media_gate(ctx, "storyboard_create_group",
                           {"group_type": "shot",
                           "draft": {"mediaType": "video"}}) is None


def test_card_media_gate_string_draft_cannot_bypass():
    """**E-1 回归钉**（2026-09-23 批12，事故 4444）：字符串形态 draft 不得绕过。

    工具侧 `ops.coerce_draft_payload` **明确宽容** draft 传成 JSON 字符串
    （8888 实证：模型高频这么传）。原闸机只给 `create_group` 做了 str 拆包，
    `add_draft` 走 `if not isinstance(draft, dict): return None`
    ⇒ **fail-open**：模型把 draft 写成字符串即可绕过阶段媒体闸（工具照常执行）。

    4444 实证：该子代理 **14 次**把 draft 传成字符串（`create_group` 侧被正常
    拦下，证明模型确实高频这么传），`add_draft` 侧则裸奔。
    本钉要求**两入口、两形态，判定完全一致**。
    """
    import json as _json

    from src.video_agent.core.fc_gates import GateContext, card_media_gate

    ctx = GateContext(stage_card_media=frozenset({"audio", "video"}),
                      stage_label="故事板设计")
    obj = {"mediaType": "image", "label": "越权图卡"}
    as_str = _json.dumps(obj, ensure_ascii=False)

    for name in ("storyboard_add_draft", "storyboard_create_group"):
        r_obj = card_media_gate(ctx, name,
                                {"group_type": "keyElement", "draft": obj})
        r_str = card_media_gate(ctx, name,
                                {"group_type": "keyElement", "draft": as_str})
        assert r_obj is not None, f"{name} 对象形态应被拒"
        assert r_str is not None, (
            f"{name} 字符串形态绕过了阶段媒体闸（E-1 回潮，fail-open）")
        assert bool(r_obj) == bool(r_str), f"{name} 两形态判定不一致"

    # 合法卡同样两形态一致放行
    ok_obj = {"mediaType": "audio", "audioType": "voice"}
    for name in ("storyboard_add_draft", "storyboard_create_group"):
        assert card_media_gate(ctx, name,
                               {"group_type": "keyElement", "draft": ok_obj}) is None
        assert card_media_gate(
            ctx, name,
            {"group_type": "keyElement",
             "draft": _json.dumps(ok_obj, ensure_ascii=False)}) is None


def test_card_media_gate_shared_draft_reader_single_source():
    """**同源钉**：两入口必须共用 `_draft_of`（防再次各写一遍口径）。"""
    import inspect

    from src.video_agent.core import fc_gates

    src = inspect.getsource(fc_gates.card_media_gate)
    assert "_draft_of" in src, "取参未走统一入口（E-1 回潮）"
    # 且不得再有分支式重复拆包
    assert "isinstance(draft, str)" not in src, \
        "闸机内重现分支式 str 拆包（应统一走 _draft_of）"


def test_card_media_gate_no_limit_when_undeclared():
    """未登记阶段/通用委派：空集 = 不启用限定（零变化，不误伤其它阶段）。"""
    from src.video_agent.core.fc_gates import GateContext, card_media_gate

    ctx = GateContext()  # 默认空集
    for name, args in (
        ("storyboard_add_draft", {"draft": {"mediaType": "image"}}),
        ("storyboard_create_group", {"group_type": "shot",
                                     "draft": {"mediaType": "video"}}),
    ):
        assert card_media_gate(ctx, name, args) is None, \
            f"未登记阶段不应被限定：{name}"
    # 无关工具一律放行
    assert card_media_gate(GateContext(stage_card_media=frozenset({"audio"})),
                           "storyboard_patch_draft",
                           {"patch": {"prompt": "x"}}) is None


def test_stage_card_media_reaches_gate_ctx_end_to_end(svc):
    """管线连通性（G4）：子代理轮的 stage 真能传到建卡闸（不是躺着的声明）。

    防"表改了但没接线"——planner 轮始按 context.subagent_stage 下发到
    fc_runner，再进 GateContext。这条钉死整条链路。
    """
    from src.video_agent.core.fc_gates import card_media_gate

    planner = Planner(state_manager=svc, llm_adapter=None)
    runner = planner._fc_runner

    # 子代理轮 + 该阶段 → 限定生效
    ctx_ke = PlannerContext(
        skill_name=SKILL, subagent_depth=1, subagent_stage="storyboard_design")
    planner._apply_stage_card_media(ctx_ke)
    assert runner.stage_card_media == frozenset({"audio", "video"})
    assert runner.stage_label == "故事板设计"
    g = runner._gate_ctx()
    assert card_media_gate(g, "storyboard_add_draft",
                           {"draft": {"mediaType": "image"}}) is not None
    assert card_media_gate(g, "storyboard_add_draft",
                           {"draft": {"mediaType": "video"}}) is None

    # 子代理轮 + 其它阶段 → 不受限
    ctx_prompt = PlannerContext(
        skill_name=SKILL, subagent_depth=1, subagent_stage="media_generate")
    planner._apply_stage_card_media(ctx_prompt)
    assert runner.stage_card_media == frozenset()
    assert card_media_gate(runner._gate_ctx(), "storyboard_add_draft",
                           {"draft": {"mediaType": "image"}}) is None

    # 主代理轮（无 stage）→ 不受限
    planner._apply_stage_card_media(
        PlannerContext(skill_name=SKILL, subagent_depth=0))
    assert runner.stage_card_media == frozenset()


def test_card_media_gate_sits_in_chain_before_prompt_gate():
    """链路顺序：建卡媒体闸必须在提示词闸**之前**（链路顺序敏感）。

    否则一张被拒的图像卡会先跑一遍提示词结构校验（无谓开销 + 报错指向错误原因）。
    """
    import inspect

    from src.video_agent.core import fc_gates

    src = inspect.getsource(fc_gates.run_gate_chain)
    assert src.index("card_media_gate") < src.index("prompt_gate"), \
        "建卡媒体闸应在提示词闸之前"


# ---------- ②b 阶段建卡音频种类限定（2026-09-25 用户裁决，8888 取证） ----------

def test_stage_card_audio_types_declaration():
    """声明表单一事实源：故事板设计阶段只允许角色音色卡（audioType=voice）。

    用户裁决原话：「故事板设计阶段，是不能建卡的，除了关键元素的人物音色卡。」
    病灶：`STAGE_CARD_MEDIA` 只到 mediaType 粒度、闸机只读 mediaType ⇒ 本意只为
    音色卡开的口子把 BGM/旁白卡一并放行（8888 实测 3 张 audioType=bgm 卡落库）。
    """
    from src.video_agent.core.subagent import (
        STAGE_CARD_AUDIO_TYPES, PIPELINE_STAGE_KINDS, stage_card_audio_types,
    )

    assert stage_card_audio_types("storyboard_design") == frozenset({"voice"})
    assert set(STAGE_CARD_AUDIO_TYPES) <= set(PIPELINE_STAGE_KINDS)
    # 未登记阶段不受限（维持现状，与 stage_card_media 同款默认）
    assert stage_card_audio_types("media_generate") == frozenset()
    assert stage_card_audio_types("") == frozenset()


def test_card_media_gate_rejects_bgm_and_narration_in_storyboard_design():
    """设计期 BGM/旁白卡整单拒收；音色卡与分镜卡放行（8888 回归钉）。

    必须是**拒收**而非静默剥离（同 3333 假成功空卡裁决），且文案须交代
    「BGM/旁白属 audio_layer 设计，写 desc，卡在音频生成阶段建」防反复重试。
    """
    from src.video_agent.core.fc_gates import GateContext, card_media_gate
    from src.video_agent.core.subagent import (
        stage_card_audio_types, stage_card_media,
    )

    ctx = GateContext(
        stage_card_media=stage_card_media("storyboard_design"),
        stage_card_audio_types=stage_card_audio_types("storyboard_design"),
        stage_label="故事板设计")

    # 角色音色卡：两入口、显式与只填 audioType 两形态，全放行
    for tool in ("storyboard_add_draft", "storyboard_create_group"):
        assert card_media_gate(ctx, tool, {"draft": {"audioType": "voice"}}) is None
        assert card_media_gate(ctx, tool, {
            "draft": {"mediaType": "audio", "audioType": "voice"}}) is None

    # BGM / 旁白 / 未标种类：整单拒收（8888 实跑形态：audioType=bgm）
    for kind in ("bgm", "narration"):
        for tool in ("storyboard_add_draft", "storyboard_create_group"):
            err = card_media_gate(ctx, tool, {
                "draft": {"mediaType": "audio", "audioType": kind}})
            assert err is not None, f"{kind} 卡在故事板设计阶段未被拒收（8888 回归）"
            assert "key_element_audio" in err and "保持原样" in err
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"mediaType": "audio"}}) is not None, \
        "未标 audioType 的音频卡无法证明是音色卡，应拒收"

    # 分镜视频卡不受第二维影响（两维正交）
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"mediaType": "video"}}) is None
    # 图像卡仍被 mediaType 维拒（本批不放开跨阶段产物）
    assert card_media_gate(ctx, "storyboard_add_draft",
                           {"draft": {"mediaType": "image"}}) is not None

    # 字符串形态 draft 同判定（E-1 不回归）
    import json as _json
    assert card_media_gate(ctx, "storyboard_add_draft", {
        "draft": _json.dumps({"mediaType": "audio", "audioType": "voice"})}) is None
    assert card_media_gate(ctx, "storyboard_add_draft", {
        "draft": _json.dumps({"mediaType": "audio", "audioType": "bgm"})}) is not None


def test_stage_card_audio_types_reaches_gate_ctx_end_to_end(svc):
    """管线连通性（G4）：音频种类限定同样真能经 planner 下发到闸机。

    防「表改了但没接线」——与 test_stage_card_media_reaches_gate_ctx_end_to_end 同款。
    """
    from src.video_agent.core.fc_gates import card_media_gate

    planner = Planner(state_manager=svc, llm_adapter=None)
    runner = planner._fc_runner

    planner._apply_stage_card_media(PlannerContext(
        skill_name=SKILL, subagent_depth=1, subagent_stage="storyboard_design"))
    assert runner.stage_card_audio_types == frozenset({"voice"})
    g = runner._gate_ctx()
    assert card_media_gate(g, "storyboard_add_draft",
                           {"draft": {"audioType": "bgm"}}) is not None
    assert card_media_gate(g, "storyboard_add_draft",
                           {"draft": {"audioType": "voice"}}) is None

    # 其它阶段 / 主代理轮 → 该维度不受限
    planner._apply_stage_card_media(PlannerContext(
        skill_name=SKILL, subagent_depth=1, subagent_stage="media_generate"))
    assert runner.stage_card_audio_types == frozenset()
    assert card_media_gate(runner._gate_ctx(), "storyboard_add_draft",
                           {"draft": {"audioType": "bgm"}}) is None


# ---------- ③ adjust_scope 不裁剪 ----------

def test_adjust_scope_no_prune(svc):
    """微调子对话（adjust_scope 非空）不裁剪：保留 patch/read 工具。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    ctx = PlannerContext(
        skill_name=SKILL, subagent_depth=0, use_studio_context=True,
        adjust_scope={"group_id": "g1", "draft_id": "d1"})
    excluded = planner._compute_excluded_tools(ctx)
    # adjust_scope → 不触发生产裁剪
    assert "read_uploaded_doc" not in excluded
    assert "storyboard_create_group" not in excluded
    assert "storyboard_patch_draft" not in excluded
    assert "read_draft" not in excluded


# ---------- ④ 轮内 excluded 误调拒执行 ----------

async def test_turn_excluded_rejects_execution():
    """one visibility = one permission：轮内被裁工具误调 → 拒绝执行。"""
    runner = FCToolRunner(tool_manager=object())
    runner.turn_excluded = frozenset({"read_uploaded_doc", "storyboard_create_group"})

    # 被裁工具调用 → 拒执行
    res = await runner._dispatch_tool("read_uploaded_doc", {"name": "剧本.md"})
    assert res.success is False
    assert res.error_code == "validation"
    assert "不可用" in res.error or "裁剪" in res.error

    res2 = await runner._dispatch_tool("storyboard_create_group", {"title": "T"})
    assert res2.success is False
    assert res2.error_code == "validation"

    # 未裁工具正常执行（run_subagent 需 launcher，此处只验不被 turn_excluded 拦）
    runner.subagent_launcher = None  # 无 launcher → 另一条错误路径
    res3 = await runner._dispatch_tool("run_subagent", {"task": "T"})
    # run_subagent 不在 turn_excluded → 不走裁剪拒执行分支（走 launcher 缺失分支）
    assert "裁剪" not in (res3.error or "")


# ---------- ⑤ stage 映射缺失 fail-loud ----------

def test_pipeline_stage_kinds_consistency():
    """装载期校验：PIPELINE_STAGE_KINDS 每个成员必须在 _STAGE_TOOLS 有映射。
    （本测试在 import 后运行，若映射缺失则 import 期已 raise ValueError）"""
    for stage in PIPELINE_STAGE_KINDS:
        assert stage in _STAGE_TOOLS, f"{stage} missing from _STAGE_TOOLS"
        assert stage_tools(stage), f"{stage} has empty tool set"


# ---------- ⑥ 路由改造：非法 stage fail-loud ----------

async def test_invalid_stage_fail_loud():
    """run_subagent 带非法 stage → fail-loud 拒收（不静默回落通用委派）。"""
    runner = FCToolRunner(tool_manager=object())
    launched = []

    async def launcher(task, kind="", stage="", current_step="", on_event=None):
        launched.append({"task": task, "stage": stage})
        return "ok"

    runner.subagent_launcher = launcher

    # 非法 stage → 拒收
    res = await runner._dispatch_tool(
        "run_subagent", {"task": "T", "stage": "不存在的阶段"})
    assert res.success is False
    assert res.error_code == "validation"
    assert "PIPELINE_STAGE_KINDS" in res.error or "可委派阶段" in res.error
    assert len(launched) == 0  # launcher 未被调用

    # 合法 stage → 正常委派
    res2 = await runner._dispatch_tool(
        "run_subagent", {"task": "T2", "stage": "script_analyze"})
    assert res2.success is True
    assert len(launched) == 1
    assert launched[0]["stage"] == "script_analyze"
