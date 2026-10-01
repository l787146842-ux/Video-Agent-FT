# -*- coding: utf-8 -*-
"""阶段子代理执行器试点批（2026-09-15，对齐 Flova 章节隔离）契约单测。

钉死：①stage 归一化（试点枚举内原样、未知/空回落通用）；②stage 模式工具面
= 通用白名单去 read_skill（断跨阶段预读通道）；③任务文本带阶段标注行、
通用形态零变化；④_launch_subagent 带 stage 时精准注入该阶段章节全文
（不走 8000 截断）、章节缺失回落截断路径；⑤不带 stage 注入行为与现状
逐字一致（防回归钉）；⑥子会话 meta 记 stage 名（左栏子线程可辨阶段）。

不驱动真实模型循环（monkeypatch handle_message 断言装配契约，
同 test_subagent_run_subagent 口径）。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    MAIN_AGENT_DENY, PIPELINE_STAGE_KINDS, STAGE_TOOL_DENY_EXTRA, SUBAGENT_TOOL_DENY,
    build_subagent_task, child_deny_set, resolve_stage, stage_tools,
)
from src.video_agent.state.manager import StateManager

SKILL = "演示阶段技能"
SHOTS_SECTION = "SECTION_SHOTS_BODY：分镜语法三件套探针"


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


class _FakeSkillDocs:
    """记录 get_skill_doc 是否被调（精准注入时不应触发全文截断路径）。"""

    def __init__(self, content: str = ""):
        self.content = content
        self.calls = 0

    def get_skill_doc(self, slug):
        self.calls += 1
        return {"content": self.content} if self.content else None


def _fake_child(captured: dict):
    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["msg"] = user_message
        captured["ctx"] = context
        return _FakeResp()

    return _fake_handle


# ---------- 纯契约 ----------

def test_resolve_stage_enum_and_fallback():
    # 2026-09-22 批6（Q5，用户裁决）：故事板三阶段在**委派面**合并为
    # storyboard_design（关键元素+分镜+音频一次派完，不再分三趟）。
    # 2026-10-01 媒体生成支（步骤3，用户裁决「一个阶段名」）：原 write_media_prompt
    # 收敛为 media_generate（媒体生成）——Skill 里没有「提示词编写」这个流程节点
    # （<planner> 第 4/5/6 步名字都是「生成」），对齐 Flova 的 <media_generator>。
    assert resolve_stage("script_analyze") == "script_analyze"
    assert resolve_stage("media_generate") == "media_generate"
    assert resolve_stage("storyboard_design") == "storyboard_design"
    assert resolve_stage(" storyboard_design ") == "storyboard_design"
    assert PIPELINE_STAGE_KINDS == frozenset({
        "script_analyze", "storyboard_design", "media_generate",
    })
    # 三个旧原子阶段从**委派面**退役（模型没有猜错空间，2222/Q3b 教训）：
    # 它们仍是能力名（喂 available_tools/lint/音频闸），但不可再作为委派 stage。
    for legacy in ("storyboard_shots", "storyboard_key_elements",
                   "storyboard_audio"):
        assert resolve_stage(legacy) == "", (
            f"{legacy} 仍在委派面——批6 已合并为 storyboard_design（Q5）")
    # 2026-10-01：旧名 write_media_prompt 同批从委派面退役（防回潮钉）
    assert resolve_stage("write_media_prompt") == "", (
        "write_media_prompt 仍在委派面——媒体生成支已收敛为 media_generate")
    # 未知/空 → 回落通用（不阻断委派）
    assert resolve_stage("不存在") == ""
    assert resolve_stage("") == ""


def test_merged_stage_injects_all_three_chapters():
    """批6（Q5）：合并阶段的章节注入 = 三章并集（section_for 多章节拼接）。

    这是「一次派活干完三件事」的物理前提：子代理拿到方法规范的全套。
    同时钉死**能力面**（registry）未动——三个旧能力名仍解析得到章节
    （它们还喂着 lint/音频闸/stage_probes）。
    """
    from src.video_agent.skill_runtime.registry import CAPABILITY_TOOL_STAGES
    assert CAPABILITY_TOOL_STAGES["storyboard_design"] == (
        "storyboard_ke", "storyboard_shot", "storyboard_audio")
    # 能力面三条旧映射逐字保留（不在委派面 ≠ 从能力面删除）
    assert CAPABILITY_TOOL_STAGES["storyboard_key_elements"] == ("storyboard_ke",)
    assert CAPABILITY_TOOL_STAGES["storyboard_shots"] == ("storyboard_shot",)
    assert CAPABILITY_TOOL_STAGES["storyboard_audio"] == ("storyboard_audio",)
    # 合并阶段的工具集 = 三原子阶段并集 ⇒ 一次委派内三件事都落得了账
    # 2026-09-23 批2（Q3）：并入 delete_draft（建错卡可撤销）。
    # 2026-09-23 批10（事故 4444/P1-1）：并入 patch_group（改引用不必删光重建）。
    merged = stage_tools("storyboard_design")
    assert merged == frozenset({
        "storyboard_create_group", "storyboard_delete_group",
        "storyboard_delete_draft", "storyboard_patch_group",
        "storyboard_add_draft", "storyboard_patch_draft"})


def test_merged_stage_card_media_covers_audio_and_video():
    """批6（Q5）：建卡媒体白名单随合并拓宽为 {audio, video}，image 仍拒。

    - audio ← 关键元素阶段的角色音色卡（key_element_audio）；
    - video ← 分镜阶段的 shot 卡（实跑取证：26 次 create_group 全 shot+video）；
    - image 仍归 media_generate（用户 2026-09-21 裁决不变；阶段名于 2026-10-01 收敛）。
    """
    from src.video_agent.core.subagent import stage_card_media
    assert stage_card_media("storyboard_design") == frozenset({"audio", "video"})
    assert "image" not in stage_card_media("storyboard_design"), (
        "image 卡归提示词撰写阶段（2026-09-21 用户裁决），合并不放开跨阶段产物")
    assert stage_card_media("media_generate") == frozenset()  # 未登记=不受限


def test_merged_stage_injection_deduplicates_one_to_many_chapters():
    """**2026-09-25 回归钉**（8888 取证）：一对多章节映射不得把同一段正文注入多次。

    病灶：`SECTION_TAG_STAGES["storyboard_designer"]` 是**一对多**
    → `split_skill_sections` 把同一整段正文写进 storyboard_ke/shot/audio 三个键；
    `SkillEntry.section_for` 逐键取出再 join ⇒ **同一段注入 3 次**。
    实测（AI-短剧一站式生成）：三章各 1784 字、注入 5356 字 = 3.0 倍；D-24 章节
    合并后 **16/16 个 Skill 全部命中**（合并前仅个别包如此）。

    正确的语义：一对多 = **检索**需要（三个 stage 键各自可取到全文），
    不是**注入**需要；拼接时同 body 只出现一次。
    """
    from src.video_agent.skill_runtime import registry as reg
    from src.video_agent.skill_runtime.registry import CAPABILITY_TOOL_STAGES

    injected = reg.tool_sections("AI-短剧一站式生成", "storyboard_design")
    probe = "单 shot 内切镜数量建议"
    assert injected.count(probe) == 1, (
        f"合并阶段的同一段正文被注入 {injected.count(probe)} 次（应 1 次）——"
        "一对多映射的复制语义泄漏进了注入层")
    assert len(CAPABILITY_TOOL_STAGES["storyboard_design"]) == 3, \
        "一对多映射本身应保留（检索面）"
    ke = reg.tool_sections("AI-短剧一站式生成", "storyboard_key_elements")
    shot = reg.tool_sections("AI-短剧一站式生成", "storyboard_shots")
    audio = reg.tool_sections("AI-短剧一站式生成", "storyboard_audio")
    assert ke == shot == audio == injected, (
        "合并形态下三个能力名与合并名应取到同一段正文（存量委派名的兼容面）")


def test_stage_deny_drops_read_skill_only():
    """2026-09-15 1111 批（对齐 dsh inherit∩restrict）：子级面 = 主代理面 − deny。
    stage 追加 deny read_skill（断跨阶段预读）+ 本阶段未声明的委派专属写入工具
    （2026-09-21 批0，事故 2222/Q5）；四条硬约束两面均 deny；
    本阶段落点工具（script_analysis_report 等）不在 deny ⇒ 子代理拿得到。"""
    # 2026-09-21 批0：带 stage 的子级额外 deny 的 = read_skill + 本阶段未声明的
    # MAIN_AGENT_DENY 工具（交互类 confirm/media_to_chat 无阶段认领，恒 deny）。
    assert child_deny_set("media_generate") == (
        SUBAGENT_TOOL_DENY | STAGE_TOOL_DENY_EXTRA
        | (MAIN_AGENT_DENY - stage_tools("media_generate")))
    # 通用委派（无 stage）不并入 MAIN_AGENT_DENY：无阶段即无阶段边界
    assert child_deny_set("") == SUBAGENT_TOOL_DENY
    assert child_deny_set("未知阶段") == SUBAGENT_TOOL_DENY
    for deny in (child_deny_set(""), child_deny_set("media_generate")):
        assert "run_subagent" in deny            # 防递归
        assert "image_generate" in deny and "generate_video" in deny  # 花钱留主线程
        assert "workflow_pause" in deny          # 子级不确认
    # 阶段落点工具必须授予子代理（1111 实证 script_analysis_report 未授予断链）
    assert "script_analysis_report" not in child_deny_set("script_analyze")
    # 本阶段**声明**的工具必须授予
    assert "storyboard_add_draft" not in child_deny_set("media_generate")
    assert "storyboard_patch_draft" not in child_deny_set("media_generate")
    # 未声明的则收走：media_generate 不建组（提示词写进既有草稿卡）
    assert "storyboard_create_group" in child_deny_set("media_generate")
    # 2026-09-22 批6（Q5）：合并阶段持有三原子阶段工具并集 ⇒ 建组/建卡/改卡
    # 三件事在一次委派内全拿得到（此前分三趟派，工具面也分三份）。
    # 2026-09-23 批2（Q3）：delete_draft 一并授予（建错卡可撤销）。
    # 2026-09-23 批10（事故 4444/P1-1）：patch_group 一并授予（改引用不必删光重建）。
    merged_deny = child_deny_set("storyboard_design")
    for t in ("storyboard_create_group", "storyboard_delete_group",
              "storyboard_delete_draft", "storyboard_patch_group",
              "storyboard_add_draft", "storyboard_patch_draft"):
        assert t not in merged_deny, f"合并阶段断链：{t} 被 deny"
    # 交互类工具（面向用户动作）无任何阶段认领 → 带 stage 一律 deny
    assert "storyboard_confirm_draft" in merged_deny
    assert "storyboard_media_to_chat" in merged_deny


def test_build_subagent_task_stage_header():
    msg = build_subagent_task("拆解剧本为分镜", stage="media_generate")
    # 2026-09-21 批I（事故 4444/Q6①）：展示标签口径 = 英文 tag 直译
    # 2026-10-01 媒体生成支（步骤3）：阶段展示名 = 「媒体生成」（旧「提示词编写」退役，
    # 理由见 registry.STAGE_LABELS 注释：Skill 里没有该流程节点）
    assert "本次委派阶段：媒体生成" in msg             # STAGE_LABELS 展示标签
    # P1-D/R3（2026-09-16）：阶段标注只留事实行，旧解释性括号措辞退役
    assert "章节即产出规范的全部依据" not in msg
    assert "（系统已注入该阶段 Skill 章节全文" not in msg
    # 定位语保留「方法参考」（措辞唯一源 = subagent.md DELEGATION_CONTEXT）；
    # 2026-09-17 裁决（desc 零引导）：平台引导子句退役，产出形态归 Skill 章节
    assert "方法参考" in msg
    assert "不得照抄章节字段小标题或清单骨架" not in msg
    assert "消化进你自己的产出内容" not in msg
    # 旧事实错误子句退役（工作台状态实为经读工具按需获取）
    assert "你能看到与主代理相同的工作台状态" not in msg
    # 2026-09-22 批5（Q3，用户裁决）：四行汇报格式**退役**——它与
    # structured_output 打卡四槽（created/modified/removed/unfinished）是
    # 同一契约的第二份事实源（P1），且实跑证明子代理既打卡又在正文复述一遍。
    # 完工汇报的唯一家 = prompts/shared/structured_output.md::BRIEF（随任务下发）。
    assert "完成后用以下格式汇报：" not in msg, \
        "四行汇报格式复活——完工汇报唯一家是 structured_output BRIEF（Q3 批5）"
    for line in ("已创建：[类别] N 组（ID 列表）",
                 "已修改：[类别] M 处",
                 "已移除：[类别] K 处",
                 "未完成：[事项清单]（无则写空）"):
        assert line not in msg, f"重复契约行复活：{line}"
    assert msg.rstrip().endswith("拆解剧本为分镜")
    # 通用形态零变化：无阶段标注行
    plain = build_subagent_task("拆解剧本为分镜")
    assert "本次委派阶段" not in plain
    assert "被委派的子代理" in plain            # 固定范围声明仍在
    assert "章节即产出规范的全部依据" not in plain


def test_staged_empty_task_gets_platform_goal():
    """2026-09-22 批5（Q3）：带 stage 且 task 空 → 目标行由平台生成。

    这是「把劝告下降成结构」的落点：调用方没有槽位可填 ⇒ 复述通道关闭
    （此前 task 必填，模型必须填坑，复述成了结构必然）。
    """
    msg = build_subagent_task("", stage="script_analyze")
    assert "===== 本次委派目标 =====" in msg
    assert "执行所选 Skill 的「素材分析」章节" in msg
    # 2026-09-23 批7（D-7）：平台目标行**不再**写「完成本阶段全部产出」——
    # 那句与 Skill <planner> 的「每阶段完成后暂停、绝不一口气输出全部步骤」
    # 直接矛盾（散文说逐步、平台说做完全部），是 2222 越步的结构诱因。
    # 流程控制源回归 Skill 散文；步骤节奏由主代理 current_step 下发。
    assert "全部产出" not in msg, "平台目标行不得与 Skill 暂停散文打架"
    # 平台目标行确实在目标区（不是落在声明里）
    assert msg.split("===== 本次委派目标 =====")[-1].strip().startswith(
        "执行所选 Skill 的「素材分析」章节")


def test_current_step_annotation_rendered():
    """批7（D-7）：主代理下发的「本次步骤」必须出现在任务书里。"""
    msg = build_subagent_task(
        "", stage="media_generate", current_step="第 4 步：为角色写图像提示词")
    assert "本次步骤：第 4 步：为角色写图像提示词" in msg


def test_current_step_absent_renders_no_empty_line():
    """未下发步骤时不出空标注行（不留「本次步骤：」空壳）。"""
    msg = build_subagent_task("", stage="media_generate")
    assert "本次步骤" not in msg


def test_staged_supplement_still_accepted():
    """补充信息仍可用：task 非空时拼在平台目标行之后（只该写子代理读不到的）。"""
    msg = build_subagent_task("用户新确认：画幅 16:9、中文台词", stage="script_analyze")
    tail = msg.split("===== 本次委派目标 =====")[-1]
    assert "用户新确认：画幅 16:9、中文台词" in tail


def test_generic_delegation_without_task_still_builds():
    """通用委派（无 stage）：task 空也不得崩，且不凭空造目标行。"""
    msg = build_subagent_task("", stage="")
    assert "===== 本次委派目标 =====" in msg
    assert "本次委派阶段" not in msg


# ---------- _launch_subagent 装配 ----------

async def test_launch_stage_injects_section_precisely(svc, monkeypatch):
    """带 stage：精准注入该阶段章节全文（不截断、不走 get_skill_doc 全文路径）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    seen = {}
    monkeypatch.setattr(
        pmod, "tool_sections",
        lambda skill, tool: seen.update(skill=skill, tool=tool) or SHOTS_SECTION)
    sd = _FakeSkillDocs(content="X" * 9000)  # 若走截断路径必出现 9000 字全文
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="media_generate")

    assert seen == {"skill": SKILL, "tool": "media_generate"}
    msg = captured["msg"]
    assert SHOTS_SECTION in msg                       # 章节全文在场
    assert f"注入 Skill 章节（{SKILL} · media_generate）" in msg
    assert "本次委派阶段：媒体生成" in msg               # 阶段标注行（批I 直译口径）
    assert sd.calls == 0                              # 未走全文截断回落
    assert "章节内容截断" not in msg
    # 工具面 deny + 子会话 meta 记 stage
    assert captured["ctx"].subagent_deny == child_deny_set("media_generate")
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") \
        == "stage:media_generate"


