# -*- coding: utf-8 -*-
"""frontmatter 扩展逃生舱约定钉死测试（对齐 Agent Skills 开放标准）。

审核改进方案 kind 体系要求：预留 metadata/前缀字段做扩展逃生舱，方便
将来与 Agent Skills 开放标准互转。manifest_schema 显式约定：

钉死契约：
① 顶层 metadata 自由 map（string→string）任意形状校验器一律忽略——
   零 WARN 零错误（不拒注册）；
② x- 前缀顶层键同样一律忽略（零 WARN 零错误）；与合法业务键共存时
   不影响其他键的校验结论；
③ 既有校验路径不受逃生舱影响：僵尸键 WARN 过渡告警、gates 未知键
   fail-hard、kind 未知值开放注册降级 WARN、废除 flow 键 fail-hard；
④ 注册链路：带 metadata/x- 键的 Skill 文档正常注册且注册期零告警；
⑤ scan_skills 一致性探针不误报逃生舱键（frontmatter 剥离口径）。
"""
import importlib.util
import io
from pathlib import Path

import pytest
from loguru import logger

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import manifest_schema as ms
from src.video_agent.skill_runtime import frontmatter, registry

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "scan_skills_probe", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)


# ---------- 逃生舱键判定归一入口 ----------


@pytest.mark.parametrize("key,expected", [
    ("metadata", True),
    ("x-acme-review", True),
    ("x-", True),                 # 前缀本身即命中（键名建议带后缀防冲突）
    ("metadata_extra", False),    # 不做隐式前缀匹配
    ("Metadata", False),          # 大小写敏感
    ("x", False),
    ("gates", False),
    ("", False),
    (42, False),
])
def test_is_extension_key_classification(key, expected):
    assert ms.is_extension_key(key) is expected


# ---------- ① metadata 自由 map：校验器一律忽略 ----------


@pytest.mark.parametrize("raw", [
    {"version": "1.2", "author": "acme"},       # 标准 string→string 自由 map
    {"acme.market_id": "m-42"},                 # 厂商前缀防冲突约定键
    {},                                         # 空 map
    "标量也算逃生舱",                            # 任意形状忽略（不校验形状）
    42,
    ["列表形状"],
])
def test_metadata_free_map_ignored_without_warning(raw):
    issues = ms.validate_manifest_data({"metadata": raw})
    assert issues == [], f"metadata 逃生舱不得产生任何问题: {issues}"
    errors, warnings = ms.split_issue_warnings(issues)
    assert errors == [] and warnings == []


# ---------- ② x- 前缀键：校验器一律忽略 ----------


@pytest.mark.parametrize("manifest", [
    {"x-acme-review": "pending"},
    {"x-flag": True, "x-count": 3, "x-nested": {"a": 1}},
    {"x-": "仅前缀"},
])
def test_x_prefixed_keys_ignored_without_warning(manifest):
    issues = ms.validate_manifest_data(manifest)
    assert issues == []
    assert ms.split_issue_warnings(issues) == ([], [])


def test_extension_keys_coexist_with_business_keys():
    """逃生舱键与合法业务键共存：整体零问题，业务键校验结论不受影响。"""
    manifest = {
        "schema_version": 3,
        "kind": "pipeline",
        "version": "1.0",
        "metadata": {"version": "1.2", "acme.market_id": "m-42"},
        "x-acme-review": "pending",
    }
    assert ms.validate_manifest_data(manifest) == []
    # 共存时业务键非法仍照常报出（逃生舱不得遮蔽 fail-closed）
    bad = dict(manifest, gates={"unknown_gate": True})
    errors, _ = ms.split_issue_warnings(ms.validate_manifest_data(bad))
    assert any("不是平台登记的闸键" in e for e in errors)


# ---------- ③ 既有 WARN / fail-hard 行为不变 ----------


