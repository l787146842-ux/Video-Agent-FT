# -*- coding: utf-8 -*-
"""888 项目九项反馈修复回归：时长补全、盲捡收敛、概述裁剪、铁律措辞、
流式逐条落盘、实时上下文用量。"""
import pytest

from src.video_agent.core import prompt_gates, spec_rules
from src.video_agent.core.live_metrics import get_live_context, record_live_context
from src.video_agent.core.action_executor import StateOperationExecutor


# ---------- item 6：分镜提示词时长客观补全 ----------

def test_autofill_shot_duration_appends_when_missing():
    group = {"id": "shot-1", "duration": "20s"}
    # 时长补印随 require_duration 开关（S1：默认关，声明开启才补）
    out = prompt_gates.autofill_shot_duration(
        "镜头画面描述，无字幕。", "shot", group,
        rules={"require_duration": True},
    )
    assert out.startswith("镜头画面描述，无字幕。")
    assert "镜头总时长：20s" in out


def test_autofill_shot_duration_idempotent():
    group = {"id": "shot-1", "duration": "20s"}
    prompt = "镜头总时长：20秒。画面描述。"
    assert prompt_gates.autofill_shot_duration(prompt, "shot", group) == prompt


def test_autofill_shot_duration_noop_for_key_element():
    group = {"id": "ke-1", "duration": "20s"}
    assert prompt_gates.autofill_shot_duration("描述", "keyElement", group) == "描述"


def test_executor_shot_prompt_missing_duration_passes_gate(tmp_path):
    """888 现场：12 条分镜提示词全因缺时长被拒 → 零进展熔断。
    现在用分镜组 duration 客观补印后通过结构闸并写入。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["shots"] = [{
        "id": "shot-1", "title": "镜头1", "duration": "20s",
        "drafts": [{"id": "draft-1", "prompt": "", "mediaType": "video"}],
    }]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.gate_rules = {"require_duration": True}  # 显式声明时长闸（S1：默认关）
    # 提示词满足其余硬条款（长度/字幕/音频/镜头），唯独不写时长
    prompt = (
        "中景缓慢推入，失重的白色球形舱内，程心与AA从冬眠中醒来，"
        "窗外木星云带旋转，光影冷峻。无字幕（no subtitles）。"
        "{对话：掩体没用了。} <轻微机械声> (低沉氛围音乐)"
    )
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": prompt},
    }])
    assert applied == 1
    written = svc.state_dict["shots"][0]["drafts"][0]["prompt"]
    assert written.startswith(prompt)
    assert "镜头总时长：20s" in written


# ---------- item 6：add_draft 盲捡收敛 ----------

def test_add_draft_rejects_blind_pickup_with_many_groups(tmp_path):
    """888 现场：回退第一个分组把 8 张卡全污染进程心组。
    现在多分组且 label 无线索时拒绝执行，回喂模型纠正。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "", "drafts": []},
        {"id": "ke-2", "title": "罗辑", "desc": "", "drafts": []},
    ]
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "???", "prompt": "无归属提示词", "mediaType": "image"}},
    ])
    assert applied == 0
    assert all(not g["drafts"] for g in svc.state_dict["keyElements"])


