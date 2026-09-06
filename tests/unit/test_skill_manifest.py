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
from src.video_agent.core.action_executor import StateOperationExecutor


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


# ---------- flow 开关 ----------

def test_gates_key_and_language_floor_both_retired_english_passes():
    """C1a 裁决 2026-08-31 的 gates.cjk_min_ratio 调整轴，连同平台语言
    地板已随 2026-09-06 用户裁决整体退役：英文正文不再被闸机打回
    （提示词语言归文档层：Skill 要求 / 规格显式声明经优先级链生效）。"""
    ok, hard, _ = prompt_gates.validate_prompt_write(
        "A monolithic black slab rises over the desert at dawn, extreme wide shot, "
        "slow push-in, hard rim light, no subtitles. This is a long English body "
        "prompt that clearly exceeds the minimum character budget for shots.",
        "shot")
    assert ok and not any("英文" in h or "中文正文" in h for h in hard)


# ---------- 端到端：规格暂停闸只对声明 spec_wizard 的 Skill 生效 ----------

async def _run_spec_write(svc, skill_name: str):
    ex = StateOperationExecutor(svc, gate_enabled=True)
    ex.skill_name = skill_name
    svc.state_dict["documents"] = []
    reply = ('规格已保存。\n```studio-actions\n'
             '[{"action":"write_document","name":"制片规格.md","content":"画幅：16:9"}]\n```',
             "stop")

    async def llm(system_prompt, messages, stream_hook=None):
        return reply[0], reply[1], 0, 0.0, {}

    return await run_agent_loop(
        "写规格", llm_call=llm, context_builder=lambda: "ctx", executor=ex, history=[],
    )


async def test_spec_pause_gate_silent_without_manifest(svc):
    """S1 核心回归：未声明流程开关的 Skill 写完规格文档，系统不再注入规格审阅卡/向导；
    规格硬边界已随用户裁决 2026-08-31 退役（D-08 清偿），模型暂停由自主决定。"""
    sd.save_skill_doc("外来流程", "# 外来\n> 调用规则：测试\n正文")
    result = await _run_spec_write(svc, "外来流程")
    assert "尚待您选定" not in (result.confirmation or "")


# test_spec_pause_gate_fires_with_manifest 已随用户裁决 2026-08-31 退役删除（D-08 清偿）：
# spec_wizard 声明与规格手写拒收机制整体退役，模型手写规格正常落盘。


# ---------- 端到端：规格前置警告只对声明 spec_gate 的 Skill 生效 ----------

# test_spec_gate_warning_requires_declaration 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨执行器层规格前置判定（含 _spec_gate_ok 退役断言）随执行器家族整体退役；
# 顺序控制归 Skill 流程与阶段裁剪，机械闸仅存 platform 层（GATE_RULES 5 条）。


# ---------- 文档内 manifest 块不再消费（声明唯一源 = 文档头部 frontmatter） ----------
# （暂停声明 lint 已随 pause 声明化石链整链删除：frontmatter pause / 正文
#   pause_rules 声明均无运行时消费者，提示只会诱导作者补一个空声明。）


def test_lint_skill_manifest_block_not_consumed():
    """任务#5：文档内 manifest 块不再消费并显式告知。"""
    content = (
        "# A\n```json skill_manifest\n" '{"pause": {"stage_pause": true}}\n' "```\n正文"
    )
    result = sd.lint_skill_content(content)
    assert any("不再消费" in w for w in result["warnings"])


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
    """真实 data/skills 快照（2026-08-31 用户裁决 Flova 对齐后）：
    存量包 frontmatter 只留 name/description/source，机械开关键清零。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", REAL_DIR)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        for slug in _SKILL_FLOW_OFF:
            entry = registry.get_entry(slug)
            assert entry is not None, f"Skill 未注册: {slug}"
            assert entry.manifest is not None, f"Skill 缺 manifest: {slug}"
            extra = set(entry.manifest.keys()) - {"name", "description", "source"}
            assert not extra, f"{slug} frontmatter 应只剩最小键，实际多出: {sorted(extra)}"
        # ke-prog 测试残留：允许无 manifest
    finally:
        registry.reset_registry()


# 814H9 影响面快照（耦合行登记）：客观检测只命中流程含「上传/分析剧本」的 Skill
# （豪华技能为测试桩，R2 已迁 tests/fixtures/skills，不再占生产快照名额）
_SCRIPT_REQUIRED_ON = (
    "3D国漫古装精品短剧", "AI-短剧一站式生成",
)
# 剧情短片音色参考：任务#6 用户裁决剧本可选（script_required=false，
# planner 可代写），自 ON 清单移入 OFF
_SCRIPT_REQUIRED_OFF = ("宣言式概念短片", "音乐MV需上传音乐", "商品宣传短片",
                        "剧情短片音色参考")


def test_bare_keys_parsed_as_minimal_declaration():
    """无 --- 包裹的头部连续 skill_name:/skill_description: 行 = 最小声明：
    映射 name/description、剩成对引号、正文原样保留。"""
    from src.video_agent.skill_runtime.frontmatter import split_frontmatter

    content = (
        'skill_name: "视频拉片复刻"\n'
        'skill_description: "参考现有视频生成最终视频。"\n'
        '<planner>\n流程散文\n</planner>\n'
    )
    manifest, body, err = split_frontmatter(content)
    assert err == ""
    assert manifest == {
        "name": "视频拉片复刻", "description": "参考现有视频生成最终视频。"}
    assert body.startswith("<planner>") and "流程散文" in body
    # 无裸键的普通文档行为不变（零声明）
    m2, body2, err2 = split_frontmatter("# 标题\n正文")
    assert m2 is None and err2 == "" and body2.startswith("# 标题")
    # --- 包裹的 frontmatter 优先级不变（不走裸键探测）
    m3, _, err3 = split_frontmatter("---\nname: A\n---\n正文")
    assert err3 == "" and m3 == {"name": "A"}


def test_bare_keys_document_registers_end_to_end():
    """端到端：Flova 裸键文档可注册（注册期 name/description 必填满足）。"""
    sd.save_skill_doc(
        "裸键包",
        'skill_name: 裸键包\nskill_description: 导入兼容桩\n'
        '<planner>\n1. 分析\n</planner>\n')
    entry = registry.register_skill("裸键包")
    assert entry is not None
    assert entry.name == "裸键包"
