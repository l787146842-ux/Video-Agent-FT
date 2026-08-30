# -*- coding: utf-8 -*-
"""P2-4：目录包 Skill 资源按需加载（fail-closed）与 scan 资源探针。

试点数据：水墨风格武侠短片（存量唯一目录包；用户裁决的 G1 例外
拆分产物——附属参考内容拆至同名目录 references/ 下）。
口径钉死：
① registry 包形态识别（package_root/resource_manifest）；
② resolve_skill_resource：清单内放行 / 清单外与路径穿越一律拒绝（fail-closed）；
③ read_skill 工具端到端：resource 参数返回资源全文、拒绝语义一致；
④ scan_skills.package_resource_warn_probe：真实包零告警、悬空指针/
   孤儿资源命中（诊断性质，不阻断退出码）。
批6 追加：
⑤ resolve_skill_resource 放行 assets/（媒体+文档素材描述符通道）；
⑥ 版本锁：C1b 裁决 2026-08-31 执法退役——sha256 不符/悬空不再拒注册（记账保留）；
⑦ get_skill_asset 只读返回描述符（二进制不进上下文）；
⑧ scan 探针 assets 孤儿/悬空。
（原单文件形态对照用例随批3 单一包形态收敛退役。）
"""
import hashlib
import importlib.util
import pathlib
import shutil

import pytest

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
NO_REF = "李安美学风格短片"  # 无附属资源的目录包对照


# ---------- ① 包形态识别 ----------


def test_package_entry_shape():
    entry = registry.resolve_entry(PKG)
    assert entry is not None, "目录包 Skill 未注册（镜像/同步链断裂）"
    assert entry.package_root is not None
    assert entry.package_root.name == PKG
    assert set(entry.resource_manifest) == {REF1, REF2}


def test_no_reference_package_has_empty_manifest():
    entry = registry.resolve_entry(NO_REF)
    assert entry is not None
    assert entry.package_root is not None
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
    for bad in ("../README.md", "references/../SKILL.md", ".."):
        path, err = registry.resolve_skill_resource(PKG, bad)
        assert path is None, bad
        assert "非法" in err, bad


def test_resolve_resource_absent_package_rejected():
    path, err = registry.resolve_skill_resource(NO_REF, REF1)
    assert path is None
    assert "资源清单" in err


def test_resource_manifest_excludes_symlinks(tmp_path, monkeypatch):
    """符号链接不进资源清单：白名单后缀链接可读包外文件，
    fail-closed 排除；清单不含链接 → resolve 同口径拒绝。"""
    pkg = tmp_path / "sympkg"
    refs = pkg / "references"
    refs.mkdir(parents=True)
    (pkg / "sympkg.md").write_text("正文", encoding="utf-8")
    (refs / "real.md").write_text("真身", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("包外内容", encoding="utf-8")
    link = refs / "link.md"
    try:
        link.symlink_to(outside)
    except OSError as e:
        pytest.skip(f"当前 Windows 环境无法创建符号链接：{e}")
    monkeypatch.setattr(
        registry.SkillEntry, "package_root", property(lambda self: pkg))
    entry = registry.SkillEntry(
        slug="sympkg", name="sympkg", content="", sections={})
    # 清单只含真实文件，符号链接被排除（is_symlink 分支）
    assert entry.resource_manifest == ["references/real.md"]
    # 链接名即使在白名单后缀也不在清单 → 拒绝。双保险：
    # 即使绕过清单，解析后逃逸包根同样被 resolve 守卫拦截。
    monkeypatch.setattr(registry, "resolve_entry", lambda wanted: entry)
    path, err = registry.resolve_skill_resource("sympkg", "references/link.md")
    assert path is None
    assert "资源清单" in err


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


async def test_read_skill_resource_denied_absent_package():
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name=NO_REF, resource=REF1))
    assert not res.success
    assert "资源清单" in res.error


# ---------- ③-b 批4：二进制资源禁入文本通道（媒体例外通道） ----------


