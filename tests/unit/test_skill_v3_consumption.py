# -*- coding: utf-8 -*-
"""任务#35 B2/B3：v3 元数据（requires_inputs/kind/language）与通用暂停点消费落地回归。

钉死：
1) registry 声明读取 API（零预设 + fail-closed 清洗）；
2) 原料闸：requires_inputs 优先、script_required 回落，两路不叠加；
3) prompt_builder 元数据头：未满足提示/语言说明/暂停点清单注入位置；
4) 语言闸：language.prompt=en 按声明放宽（读取经 registry API，可 patch）；
5) skill_pause_points 四级优先级各一例 + bool 兼容语义；
6) 未迁移 v2 manifest 全路径行为零变化（回归）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import gates_inputs
from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core import prompt_gates
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core.workflow_runtime import WorkflowRuntime
from src.video_agent.skill_runtime import frontmatter, registry
from src.video_agent.skill_runtime.guard import (
    skill_pause_points,
    skill_requires_stage_pause,
)
from src.video_agent.state.manager import StateManager

_LONG_EN_PROMPT = (
    "A monolithic black slab rises over the desert at dawn, extreme wide shot, "
    "slow push-in, hard rim light, volumetric dust, no subtitles. This is a "
    "long English body prompt that clearly exceeds the minimum character budget."
)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    # 任务#5：frontmatter 随文档同根（经 skill_docs 端口读 SKILL_DOCS_DIR），
    # 上面的目录隔离即声明隔离；不隔离会把测试桩文档泄漏进真实
    # data/skills，后续懒同步 sync_all 把泄漏文档重新注册回来，
    # 掩盖 fail-hard 拒注册。
    registry.reset_registry()
    yield
    registry.reset_registry()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path / "ws"))
    StateManager.reset_instance()


def _save(name: str, content: str = "", manifest=None):
    sd.save_skill_doc(name, content or f"# {name}\n正文")
    if manifest is not None:
        frontmatter.write_manifest(name, manifest)
    registry.register_skill(name)


# ---------- 1) registry 声明读取 API ----------

def test_registry_v3_readers_zero_preset_and_clean():
    _save("零预设", "# A\n正文")
    assert registry.skill_requires_inputs("零预设") == []
    assert registry.skill_kind("零预设") == ""
    assert registry.skill_language("零预设") == {}
    assert registry.skill_requires_inputs("不存在") == []

    _save("全声明", "# B\n正文", {
        "kind": "style",
        "requires_inputs": [
            {"type": "script"},  # required 缺省 true
            {"type": "music", "required": False, "hint": "请先上传 BGM"},
        ],
        "language": {"prompt": "en"},
    })
    reqs = registry.skill_requires_inputs("全声明")
    assert [r["type"] for r in reqs] == ["script", "music"]
    assert reqs[0]["required"] is True and reqs[1]["required"] is False
    assert reqs[1]["hint"] == "请先上传 BGM"
    assert registry.skill_kind("全声明") == "style"
    assert registry.skill_language("全声明") == {"prompt": "en"}


def test_registry_v3_fail_hard_rejects_invalid_manifest():
    """C4 fail-hard（任务#22）：schema 违规拒注册，替代旧「只告警不阻断」。"""
    _save("坏声明", "# X\n正文", {
        "requires_inputs": [
            {"type": "外星人"},  # 白名单外 → 校验失败
            "bad",               # 非法项 → 校验失败
        ],
        "language": {"prompt": "en", "output": "非法值"},
    })
    assert registry.get_entry("坏声明") is None
    assert registry.skill_requires_inputs("坏声明") == []
    assert registry.skill_language("坏声明") == {}


def test_registry_v3_readers_fail_closed_on_live_edit():
    """消费端 fail-closed 清洗保留：合法注册后 frontmatter 被改坏，
    活读时非法项丢弃（不二次报错）。"""
    _save("活读清洗", "# Y\n正文", {"requires_inputs": [{"type": "script"}]})
    assert registry.get_entry("活读清洗") is not None
    frontmatter.write_manifest("活读清洗", {
        "requires_inputs": [{"type": "外星人"}, {"type": "music"}],
        "language": {"output": "非法值"},
    })
    assert [r["type"] for r in registry.skill_requires_inputs("活读清洗")] == ["music"]
    assert registry.skill_language("活读清洗") == {}


