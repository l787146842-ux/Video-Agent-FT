"""耦合注册表（八轮 B5，T20 全量清偿：宪法 13.7 耦合表机器可读化）。

13.7「改 A 必须同步检查 B」原为宪法内散文表，靠 AI 读到并记住——记性不可靠。
本注册表把全部耦合行转为数据（policy-as-data 同源），每行声明强制方式：

- file   ：关键文件必须存在（路径相对仓库根）
- symbol ：模块属性必须可导入（module:attr，改名/删除即红）
- testfile：钉死回归测试文件必须存在（tests/ 下相对路径）
- vtest  ：前端钉死测试文件必须存在（仓库根相对路径）
- gate   ：门禁脚本必须存在且已注册进 scripts/acceptance.py
- prose  ：确不可机械化，必须给理由（降级声明，非遗漏）

遍历测试：tests/unit/test_coupling_registry.py（注册表每行强制项真实存在；
prose 行必须有理由）。宪法 13.7 正文由该注册表 + 遍历测试承接（八轮 B8 落指针）。
行编号 R01-R26 与宪法 13.7 原表行序对应，便于销账对照。
"""
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(frozen=True)
class CouplingRow:
    row_id: str
    trigger: str          # 什么变更触发本行
    sync_points: str      # 必须同步检查什么（人读摘要）
    enforcement: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)


def _sym(*pairs: str) -> Tuple[Tuple[str, str], ...]:
    return tuple(("symbol", p) for p in pairs)


