"""任务#12 E-6 禁令下沉回归：生成前资产绑定检查（skill.gen_asset_binding）。

原李安 Skill prose 禁令「缺少场景参考图不启动视频生成」机检化：
判定唯一实现 = guard_pipeline.evaluate_gen_asset_binding
（引用感知：sceneRefs 引用的关键元素无概念图即拦，无引用不误伤）；
文本轨接线 = StateOperationExecutor._gen_asset_binding_gate
（apply_generate_video 生成提交入口前置校验，不新造平行闸体系）。
"""
from src.video_agent.core import guard_pipeline, prompt_gates
from src.video_agent.core.action_executor import StateOperationExecutor

# 关键元素：有图 / 无图两种客观状态
KE_WITH_IMG = {"id": "ke-1", "title": "竹林场景",
               "drafts": [{"id": "d-ke1", "imgUrl": "https://x/ke1.png"}]}
KE_NO_IMG = {"id": "ke-2", "title": "长剑道具",
             "drafts": [{"id": "d-ke2", "prompt": "刚性道具"}]}

GROUP_OK = {"id": "shot-1", "title": "镜头一", "sceneRefs": ["ke-1"],
            "drafts": [{"id": "d-s1", "prompt": "镜头提示词", "tag": "已确认"}]}
GROUP_MISSING = {"id": "shot-2", "title": "镜头二", "sceneRefs": ["ke-2"],
                 "drafts": [{"id": "d-s2", "prompt": "镜头提示词", "tag": "已确认"}]}
GROUP_NO_REFS = {"id": "shot-3", "title": "镜头三", "sceneRefs": [],
                 "drafts": [{"id": "d-s3", "prompt": "镜头提示词", "tag": "已确认"}]}


def _state(*ke_groups):
    return {"keyElements": list(ke_groups), "shots": [], "audioItems": []}


def test_block_when_referenced_element_has_no_image():
    state = _state(KE_WITH_IMG, KE_NO_IMG)
    err, warns = guard_pipeline.evaluate_gen_asset_binding(
        state, [GROUP_MISSING], active=True)
    assert err and "资产绑定检查拦截" in err
    assert "镜头二" in err
    assert warns == [err]


def test_pass_when_all_referenced_elements_have_images():
    state = _state(KE_WITH_IMG, KE_NO_IMG)
    err, warns = guard_pipeline.evaluate_gen_asset_binding(
        state, [GROUP_OK], active=True)
    assert err is None and warns == []


def test_no_scene_refs_not_misblocked():
    """无 sceneRefs / 未引用关键元素的目标不误伤（引用感知语义）"""
    state = _state(KE_NO_IMG)
    err, warns = guard_pipeline.evaluate_gen_asset_binding(
        state, [GROUP_NO_REFS], active=True)
    assert err is None and warns == []


def test_override_pass_with_warning():
    state = _state(KE_NO_IMG)
    err, warns = guard_pipeline.evaluate_gen_asset_binding(
        state, [GROUP_MISSING], active=True, override="all")
    assert err is None and warns and "坚持" in warns[0]


def test_inactive_or_empty_pass():
    state = _state(KE_NO_IMG)
    err, warns = guard_pipeline.evaluate_gen_asset_binding(
        state, [GROUP_MISSING], active=False)
    assert err is None and warns == []
    err, warns = guard_pipeline.evaluate_gen_asset_binding(state, [], active=True)
    assert err is None and warns == []


def test_rule_registered():
    meta = prompt_gates.GATE_RULES["skill.gen_asset_binding"]
    assert meta.layer == "skill"
    assert meta.description


def test_blocked_message_from_messages_md():
    """文案单一事实源：拦截文案来自 prompts/gates/messages.md 分节"""
    from src.video_agent.utils.prompts import load_prompt_section
    assert prompt_gates.GEN_ASSET_BINDING_BLOCKED == load_prompt_section(
        "gates/messages.md", "GEN_ASSET_BINDING_BLOCKED")


class _SvcStub:
    def __init__(self, state):
        self.state_dict = state


def _text_executor(state, override=False):
    e = object.__new__(StateOperationExecutor)
    e.svc = _SvcStub(state)
    e.gate_enabled = True
    e.gate_override = override
    e.gate_warnings = []
    e.gate_rejections = []
    return e


def test_text_track_wiring_blocks_batch(monkeypatch):
    """文本轨接线：缺图分镜整批拦截并结构化回喂（gate_rejections）"""
    monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
    state = _state(KE_NO_IMG)
    ex = _text_executor(state)
    pairs = [(GROUP_MISSING, GROUP_MISSING["drafts"][0])]
    assert ex._gen_asset_binding_gate(pairs) == []
    assert ex.gate_rejections and "资产绑定检查拦截" in ex.gate_rejections[0]


def test_text_track_wiring_passes_when_ready(monkeypatch):
    monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
    state = _state(KE_WITH_IMG)
    ex = _text_executor(state)
    pairs = [(GROUP_OK, GROUP_OK["drafts"][0])]
    assert ex._gen_asset_binding_gate(pairs) == pairs
    assert ex.gate_warnings == [] and ex.gate_rejections == []


def test_text_track_override_passes(monkeypatch):
    monkeypatch.setattr("src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
    state = _state(KE_NO_IMG)
    ex = _text_executor(state, override="all")
    pairs = [(GROUP_MISSING, GROUP_MISSING["drafts"][0])]
    assert ex._gen_asset_binding_gate(pairs) == pairs
    assert ex.gate_warnings and "坚持" in ex.gate_warnings[0]
