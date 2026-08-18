# -*- coding: utf-8 -*-
"""0818 架构板正批 B0：sidecar 声明外置迁移回归（零行为变化钉死）。

钉死：
① 迁移等价——sidecar 内容 == 旧文档通道清洗结果（双读零行为变化）；
② 文档去围栏后章节解析不变（S6 同构断言）；
③ 迁移幂等；
④ registry 双读：sidecar 优先、文档 manifest 回落。
"""
from pathlib import Path

from src.video_agent.skill_runtime import sidecar
from src.video_agent.web.skill_docs import parse_skill_manifest, split_skill_sections

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


def test_migrate_doc_to_sidecar_equivalence(tmp_path):
    """sidecar 内容 == 旧文档通道清洗结果；文档去围栏；章节解析不变。"""
    doc = tmp_path / "迁移测试桩.md"
    doc.write_text(_DOC_WITH_MANIFEST, encoding="utf-8")
    sections_before = split_skill_sections(_DOC_WITH_MANIFEST)
    expected = parse_skill_manifest(_DOC_WITH_MANIFEST)
    assert expected is not None

    changed = sidecar.migrate_doc_to_sidecar(doc, directory=tmp_path / "sc")
    assert changed is True

    got = sidecar.load_sidecar("迁移测试桩", directory=tmp_path / "sc")
    assert got == expected, "sidecar 必须与旧通道清洗结果逐键相等"

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


def test_registry_falls_back_to_doc_manifest(monkeypatch):
    """sidecar 缺失时回落文档 manifest（迁移前/未迁移 Skill 行为不变）。"""
    from src.video_agent.skill_runtime import registry

    monkeypatch.setattr(sidecar, "load_sidecar", lambda slug, directory=None: None)
    entry = registry._load_entry("AI-短剧一站式生成")
    assert entry is not None
    assert entry.manifest == parse_skill_manifest(entry.content)