def test_add_draft_single_group_fallback_still_works(tmp_path):
    """类别下仅一个分组时回落无歧义，保留原有兜底能力。"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "程心", "desc": "", "drafts": []},
    ]
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([
        {"action": "add_draft", "group_id": "current",
         "draft": {"label": "???", "prompt": "唯一分组提示词", "mediaType": "image"}},
    ])
    assert applied == 1
    assert len(svc.state_dict["keyElements"][0]["drafts"]) == 1


# ---------- item 8：分镜概述裁剪 ----------

def test_shot_rough_desc_clamped(tmp_path):
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["shots"] = []
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([{
        "action": "add_group", "group_type": "shot", "title": "镜头1",
        "roughDesc": "Shot1 细节" * 100, "duration": "20s",
    }])
    assert applied == 1
    rough = svc.state_dict["shots"][0]["roughDesc"]
    assert len(rough) <= 201 and rough.endswith("…")


# ---------- item 9：执行铁律优先级含制片规格 ----------

def test_iron_rules_priority_mentions_spec_doc():
    state = {"documents": []}
    assert spec_rules.ensure_iron_rules_doc(state) is True
    iron = spec_rules.find_iron_rules_doc(state)
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in iron["content"]
    # 幂等
    assert spec_rules.ensure_iron_rules_doc(state) is False


def test_iron_rules_old_priority_upgraded_in_place():
    """老项目已有铁律文档：仅精确替换旧优先级措辞，其余内容不动。"""
    old = (
        "# 执行铁律（系统约定，按优先级执行：用户指令 > 本文档 > Skill/系统默认）\n\n"
        "0. 执行优先：用户说什么就做什么。\n9. 用户自定义条款：保持原样。\n"
    )
    state = {"documents": [{"name": "执行铁律.md", "content": old}]}
    assert spec_rules.ensure_iron_rules_doc(state) is True
    content = spec_rules.find_iron_rules_doc(state)["content"]
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in content
    assert "用户自定义条款：保持原样" in content
    assert spec_rules.ensure_iron_rules_doc(state) is False


# ---------- item 5：流式逐条落盘 ----------
# test_extract_complete_objects_incremental / test_extract_complete_objects_braces_in_strings /
# test_stream_progressive_applies_in_batches 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._extract_complete_objects / _stream_actions_progressive）不复存在，
# 管线阶段改由通用主路径直走平台工具。


# ---------- item 7：sceneRefs ID 兼容（后端解析链路） ----------

def test_resolve_scene_refs_matches_by_id_and_title():
    """888 现场：sceneRefs 存的是 ke-xxx ID，生视频参考图注入只认标题会全部丢失。"""
    from src.video_agent.state.storyboard_ops import resolve_scene_refs

    state = {"keyElements": [
        {"id": "ke-1", "title": "三维木星", "drafts": [{"imgUrl": "http://x/j.png"}]},
        {"id": "ke-2", "title": "程心", "drafts": [{"imgUrl": "http://x/c.png"}]},
    ]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1", "程心", "ke-404"]}
    refs = resolve_scene_refs(state, group)
    assert [r["url"] for r in refs] == ["http://x/j.png", "http://x/c.png"]


def test_shot_gate_missing_element_images_by_id_ref():
    """引用感知闸机：ID 形式的 sceneRefs 也能正确判定元素图缺失。"""
    state = {"keyElements": [{"id": "ke-1", "title": "木星", "drafts": [{"imgUrl": ""}]}]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1"]}
    assert prompt_gates.shot_references_missing_element_images(state, group=group) is True
    state["keyElements"][0]["drafts"][0]["imgUrl"] = "http://x/a.png"
    assert prompt_gates.shot_references_missing_element_images(state, group=group) is False


# ---------- item 1：实时上下文用量 ----------

def test_live_metrics_record_and_expiry(monkeypatch):
    record_live_context("proj-x", [{"role": "user", "content": "你好" * 100}])
    rec = get_live_context("proj-x")
    assert rec and rec["est_tokens"] > 0
    # 过期回落
    import src.video_agent.core.live_metrics as lm
    monkeypatch.setitem(lm._LIVE, "proj-x", {"est_tokens": 5, "ts": rec["ts"] - 999})
    assert get_live_context("proj-x") is None
    assert get_live_context("") is None


# ============================================================
# 888 事故二轮修复回归（2026-08-10）：@自动补写 / 版本账本统一 /
# 流程事件账本 / 截断禁报成功 / 铁律保护 / 回话模板去矛盾
# ============================================================

# ---------- B3：@引用系统自动补写（确定性任务收归系统） ----------

def test_at_ref_autofill_declared_appends_missing_refs():
    """声明 require_at_ref 的技能：分镜提示词缺 @ 时按 sceneRefs 客观补印。"""
    state = {"keyElements": [
        {"id": "ke-1", "title": "程心"},
        {"id": "ke-2", "title": "AA"},
    ]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1", "ke-2"]}
    out = prompt_gates.autofill_at_refs(
        "中景，程心与AA对话。", "shot", group, state,
        rules={"require_at_ref": True},
    )
    assert "@程心" in out and "@AA" in out


def test_at_ref_autofill_undeclared_noop():
    """未声明 require_at_ref 的 Skill 一律不动（验收跟声明走，换技能不误伤）。"""
    state = {"keyElements": [{"id": "ke-1", "title": "程心"}]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1"]}
    prompt = "中景，程心独行。"
    assert prompt_gates.autofill_at_refs(prompt, "shot", group, state) == prompt
    assert prompt_gates.autofill_at_refs(
        prompt, "shot", group, state, rules={"require_at_ref": False},
    ) == prompt


def test_at_ref_autofill_existing_ref_not_duplicated():
    state = {"keyElements": [{"id": "ke-1", "title": "程心"}]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1"]}
    prompt = "中景，@程心 独行。"
    assert prompt_gates.autofill_at_refs(
        prompt, "shot", group, state, rules={"require_at_ref": True},
    ) == prompt


def test_fc_track_autofills_at_refs(monkeypatch):
    """FC 轨写分镜提示词同样客观补 @（与时长补印同路，防模型绕过执行器
    直接建卡写词时漏 @）。"""
    from src.video_agent.core.fc_tool_runner import FCToolRunner

    runner = FCToolRunner(tool_manager=None)
    state = {
        "keyElements": [{"id": "ke-1", "title": "程心",
                         "drafts": [{"imgUrl": "http://x/c.png"}]}],
        "shots": [{"id": "shot-1", "title": "镜1", "sceneRefs": ["ke-1"],
                   "duration": "10s", "drafts": [{"id": "1-1", "label": "分镜"}]}],
    }
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: state))
    runner._gate_rules = {"require_at_ref": True}
    args = {"draft_id": "1-1", "draft_type": "shot",
            "patch": {"prompt": "中景，程心在走廊独行，冷光。"}}
    runner._prompt_gate("storyboard_patch_draft", args, injected_skill="任意")
    # 补印后的文本必须回写进待写入的 args
    assert "@程心" in args["patch"]["prompt"]


# ---------- B1：版本账本全站统一（重启不断号、双实例同一本账） ----------

def test_board_version_shared_between_instances(tmp_path):
    """888 现场：常驻单例 110 号对任务实例 9 号，正常保存被拒。
    修复后同项目所有实例共享一本账。"""
    from src.video_agent.state.manager import StateManager

    a = StateManager(str(tmp_path / "ws"))
    pid = a.active_project_id
    b = StateManager(str(tmp_path / "ws"))  # 第二个实例（模拟任务注册表路径）
    assert b.active_project_id == pid
    v0 = a.board_version
    a.state_dict["marker"] = 1
    a.save()
    # 同项目另一实例立即看到同一版号（各算各的 bug 已修）
    assert b.board_version == v0 + 1


def test_board_version_persisted_across_reload(tmp_path):
    """版号随项目文件落盘：换实例/重启都从上次的号继续数，不从 0 重数。"""
    from src.video_agent.state.manager import StateManager

    StateManager._board_versions.clear()  # 模拟进程重启，内存账本清空
    a = StateManager(str(tmp_path / "ws"))
    a.state_dict["marker"] = 1
    a.save()
    v = a.board_version
    assert v >= 1
    StateManager._board_versions.clear()  # 再次模拟重启
    b = StateManager(str(tmp_path / "ws"))
    assert b.board_version == v  # 从落盘状态继承，不断号


# ---------- A3：流程事件账本（进度事实可见，截断不得冒充完成） ----------

def test_flow_event_recorded_injected_and_cleared(tmp_path):
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.record_flow_event(
        "storyboard_shots_truncated",
        "上次分镜拆解输出被截断，只写入 4 个，疑似不完整",
    )
    ctx = svc.build_agent_context("all")
    assert "上次分镜拆解输出被截断" in ctx
    # 完整完成后消解
    svc.clear_flow_events("storyboard_shots_truncated")
    assert "上次分镜拆解输出被截断" not in svc.build_agent_context("all")


# test_is_truncated_detects_length_finish / test_split_truncation_marks_incomplete_and_records_event
# 已随任务#36 B5 执行器一步退役删除：被测对象（executors._is_truncated /
# StoryboardShotsTool 截断对账）不复存在。「截断不得冒充完成」的通用事实由
# test_flow_event_recorded_injected_and_cleared（StateManager 流程事件账本）承接钉死。


# ---------- B7：铁律文档保护（模型不得整篇重写） ----------

@pytest.mark.asyncio
async def test_model_cannot_rewrite_iron_rules_doc(monkeypatch, tmp_path):
    """888 现场：模型自作主张重写铁律，可能盖掉用户编辑。修复后写入被拒。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.document_tools import (
        DocumentWriteTool, WriteDocumentInput,
    )

    svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    result = await DocumentWriteTool().aexecute(WriteDocumentInput(
        name="执行铁律.md", content="# 模型自造的铁律\n",
    ))
    assert result.success is False
    assert "不得整篇重写" in str(result.error)


