# -*- coding: utf-8 -*-
"""防复活门禁（0818 架构板正批 B5）：已退役编排机制符号零残留。

状态驱动编排重构（B0-B4）机械退役了老机制；无门禁则复活可能回潮——
本脚本扫描退役符号：主清单扫 src/tests/scripts；任务#12 批次B 注入面
清单只扫 src/scripts/prompts（不扫 tests：防回归测试的 not hasattr 断言
合法含这些字面量），命中任一即非零退出。
退役清单（符号非概念，同名复用即视为复活）：
- FlowGateSet 闸机链 / skill_pipeline_plan 调度工具 / auto_retry 盲重试
- prepend_script_summary/maybe_prepend 总结注入链 / skill_declares_summary
- dag.py 正则通道（parse_steps 等）/ parse_skill_manifest 文档通道
- 五轮 S4 兼容壳：planner 委托方法组 / _split_actions、save_state 别名（P2d 结构性测试减负承接）
- 已迁 prose 防复述：暂停邀请确认（暂停纪律单家）/ 同批发出（暂停时机建议归 Skill）
- 文本协议残留：planner/system.md 字面量（P2e 单轨收敛，协议唯一 = system_fc.md，ADR-0001）
- 主体回归（ADR-0004）：runtime 机械直跑/审批直跑驱动符号（模型永远唯一行动主体）
- 任务#36 B5 执行器一步退役：executors/exec_* 执行器族模块导入
- 任务#27 文本轨残留退役：web.action_parser 文本块解析通道 /
  parse_actions_from_reply / StudioActionExecutor 旧名（已按实际职责更名
  StateOperationExecutor）/ stage_probes（旧名编排器模块）拓扑就绪集调度函数
- 任务#9 熊布画布通道退役（infinite-canvas 单后端）：XiongBu 后端类族 /
  fetch_canvas_providers_sync 画布 provider 拉取 / 旧映射表名 / 旧直连端点
  - 任务#14 编排器正名：旧模块名 pipeline_orchestrator 防复活（已更名
    stage_probes 纯数据层，同名复用即视为复活）
- 任务#12 批次B L2 注入路径拆除（渐进式披露，用户书面裁决：闸机变更已批准）：
  skill_full_text_injected / build_style_combo / build_generic_skill_block /
  _build_tiered_skill_block / GENERIC_FULL_INJECT_LIMIT / STYLE_COMBO_SOFT_LIMIT /
  skill_style_combo.md —— 全文直注/分级注入/组合注入全部废止，正文一律经
  read_skill 按需读取；退役条件：渐进式披露被用户裁决废止时方可复活。
spec_pause_card/spec_collect_card（规格向导，不变基线）不在清单内。
输出纯 ASCII（验收乱码误读教训）。用法：python scripts/check_legacy_orchestration.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ["src/video_agent", "tests", "scripts"]
# 任务#12 批次B 注入面退役符号：只扫 src/scripts 的 *.py 与 prompts 的 *.md
# （不扫 tests：防回归测试的 not hasattr 断言合法含这些字面量，
# 调整扫描范围而非削弱断言）
SCAN_DIRS_L2 = ["src/video_agent", "scripts"]
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
    # stage_probes（任务#14 正名前旧名编排器模块）拓扑就绪集调度函数防复活
    # （存活消费语义已迁 _spec_stage_pending 探针，ADR-0004 后 runtime 永不执行
    # 阶段）；旧模块名字面量同批入清单（\b 不命中配置字段
    # pipeline_orchestrator_enabled，该字段为环境变量契约不改名）
    r"|StudioActionExecutor|def parse_actions_from_reply|parse_actions_from_reply\("
    r"|web\.action_parser|import action_parser"
    r"|\bnext_batch\b"
    # 任务#14 编排器正名：旧模块名防复活（纯数据层已更名 stage_probes）
    r"|\bpipeline_orchestrator\b"
    # 任务#9 熊布画布通道退役（阶段 7 彻底清理，回退能力消失）：旧后端类族/
    # provider 拉取合并/旧映射表名/旧直连端点防复活（映射表已更名
    # CANVAS_TOOL_*，infinite-canvas 单后端，经 canvas-agent 协议）
    r"|XiongBu|XIONG_BU|xiong-bu|fetch_canvas_providers_sync"
    r"|XIONG_BU_TO_INFINITE_CANVAS_NODE_TYPE|XIONG_BU_NODE_TYPE_TO_CANONICAL"
    r"|CANONICAL_TO_XIONG_BU_NODE_TYPE"
    r"|/api/online-image\b"
)

# 任务#12 批次B：L2 注入路径拆除（渐进式披露）——全文直注/分级注入/组合注入
# 全部废止，系统只注入 L1 目录与轻量状态提示，正文经 read_skill 按需读取；
# 退役条件：渐进式披露被用户裁决废止时方可复活（闸机变更用户书面裁决已取得）。
FORBIDDEN_L2_INJECTION = re.compile(
    r"skill_full_text_injected|build_style_combo|build_generic_skill_block"
    r"|_build_tiered_skill_block|GENERIC_FULL_INJECT_LIMIT|STYLE_COMBO_SOFT_LIMIT"
    r"|skill_style_combo\.md"
)


def _scan(pattern: re.Pattern, dirs, globs):
    for d in dirs:
        for g in globs:
            for p in (ROOT / d).rglob(g):
                if p.resolve() == SELF:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        yield p.relative_to(ROOT).as_posix(), i, line.strip()[:70]


def main() -> int:
    hits = list(_scan(FORBIDDEN, SCAN_DIRS, ["*.py"]))
    hits += list(_scan(FORBIDDEN_L2_INJECTION, SCAN_DIRS_L2, ["*.py"]))
    hits += list(_scan(FORBIDDEN_L2_INJECTION, ["prompts"], ["*.md"]))
    if hits:
        for rel, n, line in hits[:20]:
            print(f"[check_legacy_orchestration]   {rel}:{n}: {line}")
        print(
            f"[check_legacy_orchestration] FAIL: {len(hits)} legacy-orchestration reference(s). "
            "Retired by 0818 state-driven orchestration batch; extend "
            "stage_probes/frontmatter instead of reviving old mechanisms."
        )
        return 1
    print("[check_legacy_orchestration] PASS: no legacy orchestration symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