# ---------- 2) 原料闸：v3 优先 / v2 回落 / 两路不叠加 ----------

@pytest.mark.asyncio
async def test_gate_precheck_v3_script_missing_blocks(svc):
    _save("v3需剧本", manifest={"requires_inputs": [{"type": "script"}]})
    out = await po.gate_precheck(svc, "v3需剧本", "开始制作")
    assert out is not None and out.kind == "script_pending"
    # 豁免话术照常消费
    out2 = await po.gate_precheck(svc, "v3需剧本", "waive_script")
    assert out2 is None
    assert (svc.state_dict.get("interaction") or {}).get("script_waived") is True


@pytest.mark.asyncio
async def test_gate_precheck_v3_nonscript_missing_generic_remind(svc):
    _save("v3需音乐", manifest={
        "requires_inputs": [{"type": "music", "hint": "本 Skill 需要先上传音乐文件"}]})
    out = await po.gate_precheck(svc, "v3需音乐", "开始制作")
    assert out is not None and out.kind == "script_pending"
    assert "需要先上传音乐文件" in out.message
    # 素材到达（assets 登记）→ 放行
    svc.state_dict["assets"] = [{"name": "bgm.mp3", "type": "music", "url": "/workspace/assets/bgm.mp3"}]
    out2 = await po.gate_precheck(svc, "v3需音乐", "继续")
    assert out2 is None or out2.kind != "script_pending"


@pytest.mark.asyncio
async def test_gate_precheck_v3_overrides_v2_no_stack(svc):
    """两路不叠加：声明了 v3 清单（仅音乐）后，即便 flow.script_required=true
    且剧本缺失，也不再弹剧本提醒卡（v3 清单独占判定）。"""
    _save("v3覆盖v2", manifest={
        "flow": {"script_required": True},
        "requires_inputs": [{"type": "music"}],
    })
    out = await po.gate_precheck(svc, "v3覆盖v2", "开始制作")
    assert out is not None and out.kind == "script_pending"
    assert "音乐" in out.message
    card_msg, _ = prompt_gates.script_remind_card()
    assert out.message != card_msg


@pytest.mark.asyncio
async def test_gate_precheck_v2_fallback_unchanged(svc):
    """未迁移 v2 manifest：回落 script_required 旧路径，提醒卡文案逐字节不变。"""
    _save("v2需剧本", manifest={"flow": {"script_required": True}})
    out = await po.gate_precheck(svc, "v2需剧本", "开始制作")
    assert out is not None and out.kind == "script_pending"
    card_msg, card_opts = prompt_gates.script_remind_card()
    assert out.message == card_msg
    assert out.options == card_opts
    out_ack = await po.gate_precheck(svc, "v2需剧本", "upload_script")
    assert out_ack is not None and out_ack.kind == "script_ack"


def test_start_run_v3_input_gate(tmp_path):
    _save("v3开跑", manifest={"requires_inputs": [{"type": "script"}]})
    StateManager.reset_instance()
    svc1 = StateManager(str(tmp_path / "ws1"))
    run = WorkflowRuntime(svc1, "v3开跑").start_run()
    assert run["status"] == "waiting_user" and run.get("pending_decision")
    StateManager.reset_instance()
    # 原料到达 → 不再等待（新实例避免复用旧 run 状态）
    svc2 = StateManager(str(tmp_path / "ws2"))
    svc2.state_dict["uploadedDocs"] = [{"name": "剧本.md", "content": "正文"}]
    run2 = WorkflowRuntime(svc2, "v3开跑").start_run()
    assert run2.get("pending_decision") is None
    StateManager.reset_instance()


# ---------- 3) 元数据头：注入内容与位置 ----------