COUPLING_ROWS: List[CouplingRow] = [
    CouplingRow(
        "R01_skill_section_tag",
        "Skill 章节 tag 改名/拆分执行器",
        "SECTION_TAG_STAGES 映射 + system 动作清单 + 存量 Skill 旧标签",
        _sym(
            "src.video_agent.web.skill_docs:SECTION_TAG_STAGES",
            "src.video_agent.web.skill_docs:split_skill_sections",
        ) + (("prose", "system 动作清单与存量 Skill 旧标签兼容属内容审查，不可机械遍历"),),
    ),
    CouplingRow(
        "R02_iron_rules_template",
        "铁律模板（spec_rules._IRON_RULES_DOC_BODY）变更",
        "只影响新建项目；老项目需手动同步或删文档重建；闸机读取逻辑",
        _sym("src.video_agent.core.spec_rules:_IRON_RULES_DOC_BODY")
        + (("prose", "老项目同步是运维动作，无代码链路可遍历"),),
    ),
    CouplingRow(
        "R03_spec_doc_rename",
        "规格文档改名/字段变更",
        "_SPEC_NAME_HINTS + provider_prefs 解析 + 执行器参数回退链",
        _sym(
            "src.video_agent.core.prompt_gates:_SPEC_NAME_HINTS",
            "src.video_agent.core.prompt_gates:is_spec_doc_name",
            "src.video_agent.core.prompt_gates:has_spec_document",
        ),
    ),
    CouplingRow(
        "R04_executor_output_format",
        "执行器输出格式变更",
        "action_executor 兜底链 + 自检去重键（去重依赖标题有效）",
        (("testfile", "tests/unit/test_2222_round2_fixes.py"),)
        + (("prose", "兜底链行为由事故回归测试钉死，格式锚点属内容审查"),),
    ),
    CouplingRow(
        "R05_new_pause_point",
        "新增暂停点",
        "Skill「何时暂停」+ 层 9 兜底注入（Skill 管引导，兜底管强制）",
        _sym(
            "src.video_agent.skill_runtime.registry:parse_pause_rules",
            "src.video_agent.skill_runtime.guard:skill_requires_stage_pause",
        ) + (("testfile", "tests/unit/test_skill_manifest.py"),),
    ),
    CouplingRow(
        "R06_new_sse_event",
        "新增 SSE 事件",
        "工具层 emit → planner 白名单 → chat_service 透传 → 前端 handler 四段链",
        (("file", "src/video_agent/web/sse_protocol.py"),)
        + _sym("src.video_agent.web.sse_protocol:PASSTHROUGH_EVENT_TYPES")
        + _sym("src.video_agent.core.sse_events:status_event"),
    ),
    CouplingRow(
        "R07_doc_written_chain",
        "doc_written 即显链路变更",
        "发射（按名去重）→ planner 白名单 → chat_service 透传 → 前端双通道去重",
        (("vtest", "src/web/lib/__tests__/turn-groups.test.ts"),)
        + _sym("src.video_agent.web.chat_service:_stamp_doc_written"),
    ),
    CouplingRow(
        "R08_model_policy_roles",
        "模型策略表角色变更",
        "core/model_policy 定义源 + 四个消费点 + runtime_settings 写入点",
        _sym(
            "src.video_agent.core.model_policy:resolve_role",
            "src.video_agent.core.model_policy:thinking_for",
            "src.video_agent.core.planner:Planner._make_summarize_fn",
        ),
    ),
    CouplingRow(
        "R09_snapshots_branch",
        "快照/分支机制变更",
        "routes/snapshots + conversations 创建 + _meta.branched_from + 前端分支按钮",
        (("file", "src/video_agent/web/routes/snapshots.py"),)
        + (("prose", "前端分支按钮属 UI 审查（目测批），无机械链路"),),
    ),
    CouplingRow(
        "R10_context_window_meta",
        "窗口表元数据变更",
        "api_providers.json chat_models_meta.context_window → token_budget → planner 传递",
        _sym(
            "src.video_agent.core.token_budget:context_window_for_model",
            "src.video_agent.web.provider_config:get_provider_config",
        ),
    ),
    CouplingRow(
        "R11_new_fc_tool",
        "新增 FC 工具",
        "tool description（层 10）+ 阶段裁剪集 + 测试",
        _sym("src.video_agent.core.planner:Planner._compute_excluded_tools")
        + (("prose", "description 质量与裁剪集归属属内容审查"),),
    ),
    CouplingRow(
        "R12_fc_confirm_loop",
        "FC 确认回环变更",
        "planner 合成 studio-actions JSON 拼回正文 → agent_loop 单路径消费；双轨同测",
        (("testfile", "tests/unit/test_b0_p0_fixes.py"),)
        + (("prose", "FC 暂停语义合成 studio-actions 单路径消费，双轨同测由该行测试覆盖"),),
    ),
    CouplingRow(
        "R13_split_module_shells",
        "拆分模块新增顶层符号",
        "re-export 壳清单 + 测试 patch 目标改为调用方命名空间",
        _sym(
            # skill_runtime/executors 承重壳（R4a）
            "src.video_agent.skill_runtime.executors:ScriptAnalyzeTool",
            "src.video_agent.skill_runtime.executors:StoryboardShotsTool",
            # prompt_gates 尾部承重壳（gates_spec + gates_script，R4b/S5）
            "src.video_agent.core.prompt_gates:spec_pause_card",
            "src.video_agent.core.prompt_gates:script_present",
            # chat_service 尾部承重壳（R4c）
            "src.video_agent.web.chat_service:_acquire_request_slot",
            # exec_tools 尾部承重壳（exec_split，S5）
            "src.video_agent.skill_runtime.exec_tools:_KE_TASK",
            # 八轮 B1-B3 新壳
            "src.video_agent.core.fc_tool_runner:format_tool_results",
            "src.video_agent.core.planner:_prepend_script_summary",
            "src.video_agent.web.action_executor:StudioActionExecutor._apply_generate_image",
            # 九轮 B3/B3b 新壳（exec_media_writer/exec_media_gen/gates_cards 迁出后 re-export）
            "src.video_agent.skill_runtime.exec_tools:WriteMediaPromptTool",
            "src.video_agent.skill_runtime.exec_tools:AudioGenerateTool",
            "src.video_agent.core.prompt_gates:SPEC_GATE_ERROR",
            "src.video_agent.core.prompt_gates:parse_hard_selections",
        ),
    ),
    CouplingRow(
        "R14_shell_expiry",
        "新增 re-export 壳",
        "注释登记清偿属性（长期承重/预计清偿轮次），逾期立案",
        (("prose", "到期制是审查纪律（登记完备性），不可机械判定语义"),),
    ),
    CouplingRow(
        "R15_s5_split_modules",
        "拆分模块变更（gates_script/exec_split/gates_cards/exec_media_writer/exec_media_gen）",
        "prompt_gates 尾部与 exec_tools 尾部 re-export；消费方旧命名空间不变",
        (("file", "src/video_agent/core/gates_script.py"),)
        + (("file", "src/video_agent/skill_runtime/exec_split.py"),)
        + (("file", "src/video_agent/core/gates_cards.py"),)
        + (("file", "src/video_agent/skill_runtime/exec_media_writer.py"),)
        + (("file", "src/video_agent/skill_runtime/exec_media_gen.py"),),
    ),
    CouplingRow(
        "R16_manifest_whitelist_keys",
        "skill_manifest 白名单键变更",
        "七个消费点：parse_gate_rules/agent_loop/fc_tool_runner/planner 裁剪/"
        "prompt_builder/action_executor/_spec_gate_ok/registry pause 节",
        _sym(
            "src.video_agent.core.prompt_gates:parse_gate_rules",
            "src.video_agent.core.fc_tool_runner:FCToolRunner._prompt_gate",
            "src.video_agent.core.planner:Planner._compute_excluded_tools",
            "src.video_agent.core.prompt_builder:PromptBuilder.build_system_prompt",
            "src.video_agent.web.action_executor:StudioActionExecutor._spec_gate_ok",
            "src.video_agent.skill_runtime.registry:parse_pause_rules",
        ) + (("testfile", "tests/unit/test_skill_manifest.py"),),
    ),
    CouplingRow(
        "R17_channel_rules_source",
        "渠道来源规则共源段变更",
        "prompts/shared/gen_channel_rules.md 唯一表述源 + 双协议 {{include}} + 快照",
        (("file", "prompts/shared/gen_channel_rules.md"),)
        + (("testfile", "tests/unit/test_round3_governance.py"),),
    ),
    CouplingRow(
        "R18_gen_confirm_single",
        "生成确认闸变更",
        "guard_pipeline.evaluate_gen_confirm 唯一判定；双轨只注入参数",
        _sym("src.video_agent.core.guard_pipeline:evaluate_gen_confirm")
        + (("testfile", "tests/unit/test_b4_dual_track_gen_confirm.py"),),
    ),
    CouplingRow(
        "R19_flow_gate_single",
        "流程门禁变更",
        "guard_pipeline.evaluate_flow_gate 唯一判定；两轨只做分类与处置",
        _sym("src.video_agent.core.guard_pipeline:evaluate_flow_gate")
        + (("testfile", "tests/unit/test_r2_dual_track_flow_gate.py"),),
    ),
    CouplingRow(
        "R20_pause_rules_landing",
        "pause_rules 解析变更",
        "registry.parse_pause_rules 定义源；skill_docs 顶层 re-export 保兼容",
        _sym(
            "src.video_agent.skill_runtime.registry:parse_pause_rules",
            "src.video_agent.web.skill_docs:parse_pause_rules",
        ),
    ),
    CouplingRow(
        "R21_button_base_reset",
        "按钮基线变更",
        "tokens.css @layer base 的 button 重置为根因唯一落点",
        (("prose", "视觉基线属 UI 审查（目测批）；CSS 无机械链路"),),
    ),
    CouplingRow(
        "R22_acceptance_components",
        "验收组件改名/新增",
        "scripts/acceptance.py GATES/SUITES/EVAL 表 + CI Job 同构",
        (("gate", "check_governance_refs.py"), ("gate", "check_prompt_budget.py"),
         ("gate", "check_file_lines.py"), ("gate", "check_func_imports.py"),
         ("gate", "gen_api_types.py"), ("gate", "check_category_keys.py")),
    ),
    CouplingRow(
        "R23_governance_refs_gate",
        "治理叙事门禁变更",
        "acceptance GATES 表 + CI Job1 + BUDGET 棘轮（禁止上调）",
        (("gate", "check_governance_refs.py"),),
    ),
    CouplingRow(
        "R24_log_file_switch",
        "LOG_FILE_ENABLED 开关变更",
        "config.settings → app.py sink 装配 + conftest setdefault + acceptance env",
        _sym(
            "src.video_agent.config:settings",
            "src.video_agent.web.app:app",
        ),
    ),
    CouplingRow(
        "R25_doc_turn_stamp",
        "doc_written turn_id 打戳位置变更",
        "chat_service 透传层打戳 → use-sse 携带 → chat.docWritten 落消息",
        _sym("src.video_agent.web.chat_service:_stamp_doc_written")
        + (("vtest", "src/web/lib/__tests__/turn-groups.test.ts"),)
        + (("testfile", "tests/unit/test_s5_doc_written_turn_stamp.py"),),
    ),
    CouplingRow(
        "R26_frontend_contract",
        "后端路由模型改名/删字段",
        "重生成 api.generated.ts → tsc 编译期报消费点；消费覆盖桥接测试",
        (("gate", "gen_api_types.py"),)
        + (("vtest", "src/web/lib/__tests__/api-contract.test.ts"),),
    ),
]


ROW_INDEX = {r.row_id: r for r in COUPLING_ROWS}
