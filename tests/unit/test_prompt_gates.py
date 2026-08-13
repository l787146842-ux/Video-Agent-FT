"""提示词结构闸机：校验规则 + FC/文本双轨拦截"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.web.action_executor import StudioActionExecutor

GOOD_SHOT_PROMPT = (
    "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
    "前景飘散的冰晶在冷光中闪烁，整体色调深青克制，Strong chiaroscuro contrast，"
    "<急促的呼吸声与远方空间坍缩的轰鸣>，no music，no subtitles。"
)


# ---------- 校验规则 ----------

def test_shot_prompt_complete_passes():
    ok, hard, _ = prompt_gates.validate_prompt_write(GOOD_SHOT_PROMPT, "shot")
    assert ok and not hard


def test_shot_prompt_missing_no_subtitles():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体奔跑，空间崩裂，<音效轰鸣>，no music。", "shot",
        rules={"require_subtitle": True})
    assert not ok
    assert any("no subtitles" in e for e in hard)


def test_shot_prompt_missing_audio_layer():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体在冰原上奔跑，背景崩裂成平面，光影克制，no subtitles。", "shot",
        rules={"require_audio_layer": True})
    assert not ok
    assert any("音频层" in e for e in hard)


def test_shot_prompt_missing_camera():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "程心怀抱文物奔向舱门，背景冥王星冰原崩裂，<呼吸声与轰鸣>，no music，no subtitles。", "shot",
        rules={"require_camera_language": True})
    assert not ok
    assert any("镜头语言" in e for e in hard)


def test_shot_prompt_too_short():
    ok, hard, _ = prompt_gates.validate_prompt_write("推入，no subtitles，<音效>", "shot")
    assert not ok
    assert any("过短" in e for e in hard)


def test_shot_prompt_missing_duration():
    """镜头时长强制条款：提示词未写明本镜头总时长即打回"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体奔跑，空间崩裂，<音效轰鸣>，no music，no subtitles。", "shot",
        rules={"require_duration": True})
    assert not ok
    assert any("时长" in e for e in hard)


def test_shot_prompt_with_duration_passes():
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "镜头总时长：12秒。缓慢推入中景，主角在冰原上奔跑，怀中紧抱文物，背景崩裂成平面，"
        "光影克制，色调深青，<音效轰鸣>，no music，no subtitles。", "shot")
    assert ok and not hard


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
        "drafts": [{"id": "draft-1", "label": "分镜 1", "mediaType": "video", "prompt": ""}],
    }]


def test_executor_strict_blocks_bad_update_draft(svc):
    _seed_shot(svc)
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": "太短了"},
    }])
    assert applied == 0
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == ""


def test_executor_passes_good_update_draft(svc):
    _seed_shot(svc)
    ex = StudioActionExecutor(svc, gate_enabled=True)
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
    ex = StudioActionExecutor(svc)  # gate_enabled 默认 False
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": "太短了"},
    }])
    assert applied == 1


def test_executor_add_group_skips_bad_inline_draft(svc):
    # 预置规格文档：否则会被规格前置闸机整体拦下（见下方专项用例）
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "shot", "title": "Shot_新",
        "draft": {"label": "分镜", "prompt": "敷衍短句"},
    }])
    # 分组创建成功，但不合格草稿被闸机拦下
    assert applied == 1
    group = svc.state_dict["shots"][-1]
    assert group["title"] == "Shot_新" and group["drafts"] == []


# ---------- 规格文档前置闸机（666 项目事故：跳过 Final_Video_Spec.md 直建故事板） ----------

def test_has_spec_document_variants():
    assert prompt_gates.has_spec_document({"documents": []}) is False
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "Final_Video_Spec.md", "content": "正文"}]}) is True
    # 大小写/空格/连字符不敏感
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "final video-spec", "content": "正文"}]}) is True
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "制作规格", "content": "正文"}]}) is True
    # 空文档不算数（防绕过）
    assert prompt_gates.has_spec_document(
        {"documents": [{"name": "Final_Video_Spec.md", "content": "  "}]}) is False


def test_executor_spec_gate_warns_when_declared(svc, tmp_path, monkeypatch):
    """规格前置警告（S1）：只对显式声明 flow.spec_gate 的 Skill 生效，
    且不硬拦（用户指令优先，警告随 gate_warnings 回喂）。"""
    import src.video_agent.web.skill_docs as sd

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", skill_dir)
    sd.save_skill_doc(
        "有规格闸",
        '# A\n```json skill_manifest\n' '{"flow": {"spec_gate": true}}\n' "```\n正文",
    )
    before = len(svc.state_dict.get("keyElements") or [])
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    # 未声明 spec_gate 的 Skill：完全静默，照常搭建
    assert applied == 1
    assert ex.gate_warnings == []
    # 声明了 spec_gate 的 Skill：照常搭建 + 追加「建议补写规格」警告
    ex2 = StudioActionExecutor(svc, gate_enabled=True)
    ex2.skill_name = "有规格闸"
    applied = ex2.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试2",
    }])
    assert applied == 1
    assert any("规格" in w for w in ex2.gate_warnings)
    assert len(svc.state_dict.get("keyElements") or []) == before + 2


def test_executor_spec_gate_allows_after_spec_written(svc):
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    assert applied == 1


def test_executor_spec_gate_inactive_without_skill(svc):
    ex = StudioActionExecutor(svc)  # gate_enabled=False → 日常微调不受影响
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
    }])
    assert applied == 1


