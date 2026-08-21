# -*- coding: utf-8 -*-
"""\u9632\u590d\u6d3b\u95e8\u7981\uff080818 \u67b6\u6784\u677f\u6b63\u6279 B5\uff09\uff1a\u5df2\u9000\u5f79\u7f16\u6392\u673a\u5236\u7b26\u53f7\u96f6\u6b8b\u7559\u3002

\u72b6\u6001\u9a71\u52a8\u7f16\u6392\u91cd\u6784\uff08B0-B4\uff09\u673a\u68b0\u9000\u5f79\u4e86\u8001\u673a\u5236\uff1b\u65e0\u95e8\u7981\u5219\u590d\u6d3b\u53ef\u80fd\u56de\u6f6e\u2014\u2014
\u672c\u811a\u672c\u626b\u63cf src/tests/scripts \u4e2d\u9000\u5f79\u7b26\u53f7\uff0c\u547d\u4e2d\u4efb\u4e00\u5373\u975e\u96f6\u9000\u51fa\u3002
\u9000\u5f79\u6e05\u5355\uff08\u7b26\u53f7\u975e\u6982\u5ff5\uff0c\u540c\u540d\u590d\u7528\u5373\u89c6\u4e3a\u590d\u6d3b\uff09\uff1a
- FlowGateSet \u95f8\u673a\u94fe / skill_pipeline_plan \u8c03\u5ea6\u5de5\u5177 / auto_retry \u76f2\u91cd\u8bd5
- prepend_script_summary/maybe_prepend \u603b\u7ed3\u6ce8\u5165\u94fe / skill_declares_summary
- dag.py \u6b63\u5219\u901a\u9053\uff08parse_steps \u7b49\uff09/ parse_skill_manifest \u6587\u6863\u901a\u9053
- \u4e3b\u4f53\u56de\u5f52\uff08ADR-0004\uff09\uff1aruntime \u673a\u68b0\u76f4\u8dd1/\u5ba1\u6279\u76f4\u8dd1\u9a71\u52a8\u7b26\u53f7\uff08\u6a21\u578b\u6c38\u8fdc\u552f\u4e00\u884c\u52a8\u4e3b\u4f53\uff09
spec_pause_card/spec_collect_card\uff08\u89c4\u683c\u5411\u5bfc\uff0c\u4e0d\u53d8\u57fa\u7ebf\uff09\u4e0d\u5728\u6e05\u5355\u5185\u3002
\u8f93\u51fa\u7eaf ASCII\uff08\u9a8c\u6536\u4e71\u7801\u8bef\u8bfb\u6559\u8bad\uff09\u3002\u7528\u6cd5\uff1apython scripts/check_legacy_orchestration.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ["src/video_agent", "tests", "scripts"]
SELF = pathlib.Path(__file__).resolve()

FORBIDDEN = re.compile(
    r"FlowGateSet|prepend_script_summary|maybe_prepend|skill_pipeline_plan"
    r"|auto_retry|parse_skill_manifest|skill_declares_summary"
    r"|parse_steps\b|parse_dependencies\b|topo_batches|resolve_steps_and_deps"
    r"|pipeline_status_from|lint_planner_dag|render_pipeline_detail"
    r"|pending_action_log|Agent 正在规划本步动作"
    r"|PAUSE_MSG_MAX|compress_pause_message|FLOW_STEP_SHORT_TITLES|_DIM_ALIAS"
    r"|flush_pending_doc_card|emit_pending_doc_card|spec_doc_card_pending"
    # 主体回归（ADR-0004，审核整改批4）：runtime 机械直跑/审批直跑退役，
    # 模型永远唯一行动主体；直跑驱动符号防复活
    r"|drive_turn|direct_run_nodes|_run_direct_stage|_run_approval_pause|compose_stage_pause"
)


def main() -> int:
    hits = []
    for d in SCAN_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if p.resolve() == SELF:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append((p.relative_to(ROOT).as_posix(), i, line.strip()[:70]))
    if hits:
        for rel, n, line in hits[:20]:
            print(f"[check_legacy_orchestration]   {rel}:{n}: {line}")
        print(
            f"[check_legacy_orchestration] FAIL: {len(hits)} legacy-orchestration reference(s). "
            "Retired by 0818 state-driven orchestration batch; extend "
            "pipeline_orchestrator/sidecar instead of reviving old mechanisms."
        )
        return 1
    print("[check_legacy_orchestration] PASS: no legacy orchestration symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
