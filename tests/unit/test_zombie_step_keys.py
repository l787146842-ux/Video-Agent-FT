# -*- coding: utf-8 -*-
"""僵尸键废除迁移（B-4 补交）钉死测试。

钉死契约：
① manifest_schema：三组僵尸键（stage_executors/step_done_conditions/
   step_short_titles）声明即 WARN 级过渡告警——不拒注册（错误级为零），
   不再校验值形状（键已无消费者）；时序 = 本版本 WARN + 存量迁移清键，
   下一版本升级为 fail-hard（manifest_schema docstring 登记）。
② ZOMBIE_STEP_KEYS 与迁移脚本 ZOMBIE_KEYS 锁源同值（漂移即报）。
③ migrate_zombie_step_keys：dry-run 默认不落盘；--apply 清除僵尸键且
   正文逐字不动、其余声明保留；flow 清空后整键移除；幂等（重跑零命中）。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.video_agent.skill_runtime import manifest_schema as ms

ROOT = Path(__file__).resolve().parents[2]
MIGRATE_SCRIPT = ROOT / "scripts" / "migrate_zombie_step_keys.py"


@pytest.fixture(scope="module")
def migrate_mod():
    spec = importlib.util.spec_from_file_location(
        "migrate_zombie_step_keys", MIGRATE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- ① WARN 过渡告警（不拒注册） ----------


@pytest.mark.parametrize("key", ms.ZOMBIE_STEP_KEYS)
def test_zombie_key_declaration_warns_not_fails(key):
    """声明僵尸键：issues 全部为 WARN 级（split_issue_warnings 错误侧为空）。"""
    issues = ms.validate_manifest_data({"flow": {key: {"1": "任意值"}}})
    assert issues, f"{key} 声明必须被告警"
    errors, warnings = ms.split_issue_warnings(issues)
    assert errors == [], f"{key} 过渡期不得拒注册: {errors}"
    assert any(key in w for w in warnings)
    assert all("下一版本" in w for w in warnings if key in w)


def test_zombie_key_shape_no_longer_validated():
    """键已无消费者：任意形状（非 dict/空值）一律只 WARN，不产生形状错误。"""
    for raw in ("字符串", 42, None, {"1": ""}, [["x"]]):
        errors, _ = ms.split_issue_warnings(
            ms.validate_manifest_data({"flow": {"stage_executors": raw}}))
        assert errors == [], f"形状校验应随僵尸键退役: {raw!r} → {errors}"


def test_zombie_keys_undeclared_clean():
    assert ms.validate_manifest_data({"flow": {"spec_wizard": True}}) == []
    assert ms.validate_manifest_data(None) == []


def test_zombie_keys_tuple_drift_lock(migrate_mod):
    """锁源：schema 与迁移脚本的僵尸键清单同值（漂移即本钉报出）。"""
    assert migrate_mod.ZOMBIE_KEYS == ms.ZOMBIE_STEP_KEYS


# ---------- ② 迁移脚本：dry-run / apply / 幂等 ----------

_SAMPLE_BODY = "# 测试技能\n\n<planner>\n流程正文不动\n</planner>\n"
_SAMPLE_FM = (
    "---\n"
    "flow:\n"
    "  spec_wizard: true\n"
    "  stage_executors:\n"
    "    '1':\n"
    "    - script_analyze\n"
    "  step_done_conditions:\n"
    "    '2': spec\n"
    "  step_short_titles:\n"
    "    '1': 剧本分析\n"
    "pause:\n"
    "  stage_pause: true\n"
    "---\n"
)


def _write_skill(d: Path, slug: str = "测试技能") -> Path:
    f = d / f"{slug}.md"
    f.write_text(_SAMPLE_FM + _SAMPLE_BODY, encoding="utf-8")
    return f


def test_dry_run_reports_without_writing(migrate_mod, tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    f = _write_skill(d)
    before = f.read_text(encoding="utf-8")
    hit, skip = migrate_mod.migrate_file(f, apply=False)
    assert not skip
    assert hit == ["stage_executors", "step_done_conditions", "step_short_titles"]
    assert f.read_text(encoding="utf-8") == before  # dry-run 不落盘


def test_apply_removes_zombie_keys_keeps_body(migrate_mod, tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    f = _write_skill(d)
    hit, skip = migrate_mod.migrate_file(f, apply=True)
    assert hit and not skip
    text = f.read_text(encoding="utf-8")
    for zk in ms.ZOMBIE_STEP_KEYS:
        assert zk not in text
    assert _SAMPLE_BODY.strip() in text  # 正文逐字不动
    assert "spec_wizard: true" in text  # 其余声明保留
    assert "stage_pause: true" in text
    # 迁移后体检：错误级与僵尸 WARN 均清零
    from src.video_agent.skill_runtime import frontmatter

    manifest, _, err = frontmatter.split_frontmatter(text)
    assert not err
    assert ms.validate_manifest_data(manifest) == []
    # 幂等：重跑零命中
    hit2, _ = migrate_mod.migrate_file(f, apply=True)
    assert hit2 == []


def test_apply_removes_flow_when_emptied(migrate_mod, tmp_path):
    """frontmatter 仅含僵尸键：apply 后 flow 整键移除（不留空壳）。"""
    d = tmp_path / "skills"
    d.mkdir()
    f = d / "仅僵尸.md"
    fm = "---\nflow:\n  step_short_titles:\n    '1': 分析\n---\n"
    f.write_text(fm + _SAMPLE_BODY, encoding="utf-8")
    hit, skip = migrate_mod.migrate_file(f, apply=True)
    assert hit == ["step_short_titles"] and not skip
    text = f.read_text(encoding="utf-8")
    assert "flow:" not in text and "step_short_titles" not in text
    assert _SAMPLE_BODY.strip() in text


def test_cli_defaults_to_dry_run(migrate_mod, tmp_path):
    """CLI 默认 dry-run：退出码 0 且文件不落盘（--apply 才真删）。"""
    d = tmp_path / "skills"
    d.mkdir()
    f = _write_skill(d)
    before = f.read_text(encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT), "--dir", str(d)],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "DRY-RUN" in r.stdout
    assert f.read_text(encoding="utf-8") == before
    r2 = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT), "--dir", str(d), "--apply"],
        capture_output=True, text=True)
    assert r2.returncode == 0
    assert "APPLY" in r2.stdout
    assert "stage_executors" not in f.read_text(encoding="utf-8")