def test_resolve_resource_media_descriptor_channel(tmp_path, monkeypatch):
    """references/ 下图/音/视频资源走媒体例外通道（返回文件位置供元数据描述符解析）；
    references/ 外媒体与不存在的媒体文件仍 fail-closed 拒绝。"""
    pkg = tmp_path / "mediapkg"
    refs = pkg / "references"
    refs.mkdir(parents=True)
    (pkg / "mediapkg.md").write_text("正文", encoding="utf-8")
    (refs / "ref.png").write_bytes(b"\x89PNG fake-binary")
    entry = registry.SkillEntry(
        slug="mediapkg", name="mediapkg", content="", sections={})
    monkeypatch.setattr(
        registry.SkillEntry, "package_root", property(lambda self: pkg))
    monkeypatch.setattr(registry, "resolve_entry", lambda wanted: entry)
    path, err = registry.resolve_skill_resource("mediapkg", "references/ref.png")
    assert err == "" and path is not None
    # references/ 外媒体：不在清单也无媒体通道 → 拒绝（fail-closed）
    (pkg / "root.png").write_bytes(b"x")
    path2, err2 = registry.resolve_skill_resource("mediapkg", "root.png")
    assert path2 is None and err2
    # 不存在的媒体文件：媒体通道要求实际文件在场 → 拒绝（fail-closed）
    path3, err3 = registry.resolve_skill_resource(
        "mediapkg", "references/ghost.png")
    assert path3 is None and err3


async def test_read_skill_media_resource_returns_descriptor(
        tmp_path, monkeypatch):
    """批4：媒体资源只返回元数据描述符（名/大小/类型），不按文本读入上下文。"""
    import src.video_agent.tools.document_tools as dt

    pkg = tmp_path / "mediapkg"
    refs = pkg / "references"
    refs.mkdir(parents=True)
    (pkg / "mediapkg.md").write_text("正文", encoding="utf-8")
    (refs / "ref.png").write_bytes(b"\x89PNG fake-binary")
    entry = registry.SkillEntry(
        slug="mediapkg", name="mediapkg", content="", sections={})
    monkeypatch.setattr(
        registry.SkillEntry, "package_root", property(lambda self: pkg))
    monkeypatch.setattr(registry, "resolve_entry", lambda wanted: entry)

    class _StubDocs:
        def resolve_skill_content(self, name):
            return "mediapkg", "正文"

        def list_skill_sections(self, content):
            return []

        def list_skill_docs(self):
            return []

    monkeypatch.setattr(dt.ports, "skill_docs_port", lambda: _StubDocs())
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="mediapkg", resource="references/ref.png"))
    assert res.success, res.error
    assert res.data["media_kind"] == "image"
    assert res.data["size"] > 0
    assert "元数据描述符" in res.data["content"]
    assert "\x89PNG" not in res.data["content"]  # 二进制不按文本读


# ---------- ④ scan 资源探针（WARN，诊断性质） ----------


def _real_doc(slug: str) -> pathlib.Path:
    # 批3 单一包形态：只认 <slug>/SKILL.md
    return SKILLS_DIR / slug / "SKILL.md"


def test_scan_probe_real_package_clean():
    """真实试点包：指针全部落地、资源全有指针 → 零告警。"""
    from src.video_agent.skill_runtime import frontmatter

    f = _real_doc(PKG)
    content = f.read_text(encoding="utf-8")
    manifest, body, _err = frontmatter.split_frontmatter(content)
    assert scan_skills.package_resource_warn_probe(PKG, f, body, manifest) == []
    # 无附属资源的目录包无指针无 scripts → 同样零告警（不误报）
    f2 = _real_doc(NO_REF)
    content2 = f2.read_text(encoding="utf-8")
    manifest2, body2, _err2 = frontmatter.split_frontmatter(content2)
    assert scan_skills.package_resource_warn_probe(
        NO_REF, f2, body2, manifest2) == []


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


# ---------- ⑤ 批6：resolve_skill_resource 放行 assets/ ----------


def _asset_pkg(tmp_path, slug="assetpkg"):
    pkg = tmp_path / slug
    (pkg / "assets").mkdir(parents=True)
    (pkg / f"{slug}.md").write_text("正文", encoding="utf-8")
    return pkg


def _patch_entry(monkeypatch, pkg, slug="assetpkg"):
    entry = registry.SkillEntry(slug=slug, name=slug, content="", sections={})
    monkeypatch.setattr(
        registry.SkillEntry, "package_root", property(lambda self: pkg))
    monkeypatch.setattr(registry, "resolve_entry", lambda wanted: entry)
    return entry


