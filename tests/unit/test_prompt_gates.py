"""提示词结构闸机：校验规则 + FC/文本双轨拦截"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.core.action_executor import StateOperationExecutor

GOOD_SHOT_PROMPT = (
    "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
    "前景飘散的冰晶在冷光中闪烁，整体色调深青克制，Strong chiaroscuro contrast，"
    "<急促的呼吸声与远方空间坍缩的轰鸣>，no music，no subtitles。"
)

# S1：业务闸默认全关，需要结构检查的 Skill 通过 gate_rules/manifest 声明开启；
# 本文件大量用例验证各业务闸的拦截能力，统一用这份显式开启的规则
ALL_GATES_ON = {
    "require_duration": True,
    "require_subtitle": True,
    "require_camera_language": True,
    "require_audio_layer": True,
}


# ---------- 校验规则 ----------

def test_shot_prompt_complete_passes():
    ok, hard, _ = prompt_gates.validate_prompt_write(GOOD_SHOT_PROMPT, "shot")
    assert ok and not hard


def test_shot_prompt_missing_no_subtitles():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体奔跑，空间崩裂，<音效轰鸣>，no music。", "shot",
        rules=ALL_GATES_ON)
    assert not ok
    assert any("字幕" in e for e in hard)


def test_shot_prompt_missing_audio_layer():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体在冰原上奔跑，背景崩裂成平面，光影克制，no subtitles。", "shot",
        rules=ALL_GATES_ON)
    assert not ok
    assert any("音频层" in e for e in hard)


def test_shot_prompt_missing_camera():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "程心怀抱文物奔向舱门，背景冥王星冰原崩裂，<呼吸声与轰鸣>，no music，no subtitles。",
        "shot", rules=ALL_GATES_ON)
    assert not ok
    assert any("镜头语言" in e for e in hard)


def test_shot_prompt_too_short():
    ok, hard, _ = prompt_gates.validate_prompt_write("推入，no subtitles，<音效>", "shot")
    assert not ok
    assert any("过短" in e for e in hard)


def test_shot_prompt_missing_duration():
    """镜头时长强制条款（需声明 require_duration）：未写明本镜头总时长即打回"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体奔跑，空间崩裂，<音效轰鸣>，no music，no subtitles。", "shot",
        rules=ALL_GATES_ON)
    assert not ok
    assert any("时长" in e for e in hard)


