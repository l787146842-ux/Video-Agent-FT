# -*- coding: utf-8 -*-
"""整改批 1.3：死代码清偿防复活回归（参照 test_shell_payoff 模式）。

清偿对象（全部零消费死代码，先 grep 全库确认引用面再删）：
1) src/video_agent/skills/ 整包（内置类注册器，零导入）；
2) 节点失败记账原语两枚（bump/clear）及消费链：运行时初始化、
   账本 setdefault、重试引导卡派生段、阈值配置、专属测试文件；
3) 定义变更检测旗标（单点写入零消费）；
4) 硬中断种类字符串常量（零消费死词汇；注意上下文 hard_break
   布尔字段是活语义，不在清偿范围）；
5) 阶段裁剪声明键（manifest 校验键本就不含它，模板/docstring/
   测试声明全部清除）。

留痕注释一律不含上述符号字面（全文扫描断言依赖此约定，
与 check_legacy_orchestration 不命中退役留痕注释的惯例一致）。
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/video_agent"
TESTS = ROOT / "tests"

# 退役符号（字面扫描；运行时拼接仅用于门禁 canary，不在本文件出现）
_BANNED_LITERALS = (
    "node_attempts",
    "bump_node_attempt",
    "clear_node_attempt",
    "node_retry_guidance",
    "NODE_RETRY_GUIDANCE",
    "retry_guidance",
    "definition_change_detected",
    "KIND_HARD_BREAK",
    "spec_stage_trim",
    "SkillRegistry",
    "BaseSkill",
)


def _iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


# ---------- 整包/整文件删除不得复活 ----------

def test_skills_package_deleted():
    assert not (SRC / "skills").exists()


def test_node_attempts_guidance_test_deleted():
    assert not (TESTS / "unit/test_node_attempts_guidance.py").exists()


# ---------- 退役符号不得在源码/测试中复活 ----------

def test_banned_symbols_absent_from_src():
    hits = []
    for path in _iter_py_files(SRC):
        text = path.read_text(encoding="utf-8")
        for literal in _BANNED_LITERALS:
            if literal in text:
                hits.append(f"{path}: {literal}")
    assert not hits, "退役符号复活: " + "; ".join(hits)


def test_banned_symbols_absent_from_tests():
    hits = []
    for path in _iter_py_files(TESTS):
        if path.name == Path(__file__).name:
            continue  # 本防复活文件自身含字面清单
        text = path.read_text(encoding="utf-8")
        for literal in _BANNED_LITERALS:
            if literal in text:
                hits.append(f"{path}: {literal}")
    assert not hits, "退役符号复活: " + "; ".join(hits)


def test_banned_symbols_absent_from_scripts():
    """scripts/archive/ 为历史归档，按仓库惯例不扫；其余治理脚本须干净。"""
    hits = []
    for path in _iter_py_files(ROOT / "scripts"):
        if "archive" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for literal in _BANNED_LITERALS:
            if literal in text:
                hits.append(f"{path}: {literal}")
    assert not hits, "退役符号复活: " + "; ".join(hits)


# ---------- 配置与基线快照连带钉死 ----------

def test_config_threshold_removed():
    from src.video_agent.config import Settings
    field_names = {f.name for f in Settings.__dataclass_fields__.values()}
    assert "node_retry_guidance_threshold" not in field_names


def test_workflow_baseline_snapshot_clean():
    """workflow_1111_baseline 快照不含记账键，恢复路径零影响。"""
    import json
    baseline = json.loads(
        (TESTS / "fixtures/workflow_1111_baseline.json").read_text(encoding="utf-8"))
    text = json.dumps(baseline)
    for literal in ("node_attempts", "definition_change_detected"):
        assert literal not in text


def test_round_end_kinds_only_live_pair():
    """种类常量只剩活消费的两枚（arbitrable/post_process）。"""
    from src.video_agent.core import round_end_policies as rep
    assert rep.KIND_ARBITRABLE == "arbitrable"
    assert rep.KIND_POST_PROCESS == "post_process"
    assert not hasattr(rep, "KIND_HARD_BREAK")


@pytest.mark.parametrize("key", ["spec_wizard", "spec_gate", "script_required"])
def test_manifest_flow_bool_keys_unchanged(key):
    """manifest 校验键清单不因本次清删除漂移（裁剪键本就不在其中）。"""
    from src.video_agent.skill_runtime import manifest_schema
    assert key in manifest_schema._FLOW_BOOL_KEYS
