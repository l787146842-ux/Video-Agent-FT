"""P3-17 提示词工程收尾钉测试（整改批 3.5 修订）：
1. （已删）legacy 路径单注入与 SKILL_RUNTIME_MODE 灰度开关——回退闸随
   批 3.5 fail-hard 退役：通用主路径为唯一路径，legacy/executors 代码与
   settings.skill_runtime 字段均已物理删除，残留环境变量启动即拒；
2. 运行时组装总长遥测：record_sections 落盘样本。
（C1a 裁决 2026-08-31：预算脚本 check_prompt_budget.py 退役删除，
P95 观察项随之下账。）
"""
import json


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
