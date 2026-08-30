# -*- coding: utf-8 -*-
"""整改批 1.4：治理门禁 canary 制度化（acceptance.py GATES 全部道双向可失败性）。

元教训：恒真基线/恒真门禁（永不失败）比缺门禁更危险——批次 1.1 的 scaffold
与 FRONTEND_OVER_BASELINE 动态自算事故同构。本文件为 GATES 表每道门禁
各写「故意违规 → 非 0 + 干净语料 → 0」双向断言：违规侧证明门禁真的会咬人，
干净侧证明不反噬。扫描面一律 monkeypatch 指向 tmp_path，不触碰真实仓库。

退役编排符号（check_legacy_orchestration FORBIDDEN 清单）在本文件内一律
运行时拼接（如 "Flow"+"GateSet"），防本门禁自身扫描命中本文件。
"""
import json
import sys
from pathlib import Path

import pytest

# ---------- 门禁表完整性（防静默掉闸） ----------

_EXPECTED_GATE_NAMES = [
    "contract", "file_lines", "file_lines_frontend",
    "semantic_colors", "func_imports", "category_keys",
    "legacy_orchestration", "layer_imports", "ref_integrity",
    "scaffold_registry", "cov_ratchet", "fe_cov_ratchet",
    "css_size",
]


def test_acceptance_gates_table_complete():
    """GATES 表门禁一个不少（掉闸 = 治理失明）。"""
    from scripts.acceptance import GATES
    assert [name for name, _ in GATES] == _EXPECTED_GATE_NAMES


# ---------- 1) contract：gen_api_types --check ----------

def test_canary_contract_drift_fails(monkeypatch, tmp_path):
    from scripts.gen_api_types import main
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])
    stale = tmp_path / "api.generated.ts"
    stale.write_text("// stale content\n", encoding="utf-8")
    assert main(out_path=str(stale)) == 1


def test_canary_contract_consistent_passes(monkeypatch):
    from scripts.gen_api_types import main, OUT_PATH
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])
    assert main(out_path=OUT_PATH) == 0


# ---------- 2) prompt_budget 已随 C1a 裁决 2026-08-31 退役删除（组5） ----------


# ---------- 3/4) file_lines 后端档 + 前端档 ----------

def test_canary_file_lines_oversize_fails(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.py").write_text("x = 1\n" * (gate.MAX_LINES + 1), encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SRC", src)
    assert gate.main() == 1


