# -*- coding: utf-8 -*-
"""P2-4：目录包 Skill 资源按需加载（fail-closed）与 scan 资源探针。

试点数据：水墨风格武侠短片（存量唯一目录包；用户裁决的 G1 例外
拆分产物——附属参考内容拆至同名目录 references/ 下）。
口径钉死：
① registry 包形态识别（package_root/resource_manifest）；
② resolve_skill_resource：清单内放行 / 清单外与路径穿越一律拒绝 /
   单文件形态拒绝（fail-closed）；
③ read_skill 工具端到端：resource 参数返回资源全文、拒绝语义一致；
④ scan_skills.package_resource_warn_probe：真实包零告警、悬空指针/
   孤儿资源命中（诊断性质，不阻断退出码）。
"""
import importlib.util
import pathlib

from src.video_agent.skill_runtime import registry
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"

_spec = importlib.util.spec_from_file_location(
    "scan_skills_p24", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)

PKG = "水墨风格武侠短片"
REF1 = "references/五行特效与爆发态提示词库.md"
REF2 = "references/武打剪辑律动与多轨音效设计参考.md"
SINGLE = "李安美学风格短片"  # 存量单文件形态对照


# ---------- ① 包形态识别 ----------


def test_package_entry_shape():
    entry = registry.resolve_entry(PKG)
    assert entry is not None, "目录包 Skill 未注册（镜像/同步链断裂）"
    assert entry.package_root is not None
    assert entry.package_root.name == PKG
    assert set(entry.resource_manifest) == {REF1, REF2}


def test_single_file_entry_has_no_package_root():
    entry = registry.resolve_entry(SINGLE)
    assert entry is not None
    assert entry.package_root is None
    assert entry.resource_manifest == []


# ---------- ② resolve_skill_resource fail-closed ----------


def test_resolve_resource_manifest_hit():
    for ref in (REF1, REF2):
        path, err = registry.resolve_skill_resource(PKG, ref)
        assert err == "" and path is not None, ref
        assert path.is_file(), ref


def test_resolve_resource_outside_manifest_rejected():
    path, err = registry.resolve_skill_resource(PKG, "references/不存在.md")
    assert path is None
    assert "fail-closed" in err and "资源清单" in err


def test_resolve_resource_traversal_rejected():
    for bad in ("../README.md", "references/../水墨风格武侠短片.md", ".."):
        path, err = registry.resolve_skill_resource(PKG, bad)
        assert path is None, bad
        assert "非法" in err, bad


def test_resolve_resource_single_file_rejected():
    path, err = registry.resolve_skill_resource(SINGLE, REF1)
    assert path is None
    assert "单文件" in err


# ---------- ③ read_skill 工具端到端 ----------


async def test_read_skill_resource_end_to_end():
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name=PKG, resource=REF1))
    assert res.success, res.error
    assert res.data["resource"] == REF1
    assert "五行" in res.data["content"]


async def test_read_skill_resource_denied_outside_manifest():
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name=PKG, resource="references/不存在.md"))
    assert not res.success
    assert "fail-closed" in res.error


async def test_read_skill_resource_denied_single_file():
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name=SINGLE, resource=REF1))
    assert not res.success
    assert "单文件" in res.error


# ---------- ④ scan 资源探针（WARN，诊断性质） ----------


def _real_doc(slug: str) -> pathlib.Path:
    single = SKILLS_DIR / f"{slug}.md"
    return single if single.exists() else SKILLS_DIR / slug / f"{slug}.md"


def test_scan_probe_real_package_clean():
    """真实试点包：指针全部落地、资源全有指针 → 零告警。"""
    from src.video_agent.skill_runtime import frontmatter

    f = _real_doc(PKG)
    content = f.read_text(encoding="utf-8")
    manifest, body, _err = frontmatter.split_frontmatter(content)
    assert scan_skills.package_resource_warn_probe(PKG, f, body, manifest) == []
    # 单文件存量无指针无 scripts → 同样零告警（不误报）
    f2 = _real_doc(SINGLE)
    content2 = f2.read_text(encoding="utf-8")
    manifest2, body2, _err2 = frontmatter.split_frontmatter(content2)
    assert scan_skills.package_resource_warn_probe(
        SINGLE, f2, body2, manifest2) == []


def test_scan_probe_dangling_pointer_and_orphan(tmp_path):
    pkg = tmp_path / "demo"
    (pkg / "references").mkdir(parents=True)
    doc = pkg / "demo.md"
    doc.write_text(
        '正文 read_skill(name="demo", resource="references/missing.md") 指引\n',
        encoding="utf-8")
    (pkg / "references" / "orphan.md").write_text("孤儿", encoding="utf-8")
    warns = scan_skills.package_resource_warn_probe(
        "demo", doc, doc.read_text(encoding="utf-8"), None)
    assert any("悬空" in w for w in warns), warns
    assert any("孤儿" in w for w in warns), warns


def test_scan_probe_scripts_declaration_existence(tmp_path):
    pkg = tmp_path / "demo"
    pkg.mkdir()
    doc = pkg / "demo.md"
    doc.write_text("正文", encoding="utf-8")
    manifest = {"scripts": {"build": "render.py"}}
    warns = scan_skills.package_resource_warn_probe(
        "demo", doc, "正文", manifest)
    assert any("scripts" in w and "不存在" in w for w in warns), warns
    (pkg / "render.py").write_text("# noop", encoding="utf-8")
    assert scan_skills.package_resource_warn_probe(
        "demo", doc, "正文", manifest) == []
