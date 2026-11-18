# -*- coding: utf-8 -*-
"""阶段子代理契约单测（2026-11-11 通用 skill 口径）。

钉死：①stage 归一化（试点枚举内原样、未知/空回落通用）；②stage 模式工具面
= 通用白名单（read_skill 已解禁，分册由子代理自读）；③任务文本带阶段标注行、
通用形态零变化；④_launch_subagent 带 stage 时注入 Skill 主文档全文
（不走 8000 截断），stage 不再切章节；⑤不带 stage 注入行为与现状
逐字一致（防回归钉）；⑥子会话 meta 记 stage 名（左栏子线程可辨阶段）。

不驱动真实模型循环（monkeypatch handle_message 断言装配契约，
同 test_subagent_run_subagent 口径）。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    PIPELINE_STAGE_KINDS, SUBAGENT_TOOL_DENY,
    build_subagent_task, child_deny_set, resolve_stage,
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
    """记录 get_skill_doc 是否被调（主文档全文注入路径）。"""

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


def test_merged_stage_keeps_three_chapter_mapping():
    """批6（Q5）：合并阶段保留三章映射（section_for 多章节拼接）。

    2026-11-11 通用化后子代理拿主文档全文，不再按 stage 切章节；
    本用例只钉死**能力面**（registry）映射未漂移——三个旧能力名仍解析得到章节
    （它们还喂着 lint/音频闸/stage_probes）。
    """
    from src.video_agent.skill_runtime.registry import CAPABILITY_TOOL_STAGES
    assert CAPABILITY_TOOL_STAGES["storyboard_design"] == (
        "storyboard_ke", "storyboard_shot", "storyboard_audio")
    # 能力面三条旧映射逐字保留（不在委派面 ≠ 从能力面删除）
    assert CAPABILITY_TOOL_STAGES["storyboard_key_elements"] == ("storyboard_ke",)
    assert CAPABILITY_TOOL_STAGES["storyboard_shots"] == ("storyboard_shot",)
    assert CAPABILITY_TOOL_STAGES["storyboard_audio"] == ("storyboard_audio",)
    # 2026-11-12 宽权限批：阶段工具集不再驱动委派面；能力映射保留供
    # lint/stage_probes 旧探针读取，行为已不消费。


def test_merged_stage_card_media_only_voice_card():
    """建卡媒体白名单：合并阶段只留 {audio}（= 角色音色卡），image/video 均拒。

    - audio ← 关键元素阶段的角色音色卡（key_element_audio）；
    - video 曾于批6（Q5）随合并拓入（实跑取证 26 次 create_group 全 shot+video），
      2026-10-21 用户裁决移除：对齐 2026-09-25 裁决④字面「故事板设计阶段，
      是不能建卡的，除了关键元素的人物音色卡」——分镜视频壳卡归媒体生成阶段；
    - image 仍归 media_generate（用户 2026-09-21 裁决不变；阶段名于 2026-10-01 收敛）。
    """
    from src.video_agent.core.subagent import stage_card_media
    assert stage_card_media("storyboard_design") == frozenset({"audio"})
    assert "image" not in stage_card_media("storyboard_design"), (
        "image 卡归提示词撰写阶段（2026-09-21 用户裁决），合并不放开跨阶段产物")
    assert "video" not in stage_card_media("storyboard_design"), (
        "分镜视频壳卡归媒体生成阶段（2026-10-21 用户裁决）")
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
    # 探针取「二、项目结构规划」正文里的独有短语（Flova 六节骨架下该节一对多
    # 覆盖 storyboard_ke/shot/audio 三键）。
    probe = "每个 shot 是对应序列下的一个分组"
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


def test_registry_full_content_contains_all_generic_sections():
    """通用口径：注册内容是完整主文档，六节标题齐全，且无旧标签。"""
    from src.video_agent.skill_runtime import registry as reg

    entry = reg.resolve_entry("AI-短剧一站式生成")
    assert entry is not None
    for mark in ("## 一、目标、输入与交付", "## 二、项目结构规划", "## 三、制片规格",
                 "## 四、创作流程规划", "## 五、专业创作方法", "## 六、Reference 路由"):
        assert mark in entry.content, f"缺少六节骨架标题：{mark}"
    assert "<planner>" not in entry.content


def test_child_deny_is_safety_only():
    """2026-11-12 宽权限批：stage 不再裁剪工具面；子级只剩安全 deny。"""
    assert child_deny_set("") == SUBAGENT_TOOL_DENY
    assert child_deny_set("media_generate") == SUBAGENT_TOOL_DENY
    assert child_deny_set("未知阶段") == SUBAGENT_TOOL_DENY
    for deny in (child_deny_set(""), child_deny_set("media_generate")):
        assert "run_subagent" in deny            # 防递归
        assert "image_generate" in deny and "generate_video" in deny  # 花钱留主线程
        assert "workflow_pause" in deny          # 子级不确认
        assert "video_assembler" in deny         # 成片导出留主线程
        assert "storyboard_confirm_draft" in deny
        assert "storyboard_media_to_chat" in deny
    # 所有创作/执行工具都不再被阶段 deny
    for t in ("script_analysis_report", "storyboard_create_group",
              "storyboard_delete_group", "storyboard_delete_draft",
              "storyboard_patch_group", "storyboard_add_draft",
              "storyboard_patch_draft", "read_skill", "read_file"):
        assert t not in child_deny_set("media_generate"), f"{t} 不应被阶段 deny"


def test_build_subagent_task_stage_header():
    msg = build_subagent_task("拆解剧本为分镜", stage="media_generate")
    # 2026-09-21 批I（事故 4444/Q6①）：展示标签口径 = 英文 tag 直译
    # 2026-10-01 媒体生成支（步骤3）：阶段展示名 = 「媒体生成」（旧「提示词编写」退役，
    # 理由见 registry.STAGE_LABELS 注释：Skill 里没有该流程节点）
    assert "本次委派阶段：媒体生成" in msg             # STAGE_LABELS 展示标签
    # P1-D/R3（2026-09-16）：阶段标注只留事实行，旧解释性括号措辞退役
    assert "章节即产出规范的全部依据" not in msg
    assert "（系统已注入该阶段 Skill 章节全文" not in msg
    # 2026-11-12 dsh 对齐：技能内容不自动注入，由主代理在 task 里提供
    assert "技能内容不自动注入" in msg
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

async def test_launch_stage_does_not_inject_skill_doc(svc, monkeypatch):
    """dsh 口径：带 stage 也不自动注入 Skill 主文档；主代理在 task 里写。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    sd = _FakeSkillDocs(content="# 主文档\n\n## 制作流程\n" + "X" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="media_generate")

    msg = captured["msg"]
    assert sd.calls == 0
    assert "Skill 主文档" not in msg
    assert "## 制作流程" not in msg
    assert "本次委派阶段：媒体生成" in msg
    assert captured["ctx"].subagent_deny == child_deny_set("media_generate")
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") \
        == "stage:media_generate"


async def test_launch_oversized_doc_is_not_read(svc, monkeypatch):
    """主文档再长也不自动读取/注入；子代理拿到的只有 task。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    sd = _FakeSkillDocs(content="Y" * 25000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="media_generate")
    msg = captured["msg"]
    assert sd.calls == 0
    assert "Y" * 100 not in msg
    assert len(msg) < 20000


async def test_launch_without_stage_does_not_inject_doc(svc, monkeypatch):
    """不带 stage（含未知 stage）：同样不自动注入主文档。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    sd = _FakeSkillDocs(content="# 主文档\n\n## 制作流程\n" + "Z" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "自由任务", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="不存在的阶段")
    msg = captured["msg"]
    assert sd.calls == 0
    assert "Skill 主文档" not in msg
    assert "本次委派阶段" not in msg
    assert captured["ctx"].subagent_deny == SUBAGENT_TOOL_DENY
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") == "general"
