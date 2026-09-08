"""提示词结构闸机：校验规则 + FC/文本双轨拦截"""
import pytest

from src.video_agent.core import fc_gates, prompt_gates
from src.video_agent.state.manager import StateManager

GOOD_SHOT_PROMPT = (
    "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
    "前景飘散的冰晶在冷光中闪烁，整体色调深青克制，Strong chiaroscuro contrast，"
    "<急促的呼吸声与远方空间坍缩的轰鸣>，no music，no subtitles。"
)


# ---------- 校验规则（C1a 裁决 2026-08-31：平台固定地板＝字数+语言闸） ----------

def test_shot_prompt_complete_passes():
    ok, hard, _ = prompt_gates.validate_prompt_write(GOOD_SHOT_PROMPT, "shot")
    assert ok and not hard


def test_shot_prompt_too_short():
    ok, hard, _ = prompt_gates.validate_prompt_write("推入，no subtitles，<音效>", "shot")
    assert not ok
    assert any("过短" in e for e in hard)


def test_shot_prompt_missing_duration():
    """C1a 裁决：require_duration 技能闸退役——未写时长不再打回（平台地板只守字数+语言）"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "缓慢推入中景，主体在冰原上奔跑，怀中紧抱文物，背景冥王星冰原崩裂成平面，"
        "前景飘散的冰晶在冷光中闪烁，光影克制，色调深青，<音效轰鸣>，no music，no subtitles。", "shot")
    assert ok and not hard


def test_business_gates_retired_platform_floor_only():
    """C1a 裁决回归：技能级闸层删除——时长/字幕/音频层/镜头语言不再校验，
    平台固定地板（字数下限+语言闸）仍在。"""
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


# 8888 事故对应的「英文正文拒收」用例已随 2026-09-06 用户裁决退役：
# 语言闸私设推导删除，提示词书写语言归文档层（Skill 要求 / 规格显式声明），
# 整段英文提示词不再属闸机执法面（防复活用例见 test_trace_sse_consistency.py）。


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


# ---------- 文本轨拦截用例已随 Q2 裁决 2026-09-01 整体退役删除 ----------
# test_executor_rejects_bad_update_draft_by_default /
# test_executor_user_override_writes_bad_prompt_with_warning /
# test_executor_passes_good_update_draft / test_executor_gate_disabled_allows_everything /
# test_executor_add_group_rejects_bad_inline_draft /
# test_executor_spec_gate_allows_after_spec_written /
# test_executor_spec_gate_inactive_without_skill /
# test_executor_structure_strips_inline_prompt_on_first_batch /
# test_executor_pending_window_does_not_block_prompt_write：
# 文本轨动作分派（executor.execute）随执行器家族退役；拦截/坚持/放行/
# 关闭四态与结构剥离、待确认窗口语义由下方 FC 轨同口径用例钉死（G4 同类路径）。

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


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


def _pctx(state=None, injected_skill="任意 Skill", override=False):
    return fc_gates.GateContext(
        state=lambda: state if state is not None else {},
        injected_skill=injected_skill, gate_override=override)


def test_fc_strips_structure_prompt_on_first_batch(monkeypatch):
    """FC 轨：首次搭建批次剥离内联详细提示词（P0-2）"""
    args = {"group_type": "keyElement", "title": "Element_测试",
            "draft": {"label": "概念图", "prompt": "x" * 100}}
    assert fc_gates.strip_structure_prompt(
        _pctx(), "storyboard_create_group", args) is True
    assert args["draft"]["prompt"] == ""
    assert fc_gates.strip_structure_prompt(
        _pctx(injected_skill=""),
        "storyboard_create_group", {"draft": {"prompt": "x" * 100}}) is False
    assert fc_gates.strip_structure_prompt(
        _pctx(), "storyboard_create_group",
        {"draft": {"prompt": "x" * 100}}) is True


def test_fc_pending_window_rejects_bad_prompt(monkeypatch):
    """过短提示词触发字数地板拒收（语言轴已退役，地板=字数）：
    待确认窗口内拒收、用户坚持后放行并警告。"""
    pending = {"interaction": {"storyboard_pending": True}}
    err = fc_gates.prompt_gate(
        _pctx(pending), "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "keyElement", "patch": {"prompt": "x" * 10}},
    )
    assert err is not None  # 决策 D：硬性条款未通过 → 拒绝
    # 用户坚持 → 放行并警告
    ctx2 = _pctx(pending, override=True)
    err2 = fc_gates.prompt_gate(
        ctx2, "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "keyElement", "patch": {"prompt": "x" * 10}},
    )
    assert err2 is None
    assert ctx2.warnings


# ---------- FC 轨拦截 ----------

def test_fc_gate_rejects_bad_prompt(monkeypatch):
    err = fc_gates.prompt_gate(
        _pctx(injected_skill="剧本生视频（需上传剧本）"), "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
    )
    assert err is not None and "过短" in err


def test_fc_gate_passes_without_skill(monkeypatch):
    assert fc_gates.prompt_gate(
        _pctx(injected_skill=""), "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
    ) is None


def test_fc_gate_passes_good_prompt(monkeypatch):
    assert fc_gates.prompt_gate(
        _pctx(), "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT_PROMPT}},
    ) is None


def test_fc_gate_off_mode(monkeypatch):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert fc_gates.prompt_gate(
        _pctx(), "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
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
    # 批 A3（指令收拢批）：默认模板收敛为「契约条款 + 头部指针」——
    # 冲突与缺信息处置、回复纪律唯一表述源 = 《执行铁律》头部声明
    assert "拆解覆盖完整" in iron["content"]
    assert "见平台注入的《执行铁律》头部声明" in iron["content"]
    assert "执行优先" not in iron["content"]  # 与头部同义复述已删
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
