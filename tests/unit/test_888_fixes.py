# -*- coding: utf-8 -*-
"""888 项目九项反馈修复回归：时长补全、盲捡收敛、概述裁剪、铁律措辞、
流式逐条落盘、实时上下文用量。"""
import json

import pytest

from src.video_agent.core import prompt_gates, spec_rules
from src.video_agent.core.live_metrics import get_live_context, record_live_context
from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.skill_runtime import exec_common
from src.video_agent.skill_runtime import exec_spec
from src.video_agent.web import generation as gen_mod


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
    ex = StudioActionExecutor(svc, gate_enabled=True)
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
    ex = StudioActionExecutor(svc, gate_enabled=False)
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
    ex = StudioActionExecutor(svc, gate_enabled=False)
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
    ex = StudioActionExecutor(svc, gate_enabled=False)
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
    assert "用户指令 > 本文档 + 制片规格 > Skill/系统默认" in iron["content"]
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
    assert "用户指令 > 本文档 + 制片规格 > Skill/系统默认" in content
    assert "用户自定义条款：保持原样" in content
    assert spec_rules.ensure_iron_rules_doc(state) is False


# ---------- item 5：流式逐条落盘 ----------

def test_extract_complete_objects_incremental():
    buf = '[{"action":"add_group","title":"A"},{"action":"add_'
    objs, pos = ex_mod._extract_complete_objects(buf, 1)
    assert len(objs) == 1
    assert json.loads(objs[0])["title"] == "A"
    # 第二个对象未闭合：位置停在它的起点，等待增量补齐
    assert buf[pos:].startswith('{"action":"add_')
    objs2, _ = ex_mod._extract_complete_objects(
        buf + 'group","title":"B"}]', pos,
    )
    assert [json.loads(o)["title"] for o in objs2] == ["B"]


def test_extract_complete_objects_braces_in_strings():
    buf = '[{"desc":"含 {花括号} 与 \\"引号\\" 的文本","ok":true}]'
    objs, _ = ex_mod._extract_complete_objects(buf, 1)
    assert len(objs) == 1
    assert json.loads(objs[0])["ok"] is True