@pytest.mark.parametrize("manifest,keyword", [
    # gates 未知键 fail-hard（拒注册）
    ({"gates": {"unknown_gate": True}}, "不是平台登记的闸键"),
    # 废除 flow 通道 fail-hard
    ({"flow": {"steps": {"1": "a"}}}, "已废除"),
])
def test_existing_fail_hard_paths_unchanged(manifest, keyword):
    errors, warnings = ms.split_issue_warnings(
        ms.validate_manifest_data(manifest))
    assert errors and any(keyword in e for e in errors)
    assert warnings == []


def test_existing_warn_paths_unchanged():
    """僵尸键 WARN 过渡告警与 kind 开放注册降级 WARN：只告警不拒注册。"""
    zombie = ms.validate_manifest_data(
        {"flow": {"stage_executors": {"1": ["script_analyze"]}}})
    z_errors, z_warnings = ms.split_issue_warnings(zombie)
    assert z_errors == [] and z_warnings

    kind = ms.validate_manifest_data({"kind": "writing"})
    k_errors, k_warnings = ms.split_issue_warnings(kind)
    assert k_errors == [] and any("writing" in w for w in k_warnings)


# ---------- ④ 注册链路：正常注册且注册期零告警 ----------


_DOC = (
    "---\n"
    "name: 逃生舱技能\n"
    "description: 测试桩：metadata/x- 逃生舱键注册链路\n"
    "schema_version: 3\n"
    "kind: pipeline\n"
    "metadata:\n"
    "  version: \"1.2\"\n"
    "  acme.market_id: m-42\n"
    "x-acme-review: pending\n"
    "x-flag: true\n"
    "---\n"
    "# 逃生舱技能\n\n正文。\n"
)


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    yield d
    registry.reset_registry()


def test_register_skill_with_extension_keys_no_warnings(skills_dir):
    """带 metadata/x- 键的 Skill 正常注册：entry 落地、注册期零告警。"""
    # 批3 单一包形态：<slug>/SKILL.md
    pkg = skills_dir / "逃生舱技能"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text(_DOC, encoding="utf-8")
    sink = io.StringIO()
    handler = logger.add(sink, level="WARNING", format="{message}")
    try:
        entry = registry.register_skill("逃生舱技能")
    finally:
        logger.remove(handler)
    assert entry is not None, "逃生舱键不得拒注册"
    out = sink.getvalue()
    assert "frontmatter 告警" not in out, f"注册期不得有声明告警: {out}"
    assert "拒绝注册" not in out
    # 逃生舱键原样透传（frontmatter 活读不预设）
    assert entry.manifest.get("metadata") == {
        "version": "1.2", "acme.market_id": "m-42"}
    assert entry.manifest.get("x-acme-review") == "pending"


def test_frontmatter_roundtrip_preserves_extension_keys(skills_dir):
    """write→load 回环：逃生舱键逐字保留（开放标准互转的透传前提）。"""
    manifest = {
        "kind": "style",
        "metadata": {"version": "2.0"},
        "x-acme-review": "pending",
    }
    frontmatter.write_manifest("回环技能", manifest, directory=skills_dir)
    loaded = frontmatter.load_manifest("回环技能", directory=skills_dir)
    assert loaded == manifest
    assert ms.validate_manifest_data(loaded) == []


# ---------- ⑤ scan_skills 探针不误报逃生舱键 ----------


def test_scan_probe_does_not_flag_extension_keys():
    """一致性探针（--gate 同源 validate_manifest）对逃生舱键零报出；
    工具名白名单扫描先剥离 frontmatter，YAML 键不进入正文扫描面）。"""
    manifest = {
        "metadata": {"version": "1.2", "acme.market_id": "m-42"},
        "x-acme-review": "pending",
    }
    assert scan_skills.manifest_consistency_issues(
        "逃生舱", "正文", manifest) == []
    # frontmatter 剥离后正文为空 → 工具名扫描零命中
    _fm, body, err = frontmatter.split_frontmatter(_DOC)
    assert err == "" and body.startswith("# 逃生舱技能")
    assert scan_skills.tool_whitelist_issues(body, frozenset()) == []
