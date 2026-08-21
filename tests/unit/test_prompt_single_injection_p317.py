"""P3-17 提示词工程收尾钉测试：
1. legacy 路径「全文 + 阶段聚焦重复注入」已合并为单注入——同一章节内容在
   组装结果中仅出现一次（聚焦块退为指针式强调）；
2. SKILL_RUNTIME_MODE 灰度开关（settings.skill_runtime 的计划名环境变量别名，
   缺省 auto 保持现行为）；
3. 运行时组装总长遥测：record_sections 落盘样本 + 预算脚本 P95 只 WARN 不失败。
"""
import importlib.util
import json
import pathlib

from src.video_agent.core.prompt_builder import PromptBuilder

_SECTION_BODY = "SECTION_BODY_提示词写法章节正文_唯一份"
_SKILL_CONTENT = (
    "# 演示 Skill\n\n## 流程规划\n流程正文。\n\n"
    f"## 提示词写法\n{_SECTION_BODY}\n\n## 组装与导出\n组装正文。\n"
)


class _StubDocs:
    """最小 Skill 文档桩：全文解析 + 章节拆分 + 空目录。"""

    def resolve_skill_content(self, name):
        return "演示 Skill", _SKILL_CONTENT

    def split_skill_sections(self, content):
        return {"prompt_draft": _SECTION_BODY}

    def list_skill_docs(self):
        return []


def _prompt_draft_state():
    """有草稿缺提示词 → detect_stage = prompt_draft（聚焦可命中的阶段）。"""
    return {
        "keyElements": [],
        "shots": [{"drafts": [{"prompt": ""}]}],
        "audioItems": [],
    }


def _pb():
    return PromptBuilder(
        lambda: _StubDocs(),
        lambda: "proj",
        lambda: _prompt_draft_state(),
    )


# ---------- 1. legacy 单注入钉死 ----------

def test_legacy_stage_focus_is_pointer_not_duplicate(set_global_setting):
    """legacy 全文直注 + 阶段聚焦指针：章节正文仅出现一次，聚焦头仍在末尾。"""
    set_global_setting("skill_runtime", "legacy")
    block = _pb().build_selected_skill_block("演示 Skill")
    assert block.count(_SECTION_BODY) == 1, "同一章节内容在注入块中只能出现一次"
    assert "【当前阶段重点 · 提示词草案】" in block, "阶段聚焦指针块缺位"
    assert "不再摘录重复" in block


def test_legacy_assembled_prompt_section_appears_once(set_global_setting):
    """组装结果（build_system_prompt）级钉死：章节全文仅一份。"""
    from src.video_agent.core.planner import PlannerContext

    set_global_setting("skill_runtime", "legacy")
    ctx = PlannerContext(use_studio_context=False, skill_name="演示 Skill")
    text = _pb().build_system_prompt(ctx)
    assert text.count(_SECTION_BODY) == 1, "组装结果中同一章节内容仅出现一次"


def test_legacy_focus_empty_when_stage_unknown(set_global_setting):
    """阶段不可探测时聚焦指针为空（行为与旧实现一致，全文仍单份注入）。"""
    set_global_setting("skill_runtime", "legacy")
    pb = PromptBuilder(lambda: _StubDocs(), lambda: "proj", None)
    block = pb.build_selected_skill_block("演示 Skill")
    assert block.count(_SECTION_BODY) == 1
    assert "当前阶段重点" not in block


# ---------- 2. SKILL_RUNTIME_MODE 灰度开关 ----------

def test_skill_runtime_mode_env_alias_and_default(monkeypatch):
    """计划名 SKILL_RUNTIME_MODE 优先，旧名 SKILL_RUNTIME 兼容，缺省 auto。"""
    from src.video_agent.config import Settings

    monkeypatch.setenv("SKILL_RUNTIME_MODE", "legacy")
    monkeypatch.delenv("SKILL_RUNTIME", raising=False)
    assert Settings().skill_runtime == "legacy"

    monkeypatch.delenv("SKILL_RUNTIME_MODE")
    monkeypatch.setenv("SKILL_RUNTIME", "executors")
    assert Settings().skill_runtime == "executors"

    monkeypatch.delenv("SKILL_RUNTIME")
    assert Settings().skill_runtime == "auto", "缺省必须为 auto（现行为不回归）"


# ---------- 3. 运行时组装总长遥测 ----------

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
