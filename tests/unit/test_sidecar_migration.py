# -*- coding: utf-8 -*-
"""0818 架构板正批 B0/B4：sidecar 声明外置迁移回归。

钉死：
① 迁移幂等剥离文档 manifest 围栏，章节解析不变（S6 同构断言）；
② registry 声明唯一源 = sidecar（B4 退役文档通道）；
③ sidecar 体检（依赖悬空报出）；
④ 阶段表 skill 感知裁剪；全量产品 sidecar 体检零告警。
"""
from pathlib import Path

from src.video_agent.skill_runtime import sidecar
from src.video_agent.web.skill_docs import split_skill_sections

_DOC_WITH_MANIFEST = """
```json skill_manifest
{
  "gates": {"require_subtitle": true},
  "flow": {"spec_gate": true, "stage_executors": {"1": ["script_analyze"]}},
  "pause": {"stage_pause": true}
}
```
skill_name: "迁移测试桩"
skill_description: "测试。"
<planner>
**全流程阶段与依赖关系：**
1. 读取并分析剧本 → **resource_prepare_and_analyze**。
2. 组装时间线 → **video_assembler**。

**依赖关系：** 2→1。
</planner>
"""


def test_migrate_doc_to_sidecar_strips_fence(tmp_path):
    """B4：迁移剥离文档 manifest 围栏（声明以 sidecar 为准）；章节解析不变。"""
    doc = tmp_path / "迁移测试桩.md"
    doc.write_text(_DOC_WITH_MANIFEST, encoding="utf-8")
    sections_before = split_skill_sections(_DOC_WITH_MANIFEST)

    changed = sidecar.migrate_doc_to_sidecar(doc, directory=tmp_path / "sc")
    assert changed is True

    new_content = doc.read_text(encoding="utf-8")
    assert "skill_manifest" not in new_content
    assert "<planner>" in new_content and "**依赖关系：** 2→1。" in new_content
    assert split_skill_sections(new_content) == sections_before


def test_migrate_idempotent(tmp_path):
    """无围栏文档再跑迁移 = no-op。"""
    doc = tmp_path / "迁移测试桩.md"
    doc.write_text(_DOC_WITH_MANIFEST, encoding="utf-8")
    assert sidecar.migrate_doc_to_sidecar(doc, directory=tmp_path / "sc") is True
    assert sidecar.migrate_doc_to_sidecar(doc, directory=tmp_path / "sc") is False


def test_load_sidecar_absent_returns_none(tmp_path):
    assert sidecar.load_sidecar("不存在的桩", directory=tmp_path) is None


def test_registry_prefers_sidecar_over_doc(monkeypatch):
    """双读优先级：sidecar 存在时覆盖文档 manifest（B4 退役文档通道前的一致入口）。"""
    from src.video_agent.skill_runtime import registry

    sentinel = {"flow": {"spec_gate": True}, "pause": {"stage_pause": True}}
    monkeypatch.setattr(sidecar, "load_sidecar", lambda slug, directory=None: sentinel)
    entry = registry._load_entry("AI-短剧一站式生成")
    assert entry is not None
    assert entry.manifest == sentinel


def test_registry_sidecar_only_source(monkeypatch):
    """B4：sidecar 存在=声明源；缺失=零声明（不再回落文档）。"""
    from src.video_agent.skill_runtime import registry

    sentinel = {"flow": {"spec_gate": True}, "pause": {"stage_pause": True}}
    monkeypatch.setattr(sidecar, "load_sidecar", lambda slug, directory=None: sentinel)
    entry = registry._load_entry("AI-短剧一站式生成")
    assert entry is not None
    assert entry.manifest == sentinel

    monkeypatch.setattr(sidecar, "load_sidecar", lambda slug, directory=None: None)
    entry2 = registry._load_entry("AI-短剧一站式生成")
    assert entry2 is not None
    assert entry2.manifest is None


# ---------- B4：sidecar 体检 + 阶段表 skill 感知 ----------

def test_sidecar_validate_dangling_deps():
    """依赖引用悬空（步骤/前置不在 steps）→ 体检报出；无 sidecar = 合法。"""
    bad = {"flow": {"steps": {"1": "a"}, "dependencies": {"2": [1], "1": [9]}}}
    issues = sidecar.validate_sidecar(bad)
    assert any("2" in i for i in issues)
    assert any("9" in i for i in issues)
    assert sidecar.validate_sidecar(None) == []


def test_all_product_sidecars_validate_clean():
    """全量盘点钉死：产品 Skill 的 sidecar 体检零告警。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR

    for f in sorted(Path(SKILL_DOCS_DIR).glob("*.md")):
        issues = sidecar.validate_sidecar(sidecar.load_sidecar(f.stem))
        assert issues == [], f"{f.stem}: {issues}"


def test_stage_table_skill_aware_trimming():
    """阶段表 skill 感知：无 video_assembler 章节的 Skill 无组装阶段；
    spec_wizard 冻结值决定规格阶段存在性。"""
    from src.video_agent.core import pipeline_orchestrator as po

    keys = [s.key for s in po.stage_table("商品宣传短片")]
    assert "assembly" not in keys
    assert "spec" in keys
    keys2 = [s.key for s in po.stage_table("宣言式概念短片")]
    assert "assembly" in keys2