def _pb(raw_state):
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def test_metadata_header_full_v3_declaration():
    _save("元数据全", "# 风格指导\n正文散文", {
        "kind": "style",
        "requires_inputs": [{"type": "script"}],
        "language": {"prompt": "en"},
        "pause_points": [
            {"id": "spec_finalized", "trigger": "spec_finalized"},
            {"id": "bb", "trigger": "batch_boundary", "description": "每批生成后"},
        ],
    })
    block = _pb({}).build_selected_skill_block("元数据全")
    assert "== Skill 元数据" in block
    assert "风格型" in block
    assert "本 Skill 需要剧本素材，尚未检测到上传" in block
    assert "英文书写" in block
    assert "平台会在以下节点兜底保证暂停" in block
    assert "规格定稿后" in block and "每批生成后" in block
    # 位置：元数据头在 Skill 全文之前
    assert block.index("== Skill 元数据") < block.index("风格指导")
    # 原料到达后缺失提示消失
    block2 = _pb({"uploadedDocs": [{"name": "a.md", "content": "x"}]}).build_selected_skill_block("元数据全")
    assert "原料未就绪" not in block2


def test_metadata_header_hint_override_and_empty_for_v2():
    _save("提示覆盖", "# X\n正文", {
        "requires_inputs": [{"type": "doc", "hint": "需要分镜参考文档"}]})
    block = _pb({}).build_selected_skill_block("提示覆盖")
    assert "需要分镜参考文档" in block

    # v2 存量形态（无 v3 键、无暂停声明）：元数据头零增量
    _save("v2素", "# Y\n正文", {"flow": {"spec_wizard": True}})
    block_v2 = _pb({}).build_selected_skill_block("v2素")
    assert "== Skill 元数据" not in block_v2


# ---------- 4) 语言闸：language.prompt=en 按声明放宽 ----------

def test_language_gate_relaxed_by_v3_declaration(svc):
    _save("英文向", "# E\n正文", {"language": {"prompt": "en"}})
    state = {"usedSkills": ["英文向"]}
    assert prompt_gates.resolve_prompt_language(state) == "英文"
    ok, hard, _ = prompt_gates.validate_prompt_write(_LONG_EN_PROMPT, "shot", state)
    assert ok and not hard
    # 未声明 language 的 Skill：同一英文提示词仍被语言闸打回（现状不变）
    _save("中文向", "# C\n正文")
    state_cn = {"usedSkills": ["中文向"]}
    assert prompt_gates.resolve_prompt_language(state_cn) == "中文"
    ok2, hard2, _ = prompt_gates.validate_prompt_write(_LONG_EN_PROMPT, "shot", state_cn)
    assert not ok2 and any(prompt_gates.LANG_EN_HARD_PREFIX in h for h in hard2)


def test_language_gate_read_path_patchable(monkeypatch):
    """读取路径经 registry 模块属性（测试 patch 目标稳定）。"""
    _save("可patch", "# P\n正文")
    monkeypatch.setattr(registry, "skill_language", lambda name: {"prompt": "en"})
    state = {"usedSkills": ["可patch"]}
    assert prompt_gates.resolve_prompt_language(state) == "英文"
    ok, hard, _ = prompt_gates.validate_prompt_write(_LONG_EN_PROMPT, "shot", state)
    assert ok and not hard


# ---------- 5) 通用暂停点：四级优先级 + bool 兼容 ----------

_ANCHORS = ("storyboard_structure_ready", "first_generation_call")


def _triggers(points):
    return tuple(p["trigger"] for p in points)


def test_pause_points_priority_1_manifest_declaration():
    _save("一级", "# 1\n何时暂停：每阶段后。", {
        "pause": {"stage_pause": False},  # 被 pause_points 压制（一级优先）
        "pause_points": [
            {"id": "spec_finalized", "trigger": "spec_finalized"},
            {"id": "ft", "trigger": "free_text", "prose": "每三镜确认一次"},
        ],
    })
    points = skill_pause_points("一级")
    assert _triggers(points) == ("spec_finalized", "free_text")
    assert points[1]["prose"] == "每三镜确认一次"
    assert skill_requires_stage_pause("一级") is True
    # 显式空清单接管：即便正文含关键词也视为不要求暂停
    _save("一级空", "# 1e\n何时暂停：每阶段后。", {"pause_points": []})
    assert skill_pause_points("一级空") == []
    assert skill_requires_stage_pause("一级空") is False