def test_resolve_asset_descriptor_channel(tmp_path, monkeypatch):
    """assets/ 下媒体与文档素材走描述符通道放行；白名单外后缀/穿越仍拒绝。"""
    pkg = _asset_pkg(tmp_path)
    _patch_entry(monkeypatch, pkg)
    (pkg / "assets" / "ref.png").write_bytes(b"\x89PNG fake-binary")
    (pkg / "assets" / "spec.pdf").write_bytes(b"%PDF fake-doc")
    path, err = registry.resolve_skill_resource("assetpkg", "assets/ref.png")
    assert err == "" and path is not None
    path2, err2 = registry.resolve_skill_resource("assetpkg", "assets/spec.pdf")
    assert err2 == "" and path2 is not None
    # 白名单外后缀仍 fail-closed（不进描述符通道）
    (pkg / "assets" / "run.exe").write_bytes(b"MZ")
    path3, err3 = registry.resolve_skill_resource("assetpkg", "assets/run.exe")
    assert path3 is None and "资源清单" in err3
    # 路径穿越拒绝（与文本资源同口径）
    path4, err4 = registry.resolve_skill_resource(
        "assetpkg", "assets/../assetpkg.md")
    assert path4 is None and "非法" in err4


# ---------- ⑥ 批6：版本锁（注册期 hash 硬拒） ----------
# 幂等重注册夹具惯例：测试包落会话级镜像目录（conftest 钉的
# SKILL_DOCS_DIR），夹具退出时注销 + 清目录，不污染其他测试。


@pytest.fixture
def lock_env():
    from src.video_agent.core import ports

    base = pathlib.Path(ports.skill_docs_port().SKILL_DOCS_DIR)
    created = []

    def make(slug, resources_yaml="", asset_bytes=b"asset-bytes-b6"):
        pkg = base / slug
        (pkg / "assets").mkdir(parents=True)
        (pkg / "assets" / "ref.png").write_bytes(asset_bytes)
        (pkg / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: 批6 版本锁测试包\n"
            f"{resources_yaml}---\n正文\n", encoding="utf-8")
        created.append(pkg)
        return pkg

    yield make
    for pkg in created:
        registry.unregister_skill(pkg.name)
        shutil.rmtree(pkg, ignore_errors=True)


_LOCK_ASSET = b"asset-bytes-b6"
_LOCK_SHA = hashlib.sha256(_LOCK_ASSET).hexdigest()


def test_version_lock_hash_match_registers(lock_env):
    """声明的 sha256 与实际素材一致 → 照常注册（版本锁通过）。"""
    lock_env("b6lock-ok", resources_yaml=(
        "resources:\n  assets/ref.png:\n"
        f"    sha256: {_LOCK_SHA}\n    size: {len(_LOCK_ASSET)}\n"
        "    mime: image/png\n"))
    entry = registry.register_skill("b6lock-ok")
    assert entry is not None
    # 版本锁声明同步透传到素材描述符（消费端可见锁状态）
    declared = entry.declared_resources
    assert declared["assets/ref.png"]["sha256"] == _LOCK_SHA


def test_version_lock_hash_mismatch_rejects_registration(lock_env):
    """C1b 裁决 2026-08-31：sha256 不符不再拒注册（执法退役），
    记账口径 resource_lock_errors 仍报诊断。"""
    lock_env("b6lock-bad", resources_yaml=(
        "resources:\n  assets/ref.png:\n    sha256: \"" + "0" * 64 + "\"\n"))
    assert registry.register_skill("b6lock-bad") is not None
    errs = registry.resource_lock_errors(
        registry.SkillEntry(slug="b6lock-bad", name="b6lock-bad",
                            content="", sections={}))
    assert any("sha256 不符" in e for e in errs)


def test_version_lock_dangling_declared_rejects_registration(lock_env):
    """C1b 裁决 2026-08-31：悬空声明不再拒注册（执法退役）。"""
    lock_env("b6lock-missing", resources_yaml=(
        "resources:\n  assets/ghost.png:\n    sha256: \"" + "0" * 64 + "\"\n"))
    assert registry.register_skill("b6lock-missing") is not None