# ---------- A1：回话模板去矛盾（治理台账的可机检项） ----------

def test_feedback_template_no_contradiction():
    """888 病灶一：「请继续完成任务……不要再调用 Tool」自相矛盾逼推理模型
    万字思考反复裁决。模板措辞必须消除该矛盾。"""
    import inspect

    from src.video_agent.core import agent_loop

    src = inspect.getsource(agent_loop)
    assert "不要再调用 Tool" not in src
    assert "不要再输出 continue" not in src


# ---------- B8 豪华版：软参数模型出题 + 点选 + 机械回写 ----------

def test_collect_wizard_renders_skill_dim_candidates(monkeypatch):
    """4444 + 6666 二轮：收集向导软维度来自 Skill 客观提取；候选由模型出题；
    候选不足的维度仍渲染占位卡；硬参数（渠道/分辨率/分镜最大时长）不再出现。"""
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions",
        lambda skill: ["视觉风格", "画幅"],
    )
    state = {
        "usedSkills": ["测试Skill"],
        "interaction": {"spec_soft_candidates": {
            "视觉风格": ["硬核写实科幻", "赛博朋克", "水墨风"],
            "画幅": ["16:9 横屏"],  # 只有 1 个候选 → 不渲染
        }},
    }
    _msg, opts = prompt_gates.spec_collect_card(state)
    style_labels = [o["label"] for o in opts if o["group"] == "视觉风格"]
    assert "视觉风格：硬核写实科幻" in style_labels
    assert "视觉风格：赛博朋克" in style_labels
    # 候选不足的维度仍渲染（占位卡 + 自定义输入），不允许悄悄隐藏
    assert any(o["group"] == "画幅" for o in opts)
    # 平台不预设维度：未声明的维度（旧六维）不出现
    assert not any(o["group"] == "叙事驱动" for o in opts)
    # 硬参数与渠道维度不再出现（6666 二轮：由顶部「全局设置」唯一提供）
    assert not any(o["group"] in ("图片分辨率", "视频分辨率", "分镜最大时长") for o in opts)
    assert not any("渠道" in str(o.get("group") or "") for o in opts)