def test_canary_file_lines_clean_passes(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    src = tmp_path / "src"
    src.mkdir()
    (src / "small.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SRC", src)
    assert gate.main() == 0


def test_canary_file_lines_frontend_oversize_fails(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "big.tsx").write_text("// x\n" * (gate.FRONTEND_MAX_LINES + 1),
                                 encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.run_frontend() == 1


def test_canary_file_lines_frontend_clean_passes(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "small.tsx").write_text("// x\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.run_frontend() == 0


# ---------- 5) semantic_colors ----------

def _colors_scaffold(tmp_path, monkeypatch):
    import scripts.check_semantic_colors as gate
    styles = tmp_path / "styles"
    styles.mkdir()
    monkeypatch.setattr(gate, "STYLES", styles)
    monkeypatch.setattr(gate, "WHITELIST", {})
    monkeypatch.setattr(gate, "TOTAL_BASELINE", 0)
    monkeypatch.setattr(gate, "FONT_SIZE_WHITELIST", {})
    monkeypatch.setattr(gate, "FONT_SIZE_TOTAL_BASELINE", 0)
    monkeypatch.setattr(gate, "Z_INDEX_WHITELIST", {})
    monkeypatch.setattr(gate, "Z_INDEX_TOTAL_BASELINE", 0)
    return gate, styles


def test_canary_semantic_colors_hardcode_fails(tmp_path, monkeypatch):
    gate, styles = _colors_scaffold(tmp_path, monkeypatch)
    (styles / "rogue.css").write_text(".a { color: #ff0000; }\n", encoding="utf-8")
    assert gate.main() == 1


def test_canary_semantic_colors_token_passes(tmp_path, monkeypatch):
    gate, styles = _colors_scaffold(tmp_path, monkeypatch)
    (styles / "clean.css").write_text(
        ".a { color: var(--color-danger); }\n", encoding="utf-8")
    assert gate.main() == 0


# ---------- 6) func_imports ----------

def _func_imports_scaffold(tmp_path, monkeypatch, py_text, baseline=""):
    import scripts.check_func_imports as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text(py_text, encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text(baseline, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", str(tmp_path))
    monkeypatch.setattr(gate, "BASELINE", str(base))
    monkeypatch.setattr(sys, "argv", ["check_func_imports.py"])
    return gate


def test_canary_func_imports_new_hit_fails(tmp_path, monkeypatch):
    gate = _func_imports_scaffold(
        tmp_path, monkeypatch, "def f():\n    import os\n    return os\n")
    assert gate.main() == 1


def test_canary_func_imports_top_level_passes(tmp_path, monkeypatch):
    gate = _func_imports_scaffold(
        tmp_path, monkeypatch, "import os\n\ndef f():\n    return os\n")
    assert gate.main() == 0


# ---------- 8) category_keys ----------

def test_canary_category_keys_literal_fails(tmp_path, monkeypatch):
    import scripts.check_category_keys as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text('x = "keyElements"\n', encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIR", pkg)
    assert gate.main() == 1


def test_canary_category_keys_constant_passes(tmp_path, monkeypatch):
    import scripts.check_category_keys as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("x = CAT_KEY_ELEMENTS\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIR", pkg)
    assert gate.main() == 0


# ---------- 9) legacy_orchestration（退役符号运行时拼接） ----------

def test_canary_legacy_orchestration_revival_fails(tmp_path, monkeypatch):
    import scripts.check_legacy_orchestration as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    symbol = "Flow" + "GateSet"  # 运行时拼接，防本文件自身被门禁命中
    (pkg / "bad.py").write_text(f"x = '{symbol}'\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ["src/video_agent"])
    assert gate.main() == 1


def test_canary_legacy_orchestration_clean_passes(tmp_path, monkeypatch):
    import scripts.check_legacy_orchestration as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "ok.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ["src/video_agent"])
    assert gate.main() == 0


# ---------- 10) layer_imports（整改批 3.3：层间导入方向闸） ----------

def test_canary_layer_imports_reverse_dependency_fails(tmp_path, monkeypatch):
    import scripts.check_layer_imports as gate
    pkg = tmp_path / "src" / "video_agent" / "tools"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from src.video_agent.web.skill_docs import list_skill_docs\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ("src/video_agent/tools",))
    assert gate.main() == 1


def test_canary_layer_imports_clean_passes(tmp_path, monkeypatch):
    import scripts.check_layer_imports as gate
    pkg = tmp_path / "src" / "video_agent" / "tools"
    pkg.mkdir(parents=True)
    (pkg / "ok.py").write_text(
        "from src.video_agent.storage.media_urls import resolve_injectable_url\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ("src/video_agent/tools",))
    assert gate.main() == 0


# ---------- 11) ref_integrity（doc_pointers + arch_anchors 合并） ----------
def _doc_pointers_scaffold(tmp_path, monkeypatch):
    import scripts.check_doc_pointers as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    # 锚点布局：合并后 main() 含宪法锚点校验，脚手架锚点指向 tmp 内真文件，
    # 防真实 ANCHORS 在 tmp ROOT 下恒失败（防静默掉闸的双向可失败性不变）。
    (pkg / "anchor.py").write_text("AnchorSym = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "ARCHITECTURE_RULES.md").write_text(
        "## 文件地图\n```\n```\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "ADR_DIR", tmp_path / "docs" / "adr")
    monkeypatch.setattr(gate, "ARCH_RULES", tmp_path / "ARCHITECTURE_RULES.md")
    monkeypatch.setattr(gate, "PKG", pkg)
    monkeypatch.setattr(gate, "ANCHORS",
                        [("Rule1", "src/video_agent/anchor.py", "AnchorSym")])
    return gate, pkg


def test_canary_doc_pointers_dead_pointer_fails(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# 参考 core/ghost_module.py 实现\nx = 1\n",
                              encoding="utf-8")
    assert gate.main() == 1


def test_canary_doc_pointers_clean_passes(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 0


def test_canary_ref_integrity_anchor_missing_fails(tmp_path, monkeypatch):
    """宪法锚点合并后仍双向可失败：承重路径缺失即漂移。"""
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gate, "ANCHORS", [("Rule1", "src/video_agent/core/ghost.py", "Ghost")])
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 1


def test_canary_ref_integrity_anchor_symbol_missing_fails(tmp_path, monkeypatch):
    """半漂移（文件在、承重符号搬走）必须命中。"""
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "moved.py").write_text("OtherSym = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        gate, "ANCHORS", [("Rule1", "src/video_agent/moved.py", "AnchorSym")])
    assert gate.main() == 1


def test_canary_ref_integrity_anchor_intact_passes(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 0


# ---------- 11) scaffold_registry（含元 canary：字面基线 ≠ 恒真） ----------

def test_canary_scaffold_baseline_literal_matches_reality():
    """批次 1.1 裁决钉死：基线是字面常量 8 且与实测计数一致
    （动态自算 = 恒真基线，见 check_file_lines FRONTEND_OVER_BASELINE 同构事故）。"""
    from src.video_agent.core import scaffold_registry as sreg
    assert sreg.SCAFFOLD_COUNT_BASELINE == 8
    assert isinstance(sreg.SCAFFOLD_COUNT_BASELINE, int)
    assert len(sreg.scaffold_entries()) == sreg.SCAFFOLD_COUNT_BASELINE


def test_canary_scaffold_registry_count_increase_fails(monkeypatch):
    import scripts.check_scaffold_registry as gate
    from src.video_agent.core import scaffold_registry as sreg
    monkeypatch.setattr(gate, "SCAFFOLD_COUNT_BASELINE",
                        len(sreg.scaffold_entries()) - 1)
    assert gate.main() == 1


def test_canary_scaffold_registry_clean_passes():
    import scripts.check_scaffold_registry as gate
    assert gate.main() == 0


# ---------- 12/13) cov_ratchet / fe_cov_ratchet ----------

def _write_cov_xml(path: Path, line_rate: float):
    path.write_text(f'<coverage line-rate="{line_rate}" version="1"/>',
                    encoding="utf-8")


def test_canary_cov_ratchet_regression_fails(tmp_path, monkeypatch):
    import scripts.check_cov_ratchet as gate
    xml = tmp_path / "coverage.xml"
    _write_cov_xml(xml, 0.50)
    base = tmp_path / "cov_baseline.txt"
    base.write_text("60.00\n", encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE_FILE", base)
    monkeypatch.setattr(sys, "argv",
                        ["check_cov_ratchet.py", "--cov-xml", str(xml)])
    assert gate.main() == 1


def test_canary_cov_ratchet_improved_passes(tmp_path, monkeypatch):
    import scripts.check_cov_ratchet as gate
    xml = tmp_path / "coverage.xml"
    _write_cov_xml(xml, 0.50)
    base = tmp_path / "cov_baseline.txt"
    base.write_text("40.00\n", encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE_FILE", base)
    monkeypatch.setattr(sys, "argv",
                        ["check_cov_ratchet.py", "--cov-xml", str(xml)])
    assert gate.main() == 0


def _write_fe_summary(path: Path, pct: float):
    path.write_text(json.dumps({"total": {"lines": {"pct": pct}}}),
                    encoding="utf-8")


def test_canary_fe_cov_ratchet_regression_fails(tmp_path, monkeypatch):
    import scripts.check_fe_cov_ratchet as gate
    summary = tmp_path / "coverage-summary.json"
    _write_fe_summary(summary, 50.0)
    base = tmp_path / "fe_cov_baseline.txt"
    base.write_text("63.00\n", encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE_FILE", base)
    monkeypatch.setattr(sys, "argv",
                        ["check_fe_cov_ratchet.py", "--summary", str(summary)])
    assert gate.main() == 1


def test_canary_fe_cov_ratchet_improved_passes(tmp_path, monkeypatch):
    import scripts.check_fe_cov_ratchet as gate
    summary = tmp_path / "coverage-summary.json"
    _write_fe_summary(summary, 50.0)
    base = tmp_path / "fe_cov_baseline.txt"
    base.write_text("40.00\n", encoding="utf-8")
    monkeypatch.setattr(gate, "BASELINE_FILE", base)
    monkeypatch.setattr(sys, "argv",
                        ["check_fe_cov_ratchet.py", "--summary", str(summary)])
    assert gate.main() == 0


# ---------- scan_skills --gate 诊断扫描（内容卫生/语言声明探针双向钉死） ----------
# 原第 14 道门禁 skill_tool_names 已随批 A 退役（2026-08-29 用户裁决删工具名
# 白名单，审核报告 §7 第 5 条）；保留的内容卫生/语言声明探针降级为纯诊断脚本，
# 退出码双向行为仍钉死，防诊断函数自身恒真/恒假。

def _skills_gate_scaffold(tmp_path, monkeypatch, md_name, md_text):
    import scripts.scan_skills as gate
    skills = tmp_path / "data" / "skills"
    # 批 3 单一包形态：<slug>/SKILL.md；name/description 注册期必填，
    # name 取正文 H1 与显示名口径一致。
    slug = md_name[:-3] if md_name.endswith(".md") else md_name
    pkg = skills / slug
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        f"---\nname: {md_text.splitlines()[0].lstrip('# ').strip()}\n"
        f"description: 诊断扫描测试桩\n---\n" + md_text, encoding="utf-8")
    # run_gate 按 __file__ 相对定位 data/skills：指向 tmp 布局
    monkeypatch.setattr(gate, "__file__", str(tmp_path / "scripts" / "scan_skills.py"))
    return gate


def test_canary_skill_scan_priority_claim_fails(tmp_path, monkeypatch):
    """内容卫生探针：优先级宣称 → 退出码 1（FAIL 路径仍会咬人）。"""
    gate = _skills_gate_scaffold(
        tmp_path, monkeypatch, "违规样例.md",
        "# 违规\n正文宣称：优先级最高。\n")
    assert gate.run_gate() == 1


def test_canary_skill_scan_clean_passes(tmp_path, monkeypatch):
    """干净仓 → 退出码 0（不反噬）。"""
    gate = _skills_gate_scaffold(
        tmp_path, monkeypatch, "干净样例.md",
        "# 干净\n> 调用规则：测试\n正文遵守强制基线式表述。\n")
    assert gate.run_gate() == 0
