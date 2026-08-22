# -*- coding: utf-8 -*-
"""skill_manifest 声明块回归（S1 清偿：通用层被单一 Skill 污染事故）。

核心语义：
1) 引擎对业务流程一无所知——未声明 manifest 的 Skill 只保留客观结构防护；
2) 闸机/向导/裁剪等平台行为由 manifest 声明驱动；
3) manifest 与旧 gate_rules/pause_rules 并存时 manifest 优先；
4) data/skills 全部存量 Skill 的 manifest 快照稳定（防单 Skill 再带偏）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import prompt_gates
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.web.action_executor import StateOperationExecutor

_MANIFEST_ALL_ON = (
    "```json skill_manifest\n"
    '{"gates": {"require_duration": true, "require_subtitle": true,'
    ' "require_camera_language": true, "require_audio_layer": true},'
    ' "flow": {"spec_wizard": true, "spec_stage_trim": true},'
    ' "pause": {"stage_pause": true}}\n'
    "```\n"
)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path / "ws"))
    StateManager.reset_instance()


# ---------- 解析层（任务#5：声明迁文档头部 frontmatter；
# 体检/加载语义由 test_sidecar_migration 覆盖） ----------


def test_manifest_gates_override_legacy_gate_rules():
    """并存时 frontmatter 声明优先（冲突键覆盖旧 gate_rules 块）"""
    content = (
        "```json gate_rules\n" '{"require_duration": true}' "\n```\n"
    )
    rules = prompt_gates.parse_gate_rules(
        content, manifest={"gates": {"require_duration": False}})
    assert rules["require_duration"] is False


def test_default_gate_rules_business_gates_off():
    rules = prompt_gates.parse_gate_rules("")
    for key in ("require_duration", "require_subtitle",
                "require_camera_language", "require_audio_layer"):
        assert rules[key] is False


# ---------- flow 开关 ----------

def test_skill_flow_enabled_requires_declaration():
    from src.video_agent.skill_runtime import frontmatter

    sd.save_skill_doc("有声明", "# A\n正文")
    frontmatter.write_manifest(
        "有声明", {"flow": {"spec_wizard": True, "spec_stage_trim": True}})
    sd.save_skill_doc("无声明", "# B\n> 调用规则：测试\n正文")
    assert registry.skill_flow_enabled("有声明", "spec_wizard") is True
    assert registry.skill_flow_enabled("有声明", "spec_stage_trim") is True
    assert registry.skill_flow_enabled("无声明", "spec_wizard") is False
    assert registry.skill_flow_enabled("不存在", "spec_wizard") is False
    assert registry.skill_flow_enabled("", "spec_wizard") is False


# ---------- 端到端：英文锁定 Skill 不再被语言闸打回 ----------

def test_english_prompt_passes_when_cjk_ratio_declared_low():
    rules = prompt_gates.parse_gate_rules(
        "", manifest={"gates": {"cjk_min_ratio": 0}})
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "A monolithic black slab rises over the desert at dawn, extreme wide shot, "
        "slow push-in, hard rim light, no subtitles. This is a long English body "
        "prompt that clearly exceeds the minimum character budget for shots.",
        "shot", rules=rules)
    assert ok and not hard


# ---------- 端到端：规格暂停闸只对声明 spec_wizard 的 Skill 生效 ----------

async def _run_spec_write(svc, skill_name: str):
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.skill_name = skill_name
    svc.state_dict["documents"] = []
    reply = ('规格已保存。\n```studio-actions\n'
             '[{"action":"write_document","name":"制片规格.md","content":"画幅：16:9"}]\n```',
             "stop")

    async def llm(system_prompt, messages, stream_hook=None):
        return reply[0], reply[1], 0

    return await run_agent_loop(
        "写规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )


async def test_spec_pause_gate_silent_without_manifest(svc):
    """S1 核心回归：未声明 spec_wizard 的 Skill 写完规格文档，系统不再
    注入测试 Skill 专属的规格审阅卡/向导（引擎不预设流程）。"""
    sd.save_skill_doc("外来流程", "# 外来\n> 调用规则：测试\n正文")
    result = await _run_spec_write(svc, "外来流程")
    assert result.confirmation != prompt_gates.SPEC_DOC_PAUSED_MSG
    assert "尚待您选定" not in (result.confirmation or "")


async def test_spec_pause_gate_fires_with_manifest(svc, monkeypatch):
    """4444 方案乙：声明 spec_wizard 的 Skill，模型手写规格被拒收
    （规格由系统拼装）；审阅卡走 spec_review_pending 路径（见 test_99）。"""
    from src.video_agent.skill_runtime import frontmatter

    sd.save_skill_doc("向导流程", "# 向导\n正文")
    frontmatter.write_manifest("向导流程", {
        "gates": {"require_duration": True, "require_subtitle": True,
                  "require_camera_language": True, "require_audio_layer": True},
        "flow": {"spec_wizard": True, "spec_stage_trim": True},
        "pause": {"stage_pause": True},
    })
    monkeypatch.setattr(prompt_gates, "_channel_groups", lambda: [])
    svc.state_dict["usedSkills"] = ["向导流程"]
    result = await _run_spec_write(svc, "向导流程")
    assert not any(
        prompt_gates.is_spec_doc_name(str(d.get("name") or ""))
        for d in svc.state_dict.get("documents", [])
    )


# ---------- 端到端：规格前置警告只对声明 spec_gate 的 Skill 生效 ----------

def test_spec_gate_warning_requires_declaration(svc):
    """814Gb/0818：规格前置不再在执行器层硬拦（_spec_gate_ok 退役），
    顺序控制归编排器；无论是否声明 spec_gate 均照常建组。"""
    sd.save_skill_doc(
        "有规格闸",
        "# A\n```json skill_manifest\n" '{"flow": {"spec_gate": true}}\n' "```\n正文",
    )
    sd.save_skill_doc("无规格闸", "# B\n> 调用规则：测试\n正文")
    svc.state_dict["documents"] = []

    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.skill_name = "有规格闸"
    assert not hasattr(ex, "_spec_gate_ok")
    assert ex.execute([{
        "action": "add_group", "group_type": "keyElement", "title": "Element_闸",
    }]) == 1


# ---------- 暂停声明：manifest pause 是唯一源（guard + lint） ----------

def test_stage_pause_recognizes_manifest():
    from src.video_agent.skill_runtime.guard import skill_requires_stage_pause
    from src.video_agent.skill_runtime import frontmatter

    # 无关键词、仅 frontmatter 声明 → 生效
    sd.save_skill_doc("仅清单暂停", "# A\n正文")
    frontmatter.write_manifest("仅清单暂停", {"pause": {"stage_pause": True}})
    assert skill_requires_stage_pause("仅清单暂停") is True
    # frontmatter 显式 false 覆盖『何时暂停』关键词（声明优先）
    sd.save_skill_doc("清单关闭", "# B\n何时暂停：每阶段后。")
    frontmatter.write_manifest("清单关闭", {"pause": {"stage_pause": False}})
    assert skill_requires_stage_pause("清单关闭") is False


def test_lint_pause_warning_keyword_driven():
    """任务#5：编辑期暂停提示看正文关键词与 frontmatter 声明；
    文档内 manifest 块不再消费并显式告知。"""
    content = (
        "# A\n```json skill_manifest\n" '{"pause": {"stage_pause": true}}\n' "```\n正文"
    )
    result = sd.lint_skill_content(content)
    assert any("不再消费" in w for w in result["warnings"])
    ok = sd.lint_skill_content("# A\n**何时暂停**：每阶段后\n正文")
    assert not any("暂停声明" in w for w in ok["warnings"])


# ---------- 存量 Skill 快照（防未来单 Skill 再带偏） ----------

# 迁移后的预期声明（文件名 → flow 开关）；未列出的键一律预期 False/None
# （「剧本生视频需上传剧本」已于 4444 整文件删除，不再入快照）
_SKILL_FLOW_SNAPSHOT = {}
# 明确不声明任何 flow 开关的 Skill（引擎对它们零预设）
_SKILL_FLOW_OFF = (
    "3D国漫古装精品短剧", "AI-短剧一站式生成", "人文纪录短片", "剧情短片音色参考",
    "叙事驱动的美学视频", "古风甜宠短剧", "商品宣传短片", "多人对话访谈",
    "宣言式概念短片", "故事驱动型视频", "未来科幻真人电影", "李安美学风格短片",
    "水墨风格武侠短片", "视频拉片复刻", "音乐MV需上传音乐",
)


def test_real_skills_manifest_snapshot(monkeypatch):
    """真实 data/skills 快照：把目录切回真实路径重新同步注册表，断言各
    Skill 的 manifest 声明与迁移预期一致；新增 Skill 必须在此登记预期。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", REAL_DIR)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        for slug, expected_flow in _SKILL_FLOW_SNAPSHOT.items():
            entry = registry.get_entry(slug)
            assert entry is not None, f"Skill 未注册: {slug}"
            assert entry.manifest is not None, f"Skill 缺 manifest: {slug}"
            for key, want in expected_flow.items():
                assert bool((entry.manifest.get("flow") or {}).get(key, False)) is want, \
                    f"{slug} flow.{key} 预期 {want}"
        for slug in _SKILL_FLOW_OFF:
            entry = registry.get_entry(slug)
            assert entry is not None, f"Skill 未注册: {slug}"
            flow = ((entry.manifest or {}).get("flow") or {})
            # 0818 B4：spec_wizard 现值已冻结进 frontmatter（存量视频 Skill 全为 true）
            assert flow.get("spec_wizard") is True, f"{slug} 冻结值应为 true"
            # 存量视频 Skill 流程均含规格步骤：spec_gate 与迁移前行为等价
            assert flow.get("spec_gate") is True, f"{slug} 应声明 spec_gate"
        # 暂停声明迁入 manifest（旧 pause_rules 块已删）
        for slug in ("剧情短片音色参考",):
            pause = ((registry.get_entry(slug).manifest or {}).get("pause") or {})
            assert pause.get("stage_pause") is True, f"{slug} 应声明 pause.stage_pause"
        # ke-prog 测试残留：允许无 manifest
    finally:
        registry.reset_registry()


# 814H9 影响面快照（13.7 登记）：客观检测只命中流程含「上传/分析剧本」的 Skill
# （豪华技能为测试桩，R2 已迁 tests/fixtures/skills，不再占生产快照名额）
_SCRIPT_REQUIRED_ON = (
    "3D国漫古装精品短剧", "AI-短剧一站式生成", "剧本生视频需上传剧本",
)
# 剧情短片音色参考：任务#6 用户裁决剧本可选（script_required=false，
# planner 可代写），自 ON 清单移入 OFF
_SCRIPT_REQUIRED_OFF = ("宣言式概念短片", "音乐MV需上传音乐", "商品宣传短片",
                        "剧情短片音色参考")


def test_script_required_snapshot(monkeypatch):
    """814H9：script_required 客观检测影响面快照——需剧本 Skill 命中、其余零影响。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", REAL_DIR)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        for slug in _SCRIPT_REQUIRED_ON:
            assert registry.script_required_active(slug), f"{slug} 应检测为需剧本"
        for slug in _SCRIPT_REQUIRED_OFF:
            assert not registry.script_required_active(slug), f"{slug} 不应检测为需剧本"
    finally:
        registry.reset_registry()