async def test_launch_stage_missing_section_falls_back(svc, monkeypatch):
    """Skill 无该阶段章节：回落现行全文 8000 截断路径（委派不阻断）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    monkeypatch.setattr(pmod, "tool_sections", lambda skill, tool: "")
    sd = _FakeSkillDocs(content="Y" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="media_generate")
    assert sd.calls == 1
    assert "章节内容截断" in captured["msg"]


async def test_launch_without_stage_keeps_current_behavior(svc, monkeypatch):
    """防回归钉：不带 stage（含未知 stage）注入行为与现状逐字一致——
    全文前 8000 截断、通用白名单、无阶段标注、meta 记 general。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))

    def _boom(skill, tool):
        raise AssertionError("通用委派不应触发阶段章节取读")

    monkeypatch.setattr(pmod, "tool_sections", _boom)
    sd = _FakeSkillDocs(content="Z" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "自由任务", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="不存在的阶段")
    msg = captured["msg"]
    assert sd.calls == 1
    assert f"注入 Skill 章节（{SKILL}）" in msg       # 现状标注（无 · stage 后缀）
    assert "章节内容截断" in msg
    assert "本次委派阶段" not in msg
    assert captured["ctx"].subagent_deny == SUBAGENT_TOOL_DENY
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") == "general"
