"""P3-17 提示词工程收尾钉测试（整改批 3.5 修订）：
1. （已删）legacy 路径单注入与 SKILL_RUNTIME_MODE 灰度开关——回退闸随
   批 3.5 fail-hard 退役：通用主路径为唯一路径，legacy/executors 代码与
   settings.skill_runtime 字段均已物理删除，残留环境变量启动即拒；
2. 运行时组装总长遥测：record_sections 落盘样本 + 预算脚本 P95 只 WARN 不失败。
"""
import importlib.util
import json
import pathlib


# ---------- 运行时组装总长遥测 ----------

def test_record_sections_persists_sample(tmp_path, monkeypatch):
    """非 pytest 语境下 record_sections 追加落盘样本（ts/project_id/各段字符数）。"""
    from src.video_agent.core import live_metrics

    sample = tmp_path / "prompt_sections.jsonl"
    monkeypatch.setattr(live_metrics, "_SAMPLES_PATH", sample)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    live_metrics.record_sections("proj", {"total": 12345, "skill": 10})
    lines = sample.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["total"] == 12345 and rec["project_id"] == "proj"
    # 内存注册表语义不变（context-usage 端点兜底）
    assert live_metrics.get_sections("proj")["total"] == 12345


def _load_budget_module():
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check_prompt_budget.py"
    spec = importlib.util.spec_from_file_location("check_prompt_budget_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_budget_p95_warn_is_not_hard_gate(tmp_path, monkeypatch, capsys):
    """第 5 观察项：P95 统计正确；超 48k 只 WARN，退出码仍为 0。"""
    mod = _load_budget_module()
    sample = tmp_path / "prompt_sections.jsonl"
    sample.write_text(
        "\n".join(json.dumps({"total": t}) for t in (100, 200, 60000)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SECTIONS_SAMPLE_FILE", sample)
    p95, n = mod.runtime_total_p95()
    assert (p95, n) == (60000, 3)
    rc = mod.main()  # 既有 4 断言照常执行，观察项只打印
    assert rc == 0, "P95 超阈是周报观察项，不作硬门禁"
    out = capsys.readouterr().out
    assert "P95=60000" in out and "WARN" in out


def test_budget_p95_no_sample_keeps_pass(tmp_path, monkeypatch):
    """无样本文件时观察项跳过，既有门禁行为不变。"""
    mod = _load_budget_module()
    monkeypatch.setattr(mod, "SECTIONS_SAMPLE_FILE", tmp_path / "absent.jsonl")
    assert mod.runtime_total_p95() == (None, 0)
    assert mod.main() == 0