def test_business_gates_off_by_default():
    """S1 回归：无声明时业务闸（时长/字幕/音频层/镜头语言）全部不校验，
    引擎不预设任何 Skill 的提示词规范；字数下限与语言闸等客观防护仍在。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体在冰原上奔跑，怀中紧抱文物，背景冥王星冰原崩裂成平面，"
        "前景飘散的冰晶在冷光中闪烁，光影克制，色调深青，整体氛围冷峻肃杀，宿命感强烈而庄重，如史诗末章。", "shot")
    assert ok and not hard


def test_shot_prompt_with_duration_passes():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "镜头总时长：12秒。缓慢推入中景，主角在冰原上奔跑，怀中紧抱文物，背景崩裂成平面，"
        "光影克制，色调深青，<音效轰鸣>，no music，no subtitles。", "shot")
    assert ok and not hard


def test_shot_prompt_duration_variants_pass():
    """时长语义解析（P1-4）：15s / 15 秒 / duration: 15 seconds 均视为已写明时长"""
    base = (
        "缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原在冷光中缓缓崩裂成"
        "二维平面，前景冰晶闪烁，整体色调深青克制，<急促呼吸声与远处坍缩轰鸣>，"
        "no music，no subtitles。"
    )
    for duration_clause in (
        "镜头总时长：15s",
        "镜头总时长 15 秒",
        "15秒",
        "duration: 15 seconds",
    ):
        ok, hard, _ = prompt_gates.validate_prompt_write(
            f"{base} {duration_clause}", "shot")
        assert ok and not hard, f"应通过: {duration_clause}"


def test_shot_prompt_subtitle_synonyms_pass():
    """字幕约束同义词（P1-4）：无字幕/不加字幕/后期加字幕 均合法"""
    base = (
        "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原"
        "崩裂成二维平面，前景冰晶在冷光中闪烁，色调深青克制，<急促呼吸声与轰鸣>，"
        "no music。"
    )
    for negation in ("无字幕", "不加字幕", "后期加字幕", "字幕后期添加", "no subtitles"):
        ok, hard, _ = prompt_gates.validate_prompt_write(f"{base} {negation}", "shot")
        assert ok and not hard, f"应通过: {negation}"


def test_key_element_prompt_min_len():
    ok, hard, _ = prompt_gates.validate_prompt_write("老者", "keyElement")
    assert not ok and any("过短" in e for e in hard)
    ok2, hard2, _ = prompt_gates.validate_prompt_write(
        "白发老者罗辑，地球文明最后的守墓人，身穿深色厚重古典大衣，手持拐杖，"
        "神情平静从容，冷峻光影下的宿命感。", "keyElement")
    assert ok2 and not hard2


def test_audio_kind_and_empty_prompt_skip():
    assert prompt_gates.validate_prompt_write("随便", "audio")[0] is True
    assert prompt_gates.validate_prompt_write("", "shot")[0] is True


# 8888 项目真实事故样本：结构齐全但正文整段英文（违反 Skill 最高优先级中文条款）
ENGLISH_SHOT_PROMPT = (
    "Camera: Slow push-in from wide cabin view to medium close-up on Cheng Xin and AA. "
    "Subject: Cheng Xin and AA float in zero gravity, turning anxiously towards a holographic screen. "
    "Space: Spherical white spacecraft bridge with massive observation window showing Jupiter's storm bands. "
    "Audio: AA says in Chinese: {为什么木星城还没躲进掩体？} <low ambient hum of life support> "
    "no music, no subtitles."
)


def test_english_body_rejected_shot():
    ok, hard, _ = prompt_gates.validate_prompt_write(ENGLISH_SHOT_PROMPT, "shot")
    assert not ok
    assert any("中文" in e for e in hard)


def test_english_body_rejected_key_element():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "An elderly man with white beard, wearing a dark heavy classical coat, holding a cane, "
        "calm expression, strong chiaroscuro contrast, destined aura.", "keyElement")
    assert not ok
    assert any("中文" in e for e in hard)


def test_chinese_body_with_english_terms_passes():
    # 中文正文 + 英文专业术语/包装符是合规形态（GOOD_SHOT_PROMPT 即此形态）
    ok, _, _ = prompt_gates.validate_prompt_write(GOOD_SHOT_PROMPT, "shot")
    assert ok


def test_voice_reference_soft_warning():
    state = {"assets": [{"type": "audio", "url": "/files/voice.mp3"}], "audioItems": []}
    prompt = "中景，程心喊道{我们必须立刻启动曲率引擎}，<舱门闭合声>，no music，no subtitles。"
    _, _, soft = prompt_gates.validate_prompt_write(prompt, "shot", state)
    assert soft and "音色参考" in soft[0]
    # 已说明音色参考 → 无软提醒
    prompt_ok = prompt + " 音色参考：程心使用 voice.mp3"
    assert not prompt_gates.validate_prompt_write(prompt_ok, "shot", state)[2]


# ---------- 文本轨拦截（update_draft / add_draft / add_group） ----------

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


def _seed_shot(svc):
    svc.state_dict["shots"] = [{
        "id": "shot-test", "title": "Shot_测试", "duration": "10s",
        "sceneRefs": ["Element_测试"],
        "drafts": [{"id": "draft-1", "label": "分镜 1", "mediaType": "video", "prompt": ""}],
    }]


def test_executor_rejects_bad_update_draft_by_default(svc):
    _seed_shot(svc)
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": "太短了"},
    }])
    # 决策 D（质量优先）：Skill 流程激活且未坚持 → 写入前拒绝
    assert applied == 0
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == ""
    assert ex.gate_rejections


def test_executor_user_override_writes_bad_prompt_with_warning(svc):
    _seed_shot(svc)
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.gate_rules = dict(ALL_GATES_ON)  # 显式声明业务闸（S1：默认全关）
    ex.gate_override = True  # 用户坚持：照常写入 + 警告
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": "太短了"},
    }])
    assert applied == 1
    # 时长客观补印（888 事故）：漏写镜头时长时自动追加分镜组 duration，写入文本以原文开头
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"].startswith("太短了")
    assert "镜头总时长" in svc.state_dict["shots"][0]["drafts"][0]["prompt"]
    assert ex.gate_warnings and "警告" in ex.gate_warnings[0]


def test_executor_passes_good_update_draft(svc):
    _seed_shot(svc)
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }])
    assert applied == 1
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == GOOD_SHOT_PROMPT
    # 时长参数同步：写提示词时把分镜结构时长（10s）补印到草稿时长参数
    assert svc.state_dict["shots"][0]["drafts"][0]["duration"] == "10s"


def test_executor_gate_disabled_allows_everything(svc):
    _seed_shot(svc)
    ex = StateOperationExecutor(svc)  # gate_enabled 默认 False
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": "太短了"},
    }])
    assert applied == 1


def test_executor_add_group_rejects_bad_inline_draft(svc):
    # 预置规格文档：否则会被规格前置闸机整体拦下（见下方专项用例）
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "shot", "title": "Shot_新",
        "draft": {"label": "分镜", "prompt": "敷衍短句"},
    }])
    # 分组创建成功；结构阶段内联提示词被剥离，草稿卡保留为空（v3：只建骨架）
    assert applied == 1
    group = svc.state_dict["shots"][-1]
    assert group["title"] == "Shot_新"
    assert len(group["drafts"]) == 1
    assert group["drafts"][0]["prompt"] == ""
    assert ex.prompts_stripped == 1


# ---------- 规格文档前置闸机（666 项目事故：跳过 制片规格.md 直建故事板） ----------

def test_has_spec_document_variants():
    assert prompt_gates.has_spec_document({"documents": []}) is False
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "制片规格.md", "content": "正文"}]}) is True
    # 大小写/空格/连字符不敏感
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "final video-spec", "content": "正文"}]}) is True
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "制作规格", "content": "正文"}]}) is True
    # 空文档不算数（防绕过）
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "制片规格.md", "content": "  "}]}) is False


def test_executor_spec_gate_warns_and_allows_add_group(svc, monkeypatch):
    """814Gb：文本轨规格前置与 FC 轨对齐——executor 不再向用户追加 ⚠，
    执行侧强制由编排器承担。"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(
        registry, "skill_flow_enabled", lambda skill, key: key == "spec_gate",
    )
    before = len(svc.state_dict.get("keyElements") or [])
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.skill_name = "测试流程Skill"
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    assert applied == 1
    assert len(svc.state_dict.get("keyElements") or []) == before + 1
    # 用户侧静默：规格前置不再进 gate_warnings（不展示 ⚠）
    assert not any("规格文档" in w for w in ex.gate_warnings)


