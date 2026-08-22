# -*- coding: utf-8 -*-
"""\u9632\u590d\u6d3b\u95e8\u7981\uff080818 \u67b6\u6784\u677f\u6b63\u6279 B5\uff09\uff1a\u5df2\u9000\u5f79\u7f16\u6392\u673a\u5236\u7b26\u53f7\u96f6\u6b8b\u7559\u3002

\u72b6\u6001\u9a71\u52a8\u7f16\u6392\u91cd\u6784\uff08B0-B4\uff09\u673a\u68b0\u9000\u5f79\u4e86\u8001\u673a\u5236\uff1b\u65e0\u95e8\u7981\u5219\u590d\u6d3b\u53ef\u80fd\u56de\u6f6e\u2014\u2014
\u672c\u811a\u672c\u626b\u63cf src/tests/scripts \u4e2d\u9000\u5f79\u7b26\u53f7\uff0c\u547d\u4e2d\u4efb\u4e00\u5373\u975e\u96f6\u9000\u51fa\u3002
\u9000\u5f79\u6e05\u5355\uff08\u7b26\u53f7\u975e\u6982\u5ff5\uff0c\u540c\u540d\u590d\u7528\u5373\u89c6\u4e3a\u590d\u6d3b\uff09\uff1a
- FlowGateSet \u95f8\u673a\u94fe / skill_pipeline_plan \u8c03\u5ea6\u5de5\u5177 / auto_retry \u76f2\u91cd\u8bd5
- prepend_script_summary/maybe_prepend \u603b\u7ed3\u6ce8\u5165\u94fe / skill_declares_summary
- dag.py 正则通道（parse_steps 等）/ parse_skill_manifest 文档通道
- 五轮 S4 兼容壳：planner 委托方法组 / _split_actions、save_state 别名（P2d 结构性测试减负承接）
- 已迁 prose 防复述：暂停邀请确认（暂停纪律单家）/ 同批发出（暂停时机建议归 Skill）
- 文本协议残留：planner/system.md 字面量（P2e 单轨收敛，协议唯一 = system_fc.md，ADR-0001）
- 主体回归（ADR-0004）：runtime 机械直跑/审批直跑驱动符号（模型永远唯一行动主体）
- 任务#36 B5 执行器一步退役：executors/exec_* 执行器族模块导入
- 任务#27 文本轨残留退役：web.action_parser 文本块解析通道 /
  parse_actions_from_reply / StudioActionExecutor 旧名（已按实际职责更名
  StateOperationExecutor）/ pipeline_orchestrator 拓扑就绪集调度函数
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
    # 五轮 S4 兼容壳清偿防复活（P2d 结构性测试减负：test_shell_payoff/test_stage_batch_execution/
    # test_prompt_relocation_batch3 的文本棘轮下沉至本门禁）+ 已迁 prose 防复述
    r"|def _format_tool_results|def _render_read_result|def _describe_fc_tool"
    r"|def _build_skill_catalog|def _last_user_text|_FEEDBACK_MARKER|_FEEDBACK_FULL_TOOLS"
    r"|_split_actions = split_actions|save_state = save"
    r"|暂停邀请确认|同批发出"
    # P2e 单轨收敛（ADR-0001）：文本协议 system.md 已退役删除，
    # 字面量防复活（协议唯一 = planner/system_fc.md；不命中 system_fc.md）
    r"|planner/system\.md"
    # 任务#36 B5 执行器一步退役：执行器族符号防复活（用 import/模块路径
    # 形式扫描，不命中退役留痕注释；管线阶段改由通用主路径直走平台工具）
    r"|skill_runtime\.executors|skill_runtime\.exec_common|skill_runtime\.exec_spec"
    r"|skill_runtime\.exec_split|skill_runtime\.exec_tools|skill_runtime\.exec_media_gen"
    r"|skill_runtime\.exec_media_writer|skill_runtime\.registration|skill_runtime\.capability"
    r"|skill_runtime\.blackbox|skill_runtime import executors"
    r"|import exec_common|import exec_spec|import exec_split|import exec_tools"
    r"|import exec_media_gen|import exec_media_writer"
    # 任务#27 文本轨残留退役：文本块动作解析通道防复活（动作通道唯一 = FC，
    # ADR-0001；action_parser 用导入路径形式扫描，不命中退役留痕注释）；
    # StudioActionExecutor 旧名防复活（已更名 StateOperationExecutor）；
    # pipeline_orchestrator 拓扑就绪集调度函数防复活（存活消费语义已迁
    # _spec_stage_pending 探针，ADR-0004 后 runtime 永不执行阶段）
    r"|StudioActionExecutor|def parse_actions_from_reply|parse_actions_from_reply\("
    r"|web\.action_parser|import action_parser"
    r"|\bnext_batch\b"
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