def test_fc_flow_gate_blocks_create_group_without_spec(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {"documents": []}))
    err = runner._flow_gate("storyboard_create_group", injected_skill="剧本生视频（需上传剧本）")
    assert err and "规格文档" in err
    # 无 Skill / 非结构工具不拦
    assert runner._flow_gate("storyboard_create_group", injected_skill="") is None
    assert runner._flow_gate("storyboard_patch_draft", injected_skill="任意") is None


def test_fc_flow_gate_passes_with_spec(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"documents": [{"name": "Final_Video_Spec.md", "content": "正文"}]}))
    assert runner._flow_gate("storyboard_create_group", injected_skill="任意 Skill") is None


# ---------- 元素图像时序硬闸（666 项目事故：无概念图先写分镜提示词） ----------

def _seed_ke_without_image(svc):
    svc.state_dict["keyElements"] = [{
        "id": "ke-test", "title": "Element_测试",
        "drafts": [{"id": "draft-ke", "label": "元素", "imgUrl": ""}],
    }]


def test_element_images_missing_helper():
    assert prompt_gates.element_images_missing({}) is False  # 未建卡不适用
    assert prompt_gates.element_images_missing({"keyElements": [
        {"drafts": [{"imgUrl": ""}]}]}) is True
    assert prompt_gates.element_images_missing({"keyElements": [
        {"drafts": [{"imgUrl": "http://x/a.png"}]}]}) is False


def test_executor_blocks_shot_prompt_before_element_images(svc):
    _seed_ke_without_image(svc)
    _seed_shot(svc)
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }])
    assert applied == 0
    # 元素图像就绪后放行
    svc.state_dict["keyElements"][0]["drafts"][0]["imgUrl"] = "http://x/a.png"
    applied = ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }])
    assert applied == 1


def test_fc_gate_blocks_shot_prompt_before_element_images(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {"keyElements": [
        {"drafts": [{"imgUrl": ""}]}]}))
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT_PROMPT}},
        injected_skill="任意 Skill",
    )
    assert err and "元素" in err and "拒绝" in err


# ---------- 结构纯净闸 + 故事板待确认窗口（888 项目事故：步骤3+4 合并且虚报） ----------

def test_fc_strip_structure_prompt(monkeypatch):
    """FC 轨：create_group 内联详细提示词被剥离，结构照常建立（不丢分组不虚报）"""
    runner = FCToolRunner(tool_manager=None)
    args = {"group_type": "keyElement", "title": "Element_测试",
            "draft": {"label": "概念图", "prompt": "x" * 100}}
    assert runner._strip_structure_prompt(
        "storyboard_create_group", args, injected_skill="任意 Skill") is True
    assert args["draft"]["prompt"] == ""
    # 短提示词/无 Skill/非结构工具不剥离
    args2 = {"draft": {"prompt": "短描述"}}
    assert runner._strip_structure_prompt(
        "storyboard_create_group", args2, injected_skill="任意 Skill") is False
    assert runner._strip_structure_prompt(
        "storyboard_patch_draft", {"draft": {"prompt": "x" * 100}}, injected_skill="任意") is False
    assert runner._strip_structure_prompt(
        "storyboard_create_group", {"draft": {"prompt": "x" * 100}}, injected_skill="") is False


def test_executor_structure_strips_inline_prompt(svc):
    """文本轨：add_group 内联详细提示词被剥离，分组与草稿卡照常建立"""
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    ex = StudioActionExecutor(svc, gate_enabled=True)
    applied = ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_测试",
        "draft": {"label": "概念图", "prompt": "y" * 120},
    }])
    assert applied == 1
    group = svc.state_dict["keyElements"][-1]
    assert group["title"] == "Element_测试"
    assert group["drafts"][0]["prompt"] == ""  # 详细提示词被剥离，留到步骤4


def test_executor_pending_window_blocks_prompt_write(svc):
    """步骤3→步骤4 分界：结构建立后置位待确认标记，窗口内拒绝提示词写入；
    用户新消息到达（消费确认）后解除封锁"""
    from src.video_agent.web.chat_service import _consume_pending_confirmation
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md", "content": "规格正文"}]
    _seed_shot(svc)
    ex = StudioActionExecutor(svc, gate_enabled=True)
    # 同批：建结构 + 写提示词 → 提示词被拦（步骤3与4不得合并）
    applied = ex.execute([
        {"action": "add_group", "group_type": "keyElement", "title": "Element_新"},
        {"action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
         "patch": {"prompt": GOOD_SHOT_PROMPT}},
    ])
    assert applied == 1  # 只有建结构成功
    assert svc.state_dict["interaction"]["storyboard_pending"] is True
    assert svc.state_dict["shots"][0]["drafts"][0]["prompt"] == ""
    # 窗口持续：新批次同样拒绝
    assert ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }]) == 0
    # 用户回应到达 → 解除封锁 → 可写提示词
    _consume_pending_confirmation(svc)
    assert svc.state_dict["interaction"].get("storyboard_pending") is False
    assert ex.execute([{
        "action": "update_draft", "draft_id": "draft-1", "draft_type": "shot",
        "patch": {"prompt": GOOD_SHOT_PROMPT},
    }]) == 1


def test_fc_pending_window_blocks_prompt_write(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(
        lambda: {"interaction": {"storyboard_pending": True}}))
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "keyElement", "patch": {"prompt": "x" * 80}},
        injected_skill="任意 Skill",
    )
    assert err and "等待用户审阅" in err


# ---------- FC 轨拦截 ----------

def test_fc_gate_blocks_bad_prompt(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="剧本生视频（需上传剧本）",
    )
    assert err and "闸机拦截" in err


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


def test_fc_gate_off_mode(monkeypatch):
    runner = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="任意 Skill",
    ) is None