def test_executor_spec_gate_allows_after_spec_written(svc):
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    assert applied == 1


def test_executor_spec_gate_inactive_without_skill(svc):
    ex = StateOperationExecutor(svc)  # gate_enabled=False → 日常微调不受影响
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    assert applied == 1


def test_fc_flow_gate_warns_and_allows_create_group_without_spec(monkeypatch):
    """814G5/0818：_flow_gate 不向用户追加 ⚠、不硬拦（恒 None）；
    越阶顺序控制已归编排器（旧门禁链退役）。"""
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {"documents": []}))
    err = runner._flow_gate("storyboard_create_group", injected_skill="剧本生视频（需上传剧本）")
    assert err is None
    assert not runner.gate_warnings  # 814G5：不再向用户追加警告


def test_fc_flow_gate_passes_with_spec(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"documents": [{"name": "制片规格.md", "content": "正文"}]}))
    assert runner._flow_gate("storyboard_create_group", injected_skill="任意 Skill") is None


# ---------- 结构纯净闸 + 故事板待确认窗口（888 项目事故：步骤3+4 合并且虚报） ----------

def test_fc_strips_structure_prompt_on_first_batch():
    """FC 轨：首次搭建批次剥离内联详细提示词（P0-2）"""
    runner = FCToolRunner(tool_manager=None)
    args = {"group_type": "keyElement", "title": "Element_测试",
            "draft": {"label": "概念图", "prompt": "x" * 100}}
    assert runner._strip_structure_prompt(
        "storyboard_create_group", args, injected_skill="任意 Skill") is True
    assert args["draft"]["prompt"] == ""
    assert runner._strip_structure_prompt(
        "storyboard_create_group", {"draft": {"prompt": "x" * 100}}, injected_skill="",
    ) is False
    assert runner._strip_structure_prompt(
        "storyboard_create_group", {"draft": {"prompt": "x" * 100}}, injected_skill="任意 Skill",
    ) is True