def test_parse_dim_selections_and_assemble_spec_doc(monkeypatch):
    """4444 方案乙 + 6666 二轮：选择解析 + 系统拼装键值清单；
    规格文档只含 Skill 软维度，不写渠道/分辨率/分镜最大时长。"""
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions",
        lambda skill: ["画幅比例", "目标时长", "影像风格基调", "输出语言"],
    )
    sels = prompt_gates.parse_dim_selections(
        "画幅比例：16:9\n输出语言：中文原声", ["画幅比例", "目标时长", "输出语言"])
    assert sels == {"画幅比例": "16:9", "输出语言": "中文原声"}
    sels.update({"图片分辨率": "2K", "分镜最大时长": "15 秒", "图像生成": "Antigravity CLI auto"})
    doc = prompt_gates.assemble_spec_doc(
        "测试Skill", sels,
        model_filled={"目标时长": "约 90 秒", "影像风格基调": "暗调高对比"},
    )
    assert "- 画幅比例：16:9" in doc
    assert "- 目标时长：约 90 秒" in doc      # 未选维度用模型填值
    assert "- 影像风格基调：暗调高对比" in doc
    assert "- 输出语言：中文原声" in doc
    # 硬参数不再写入规格文档（全局设置唯一提供）
    assert "- 图片分辨率：2K" not in doc
    assert "- 分镜最大时长：15 秒" not in doc
    assert "- 图像生成：Antigravity CLI auto" not in doc
    assert "剧本分析" not in doc and "##" not in doc  # 纯键值清单，无杂项


def test_soft_not_added_on_confirm_intent():
    """不选就放行：纯确认意图不追加软参数行（模型自填）。"""
    content = "- 图片分辨率：2K\n"
    new_content, applied = prompt_gates.apply_spec_param_selections(
        content, "确认成片规格，按流程继续", allow_confirm_intent=True,
    )
    assert "视觉风格" not in new_content
    assert not any("视觉风格" in a for a in applied)


def test_action_alias_normalization_groupid_payload(tmp_path):
    """9999 现场：弱模型把 add_draft 写成 type/groupId/payload 驼峰 schema，
    归一后必须命中分组写入，不再整批「拒绝盲建」。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.core.action_executor import StateOperationExecutor

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    ex = StateOperationExecutor(svc, gate_enabled=False)
    applied = ex.execute([{
        "type": "add_draft",
        "groupId": "ke-1",
        "payload": {"label": "概念图", "mediaType": "image", "prompt": "写实科幻角色图。"},
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][0]["drafts"]


# test_script_analyze_generates_soft_candidates 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors.ScriptAnalyzeTool + exec_spec.run_collect_spec_node 候选落盘）
# 不复存在。平台不再机械出题，规格收集改由模型按 skill_discipline 用 workflow_pause
# 分组向导完成。