def test_pause_points_fail_hard_and_live_clean():
    """C4 fail-hard：非法 pause_points 声明拒注册；注册后改坏的
    活读场景仍 fail-closed 丢弃非法项（trigger 白名单外/缺附件）。"""
    _save("坏暂停", "# X\n正文", {
        "pause_points": [{"id": "x", "trigger": "user_confirmed"}]})
    assert registry.get_entry("坏暂停") is None
    assert skill_pause_points("坏暂停") == []

    _save("活读暂停", "# Y\n正文", {
        "pause_points": [{"id": "ok", "trigger": "spec_finalized"}]})
    frontmatter.write_manifest("活读暂停", {"pause_points": [
        {"id": "ok", "trigger": "spec_finalized"},
        {"id": "bad", "trigger": "不在白名单"},
        {"id": "bb", "trigger": "batch_boundary"},  # 缺 description 丢弃
    ]})
    assert _triggers(skill_pause_points("活读暂停")) == ("spec_finalized",)


def test_pause_points_priority_2_stage_pause_mechanical():
    _save("二级", "# 2\n正文", {"pause": {"stage_pause": True}})
    assert _triggers(skill_pause_points("二级")) == _ANCHORS
    assert skill_requires_stage_pause("二级") is True
    _save("二级关", "# 2f\n何时暂停：每阶段后。", {"pause": {"stage_pause": False}})
    assert skill_pause_points("二级关") == []
    assert skill_requires_stage_pause("二级关") is False


def test_pause_points_priority_3_pause_rules_block():
    _save("三级", "# 3\n```json pause_rules\n{\"stage_pause\": true}\n```\n正文")
    assert _triggers(skill_pause_points("三级")) == _ANCHORS
    assert skill_requires_stage_pause("三级") is True


def test_pause_points_priority_4_keyword_fallback():
    _save("四级", "# 4\n本流程在强制暂停点处停下等确认。")
    assert _triggers(skill_pause_points("四级")) == _ANCHORS
    assert skill_requires_stage_pause("四级") is True
    _save("无暂停", "# 5\n普通正文")
    assert skill_pause_points("无暂停") == []
    assert skill_requires_stage_pause("无暂停") is False


# ---------- 6) 未迁移 v2 manifest 全路径回归（行为零变化） ----------

def test_v2_manifest_pause_semantics_unchanged():
    """v2 pause.stage_pause 声明：bool 判定与黄金语义一致，
    清单形态只是机械转两锚点（迁移脚本同口径）。"""
    _save("v2暂停", "# V\n正文", {"pause": {"stage_pause": True}})
    assert skill_requires_stage_pause("v2暂停") is True
    assert _triggers(skill_pause_points("v2暂停")) == _ANCHORS


def test_v2_manifest_gate_and_language_unchanged(svc):
    """v2 manifest（script_required + gates）：原料闸走旧提醒卡，
    语言闸维持 cjk_min_ratio 现状口径。"""
    _save("v2完整", "# V2\n正文", {
        "flow": {"script_required": True},
        "gates": {"cjk_min_ratio": 0},
    })
    # v2 英文锁定口径不变：由调用方传入 parse_gate_rules 结果（现状机制）
    v2_rules = prompt_gates.parse_gate_rules(
        "", manifest={"gates": {"cjk_min_ratio": 0}})
    assert prompt_gates.resolve_prompt_language(
        {"usedSkills": ["v2完整"]}, v2_rules) == "英文"
    _save("v2无声明", "# V3\n正文")
    assert prompt_gates.resolve_prompt_language({"usedSkills": ["v2无声明"]}) == "中文"


def test_input_present_objective_detection():
    assert gates_inputs.input_present({}, "script") is False
    assert gates_inputs.input_present({"uploadedDocs": [{"name": "a"}]}, "script") is True
    assert gates_inputs.input_present({"analysis": {"summary": "x"}}, "script") is True
    assert gates_inputs.input_present(
        {"assets": [{"type": "audio", "url": "/workspace/assets/bgm.wav"}]}, "music") is True
    assert gates_inputs.input_present(
        {"assets": [{"type": "file", "url": "/workspace/assets/a.mp4"}]}, "video") is True
    assert gates_inputs.input_present({"assets": []}, "image") is False