def test_executor_structure_strips_inline_prompt_on_first_batch(svc):
    """文本轨：首次搭建批次 add_group 内联提示词被剥离，分组照常建立"""
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    ex = StateOperationExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
        "draft": {"label": "概念图", "prompt": "y" * 120},
    }])
    assert applied == 1
    group = svc.state_dict["keyElements"][-1]
    assert group["title"] == "Element_测试"
    assert group["drafts"][0]["prompt"] == ""  # 提示词由 write_media_prompt 阶段编写
    assert ex.prompts_stripped == 1


def test_executor_pending_window_does_not_block_prompt_write(svc):
    """步骤3→步骤4 分界：即使处于待确认窗口，提示词也照常写入（执行优先）"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "规格正文"}]
    _seed_shot(svc)
    ex = StateOperationExecutor(svc, gate_enabled=True)
    # 同批：建结构 + 写提示词 → 两者都执行（步骤3与4可合并）
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "Element_新"},
        {"action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
         "patch": {"prompt": GOOD_SHOT_PROMPT}},
    ])
    assert applied == 2
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == GOOD_SHOT_PROMPT
    # 即便手动置位待确认窗口，写入也照常放行
    svc.state_dict.setdefault("interaction", {})["storyboard_pending"] = True
    assert ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }]) == 1
    # 用户回应到达 → 解除待确认标记
    _consume_pending_confirmation(svc, "确认")
    assert svc.state_dict["interaction"].get("storyboard_pending") is False


def test_fc_pending_window_rejects_bad_prompt(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"interaction": {"storyboard_pending": True}}))
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "keyElement", "patch": {"prompt": "x" * 80}},
        injected_skill="任意 Skill",
    )
    assert err is not None  # 决策 D：硬性条款未通过 → 拒绝
    # 用户坚持 → 放行并警告
    runner2 = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"interaction": {"storyboard_pending": True}}))
    runner2.gate_override = True
    err2 = runner2._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "keyElement", "patch": {"prompt": "x" * 80}},
        injected_skill="任意 Skill",
    )
    assert err2 is None
    assert runner2.gate_warnings


# ---------- FC 轨拦截 ----------

def test_fc_gate_rejects_bad_prompt(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="剧本生视频（需上传剧本）",
    )
    assert err is not None and "过短" in err


def test_fc_gate_passes_without_skill(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    assert runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="",
    ) is None


def test_fc_gate_passes_good_prompt(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    assert runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT_PROMPT}},
        injected_skill="任意 Skill",
    ) is None


# ---------- Skill 可配置闸机规则（W20） ----------


def test_parse_gate_rules_valid():
    content = (
        "```json gate_rules\n"
        '{"shot_min_chars": 200, "require_duration": false, '
        '"subtitle_synonyms": ["不要字幕"]}\n'
        "```"
    )
    rules = prompt_gates.parse_gate_rules(content)
    assert rules["shot_min_chars"] == 200
    assert rules["require_duration"] is False
    assert "不要字幕" in rules["subtitle_synonyms"]


def test_parse_gate_rules_invalid_falls_back():
    assert prompt_gates.parse_gate_rules("") == prompt_gates._DEFAULT_GATE_RULES
    assert prompt_gates.parse_gate_rules(
        "```json gate_rules\nnot-json\n```") == prompt_gates._DEFAULT_GATE_RULES
    assert prompt_gates.parse_gate_rules(
        '```json gate_rules\n{"shot_min_chars": -5}\n```'
    )["shot_min_chars"] == prompt_gates._SHOT_PROMPT_MIN_CHARS


def test_validate_with_rules_require_duration_off():
    prompt = (
        "缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
        "前景冰晶闪烁，色调深青克制，<急促呼吸声与轰鸣>，no music，no subtitles。"
    )
    ok, hard, _ = prompt_gates.validate_prompt_write(
        prompt, "shot", rules={"require_duration": False, "shot_min_chars": 10})
    assert ok and not hard


def test_validate_with_custom_subtitle_synonym():
    prompt = (
        "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原"
        "崩裂成二维平面，前景冰晶在冷光中闪烁，色调深青克制，"
        "<急促呼吸声与轰鸣>，no music，不要字幕。"
    )
    ok, hard, _ = prompt_gates.validate_prompt_write(
        prompt, "shot", rules={"subtitle_synonyms": ["不要字幕"]})
    assert ok and not hard


def test_executor_uses_skill_gate_rules_as_rejection(svc):
    svc.state_dict["shots"] = [{
        "id": "shot-1", "title": "S", "duration": "10s", "sceneRefs": [],
        "drafts": [{"id": "d1", "mediaType": "video", "prompt": ""}],
    }]
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.gate_rules = {"shot_min_chars": 200}
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "d1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }])
    assert applied == 0  # 决策 D：Skill 规则把最短字数提到 200 → 拒绝写入
    assert ex.gate_rejections
    # 用户坚持 → 照常写入并警告
    ex2 = StateOperationExecutor(svc, gate_enabled=True)
    ex2.gate_rules = {"shot_min_chars": 200}
    ex2.gate_override = True
    applied2 = ex2.execute([{
        "action": "update_draft", "draft_id": "d1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }])
    assert applied2 == 1
    assert ex2.gate_warnings and "过短" in ex2.gate_warnings[0]


def test_fc_runner_uses_skill_gate_rules_as_rejection(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    runner._gate_rules = {"shot_min_chars": 10_000}
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT_PROMPT}},
        injected_skill="任意 Skill",
    )
    assert err is not None and "过短" in err
    runner2 = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    runner2._gate_rules = {"shot_min_chars": 10_000}
    runner2.gate_override = True
    err2 = runner2._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT_PROMPT}},
        injected_skill="任意 Skill",
    )
    assert err2 is None
    assert runner2.gate_warnings and "过短" in runner2.gate_warnings[0]


def test_fc_gate_off_mode(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="任意 Skill",
    ) is None


# ---------- C5：豁免唯一权威入口 = 按钮 scope（正则 NLU 已退役） ----------

def test_user_insists_nlu_retired():
    """C5（任务#22）：正则猜自然语言豁免入口退役，「坚持/听我的/直接写」
    类话术不再降级闸门（误伤面归零）；豁免只认按钮 gate_overrides"""
    assert not hasattr(prompt_gates, "user_insists_override")
    from src.video_agent.core import planner_gate_session

    class _Svc:  # 最小 stub：无 interaction 豁免登记
        state_dict = {}

        def save(self):
            pass

    for text in ("听我的", "我坚持，按我说的来", "直接写提示词，不要概念图", "绕过闸机直接写"):
        assert planner_gate_session.consume_gate_overrides(_Svc(), text) is False


def test_button_gate_overrides_consumed_once():
    """C5：按钮路径照常消费——scope=all 映射 ALL、单次消费即清除"""
    from src.video_agent.core import planner_gate_session

    class _Svc:
        state_dict = {"interaction": {"gate_overrides": ["all"]}}

        def save(self):
            pass

    svc = _Svc()
    assert (
        planner_gate_session.consume_gate_overrides(svc, "任意文本")
        == prompt_gates.GATE_OVERRIDE_SCOPE_ALL
    )
    # 单次消费：豁免清单已清空，次轮不再放行
    assert svc.state_dict["interaction"]["gate_overrides"] == []
    assert planner_gate_session.consume_gate_overrides(svc, "任意文本") is False


def test_override_covers_matrix():
    """M1：作用域覆盖矩阵（含旧布尔语义兼容：True 等价 all）"""
    assert prompt_gates.override_covers(True, prompt_gates.GATE_STRUCTURE)
    assert prompt_gates.override_covers("all", prompt_gates.GATE_STRUCTURE)
    assert not prompt_gates.override_covers("flow", prompt_gates.GATE_STRUCTURE)
    assert not prompt_gates.override_covers("", prompt_gates.GATE_STRUCTURE)
    assert not prompt_gates.override_covers(False, prompt_gates.GATE_STRUCTURE)


def test_spec_rules_standalone_doc(svc):
    from src.video_agent.core import spec_rules

    # 铁律为独立文档：写规格文档后 ensure，规格正文不含铁律章节
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "# 制片规格\n标题：测试\n"}]
    assert spec_rules.ensure_iron_rules_doc(svc.state_dict) is True
    names = [d["name"] for d in svc.state_dict["documents"]]
    assert "执行铁律.md" in names
    iron = spec_rules.find_iron_rules_doc(svc.state_dict)
    assert "3. 回复纪律见平台协议" in iron["content"]
    spec = svc.state_dict["documents"][names.index("制片规格.md")]
    assert "执行铁律" not in spec["content"]
    # 幂等：不再重复创建
    assert spec_rules.ensure_iron_rules_doc(svc.state_dict) is False


def test_spec_rules_migrate_legacy_appendix():
    """老项目：规格文档里的铁律章节自动迁入独立文档（保留用户编辑内容）。"""
    from src.video_agent.core import spec_rules

    legacy = (
        "# 规格\n时长：60s\n\n"
        "## 执行铁律（系统约定，按优先级执行：用户指令 > 本文档 > Skill/系统默认）\n"
        "1. 拆解覆盖完整：所有有台词的具名角色都必须单独建组。\n"
    )
    state = {"documents": [{"name": "制片规格.md", "content": legacy}]}
    assert spec_rules.ensure_iron_rules_doc(state) is True
    spec = next(d for d in state["documents"] if d["name"] == "制片规格.md")
    assert "执行铁律" not in spec["content"]  # 章节已从规格文档剥离
    assert "时长：60s" in spec["content"]
    iron = spec_rules.find_iron_rules_doc(state)
    assert iron is not None
    assert "拆解覆盖完整" in iron["content"]  # 用户内容原样保留
    # 迁移完成后幂等
    assert spec_rules.ensure_iron_rules_doc(state) is False


# ---------- 卡片枚举压缩（8888 事故：正文逐卡罗列既耗 token 又撑长卡片） ----------

def test_compact_card_enumeration():
    from src.video_agent.web.chat_service import _compact_card_enumeration

    text = (
        "已为全部 3 个关键元素完成提示词编制：\n"
        "- **1 组 1 卡（Element_A）**：已写入定义 A。\n"
        "- **2 组 1 卡（Element_B）**：已写入定义 B。\n"
        "- **3 组 1 卡（Element_C）**：已写入定义 C。\n"
        "请在左侧故事板审阅。"
    )
    out = _compact_card_enumeration(text)
    assert "逐卡明细已写入左侧故事板" in out
    assert "Element_A" not in out
    assert "请在左侧故事板审阅" in out
    # 少于 3 行不触发
    short = "1. **Shot 1（测试）**：a。\n2. **Shot 2（测试）**：b。"
    assert _compact_card_enumeration(short) == short