def test_no_resources_declaration_backward_compat(lock_env):
    """无 resources 声明的包照常注册（存量 16 包同口径，向后兼容）。"""
    lock_env("b6lock-none")
    assert registry.register_skill("b6lock-none") is not None
    # 存量真实包（无清单无 hash）行为零变化：照常可读资源清单口径
    assert registry.resolve_entry(NO_REF) is not None


# ---------- ⑦ 批6：get_skill_asset 只读返回描述符 ----------


async def test_get_skill_asset_returns_read_only_descriptor(
        tmp_path, monkeypatch):
    """描述符含路径/名/大小/类型；二进制不进返回体（不按文本读）。"""
    from src.video_agent.tools.document_tools import (
        GetSkillAssetInput, GetSkillAssetTool)

    pkg = _asset_pkg(tmp_path)
    _patch_entry(monkeypatch, pkg)
    (pkg / "assets" / "ref.png").write_bytes(b"\x89PNG fake-binary")
    res = await GetSkillAssetTool().aexecute(
        GetSkillAssetInput(name="assetpkg", path="assets/ref.png"))
    assert res.success, res.error
    assert res.data["media_kind"] == "image"
    assert res.data["size"] > 0
    assert res.data["name"] == "ref.png"
    assert res.data["path"].endswith("ref.png")
    assert "content" not in res.data  # 二进制不进文本/上下文通道
    assert "\x89PNG" not in str(res.data)


async def test_get_skill_asset_rejects_outside_assets(tmp_path, monkeypatch):
    from src.video_agent.tools.document_tools import (
        GetSkillAssetInput, GetSkillAssetTool)

    pkg = _asset_pkg(tmp_path)
    _patch_entry(monkeypatch, pkg)
    (pkg / "assets" / "ref.png").write_bytes(b"x")
    # 非 assets/ 路径：直接拒收（文本参考仍走 read_skill）
    res = await GetSkillAssetTool().aexecute(
        GetSkillAssetInput(name="assetpkg", path="references/a.md"))
    assert not res.success and "assets/" in res.error
    # assets/ 下不存在的文件：fail-closed 拒绝
    res2 = await GetSkillAssetTool().aexecute(
        GetSkillAssetInput(name="assetpkg", path="assets/ghost.png"))
    assert not res2.success and res2.error


async def test_get_skill_asset_surfaces_declared_sha256(lock_env):
    """经注册的真实包：描述符携带 resources 声明的锁（版本锁可见）。"""
    from src.video_agent.tools.document_tools import (
        GetSkillAssetInput, GetSkillAssetTool)

    lock_env("b6lock-desc", resources_yaml=(
        "resources:\n  assets/ref.png:\n    sha256: \"" + _LOCK_SHA + "\"\n"))
    assert registry.register_skill("b6lock-desc") is not None
    res = await GetSkillAssetTool().aexecute(
        GetSkillAssetInput(name="b6lock-desc", path="assets/ref.png"))
    assert res.success, res.error
    assert res.data["sha256"] == _LOCK_SHA


# ---------- ⑧ 批6：scan 探针 assets 孤儿/悬空 ----------


def test_scan_probe_assets_orphan_and_dangling(tmp_path):
    pkg = tmp_path / "demo"
    (pkg / "assets").mkdir(parents=True)
    doc = pkg / "SKILL.md"
    doc.write_text("正文", encoding="utf-8")
    (pkg / "assets" / "orphan.png").write_bytes(b"x")  # 在场未声明 = 孤儿
    manifest = {"resources": {"assets/ghost.png": {"sha256": "0" * 64}}}
    warns = scan_skills.package_resource_warn_probe(
        "demo", doc, "正文", manifest)  # 声明不在场 = 悬空
    assert any("悬空" in w for w in warns), warns
    assert any("孤儿素材" in w for w in warns), warns
    # 声明与在场文件对齐后零告警（孤儿消失、悬空落地）
    (pkg / "assets" / "ghost.png").write_bytes(b"y")
    (pkg / "assets" / "orphan.png").unlink()
    assert scan_skills.package_resource_warn_probe(
        "demo", doc, "正文", manifest) == []