@pytest.mark.asyncio
async def test_stream_progressive_applies_in_batches(monkeypatch, tmp_path):
    """流式增量到达即逐批落盘：三个动作分两次吐出，左栏状态随批增长。
    （audit-0819d：纯 JSON 数组流，response_format 参数透传钉死）"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = []
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    chunks = [
        '[{"action":"add_group","group_type":"keyElement","title":"程心"},',
        '{"action":"add_group","group_type":"keyElement","title":"罗辑"},',
        '{"action":"add_group","group_type":"keyElement","title":"二向箔"}]',
    ]
    seen_kwargs = {}

    async def fake_stream(provider, model, messages, *, max_tokens=8192,
                          temperature=0.7, timeout=180, on_delta=None,
                          reasoning_sink=None, thinking_level=None,
                          response_format=None):
        seen_kwargs["response_format"] = response_format
        content = ""
        for c in chunks:
            content += c
            if on_delta:
                await on_delta(c)
        return content, "stop"

    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_stream)

    applied, warnings, content, finish = await ex_mod._stream_actions_progressive(
        "storyboard_key_elements", "技能", "system", "user", svc, "",
        provider="p", model="m", max_tokens=8192, flush_n=2,
    )
    assert applied == 3
    assert finish == "stop"
    # audit-0819d：结构化输出声明必须随流式调用下发
    assert seen_kwargs["response_format"] == {"type": "json_object"}
    titles = [g["title"] for g in svc.state_dict["keyElements"]]
    assert titles == ["程心", "罗辑", "二向箔"]
    assert content.startswith("[")


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


def test_is_truncated_detects_length_finish():
    assert ex_mod._is_truncated("length") is True
    assert ex_mod._is_truncated("max_tokens") is True
    assert ex_mod._is_truncated("stop") is False
    assert ex_mod._is_truncated("") is False


@pytest.mark.asyncio
async def test_split_truncation_marks_incomplete_and_records_event(monkeypatch, tmp_path):
    """888 现场：截断只拆出 4 个却报「重拆完成」。修复后截断不得冒充完成：
    回执带警告 + 流程事件账本记录疑似不完整。"""
    from src.video_agent.skill_runtime.executors import (
        StoryboardShotsTool, StoryboardSplitInput,
    )
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry

    sd.save_skill_doc(
        "截断技能", "# T\n> 调用规则：测试\n<storyboard_shots>\n拆解规范\n</storyboard_shots>\n",
    )
    registry.register_skill("截断技能")

    async def fake_stream(provider, model, messages, *, max_tokens=8192,
                          temperature=0.7, timeout=180, on_delta=None,
                          reasoning_sink=None, thinking_level=None,
                          response_format=None):
        content = ('[{"action":"add_group","group_type":"shot",'
                   '"title":"镜1","duration":"10s","sceneRefs":["s1"]}]')
        if on_delta:
            await on_delta(content)
        return content, "length"  # 撞输出上限被截断（两次都截断才走对账流程）

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["shots"] = []
    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_stream)
    monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("f", "f"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    result = await StoryboardShotsTool().aexecute(
        StoryboardSplitInput(skill_name="截断技能")
    )
    assert result.success  # 部分写入照常落盘不丢
    assert "截断" in result.data["detail"]  # 但回执不得冒充完整
    events = svc.state_dict.get("flowEvents") or []
    assert any("截断" in str(e.get("text") or "") for e in events)
    registry.reset_registry()


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
    from src.video_agent.web.action_executor import StudioActionExecutor

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [{"id": "ke-1", "title": "程心", "drafts": []}]
    ex = StudioActionExecutor(svc, gate_enabled=False)
    applied = ex.execute([{
        "type": "add_draft",
        "groupId": "ke-1",
        "payload": {"label": "概念图", "mediaType": "image", "prompt": "写实科幻角色图。"},
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][0]["drafts"]


@pytest.mark.asyncio
async def test_script_analyze_generates_soft_candidates(monkeypatch, tmp_path):
    """script_analyze 后内层模型按剧本出题软参数候选并落 state；
    校验不过的维度被丢弃。"""
    from src.video_agent.skill_runtime.executors import (
        ScriptAnalyzeTool, ScriptAnalyzeInput,
    )
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry

    sd.save_skill_doc(
        "豪华技能", "# S\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n",
    )
    registry.register_skill("豪华技能")
    monkeypatch.setattr(registry, "skill_flow_enabled", lambda skill, key: True)
    monkeypatch.setattr(registry, "spec_wizard_active", lambda skill: True)
    # 4444：维度来自 Skill 客观提取；测试桩无规格行，用 monkeypatch 注入维度
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions",
        lambda skill: ["视觉风格", "输出语言", "画幅"],
    )

    calls = {"n": 0}

    async def fake_json(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"summary": "太阳系逐渐二维化", "key_points": []}
        return {
            "视觉风格": ["硬核写实科幻", "赛博朋克"],
            "输出语言": ["中文"],          # 只有 1 个候选 → 校验不过丢弃
            "画幅": ["16:9 横屏", "9:16 竖屏"],
        }

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "程心看着二向箔展开。"},
    ]
    monkeypatch.setattr(exec_spec, "_llm_json_call", fake_json)
    monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("f", "f"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    result = await ScriptAnalyzeTool().aexecute(
        ScriptAnalyzeInput(skill_name="豪华技能", doc_name="剧本.md")
    )
    assert result.success
    # 批3 分离：候选出题 = collect_spec 独立节点（runtime 调度）
    await exec_spec.run_collect_spec_node(svc, "豪华技能")
    cands = (svc.state_dict.get("interaction") or {}).get("spec_soft_candidates") or {}
    assert cands.get("视觉风格") == ["硬核写实科幻", "赛博朋克"]
    assert "输出语言" not in cands
    assert cands.get("画幅") == ["16:9 横屏", "9:16 竖屏"]
    registry.reset_registry()
