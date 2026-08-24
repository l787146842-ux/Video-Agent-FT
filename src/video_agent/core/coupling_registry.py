"""耦合注册表（全量清偿：宪法 13.7 耦合表机器可读化）。

13.7「改 A 必须同步检查 B」原为宪法内散文表，靠 AI 读到并记住——记性不可靠。
本注册表把全部耦合行转为数据（policy-as-data 同源），每行声明强制方式：

- file   ：关键文件必须存在（路径相对仓库根）
- symbol ：模块属性必须可导入（module:attr，改名/删除即红）
- testfile：钉死回归测试文件必须存在（tests/ 下相对路径）
- vtest  ：前端钉死测试文件必须存在（仓库根相对路径）
- gate   ：门禁脚本必须存在且已注册进 scripts/acceptance.py
- prose  ：确不可机械化，必须给理由（降级声明，非遗漏）

遍历测试：tests/unit/test_coupling_registry.py（注册表每行强制项真实存在；
prose 行必须有理由）。宪法 13.7 正文由该注册表 + 遍历测试承接（落指针）。
行编号 - 与宪法 13.7 原表行序对应，便于销账对照。
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
        "R_workflow_runtime_subject_return",
        "Workflow Runtime 控制流范式变更（宪法 Rule2 主体回归 / ADR-0004）",
        "账本+裁判数据层 sync_run/compile_definition + 选项面归一 + reducer 单一写入 + 1111 黄金轮次契约",
        _sym(
            "src.video_agent.core.workflow_runtime:sync_run",
            "src.video_agent.core.workflow_runtime:reduce_interaction",
            "src.video_agent.core.pause_composer:normalize_option_surface",
        ) + (("testfile", "tests/unit/test_workflow_runtime_1111.py"),),
    ),
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
        (("testfile", "tests/unit/test_action_executor_fallback.py"),)
        + (("prose", "兜底链行为由回归测试钉死，格式锚点属内容审查"),),
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
        + _sym("src.video_agent.web.chat_cards:_stamp_doc_written"),
    ),
    CouplingRow(
        "R08_model_policy_roles",
        "模型策略表角色变更",
        "core/model_policy 定义源 + 四个消费点 + runtime_settings 写入点",
        _sym(
            "src.video_agent.core.model_policy:resolve_role",
            "src.video_agent.core.model_policy:thinking_for",
            "src.video_agent.web.chat_opening:_resolve_summary_adapter",
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
        (("testfile", "tests/unit/test_transport_wiring_four.py"),)
        + (("prose", "FC 暂停语义合成 studio-actions 单路径消费，双轨同测由该行测试覆盖"),),
    ),
    CouplingRow(
        "R13_split_module_shells",
        "拆分模块新增顶层符号",
        "re-export 壳清单 + 测试 patch 目标改为调用方命名空间",
        _sym(
            # prompt_gates 尾部承重壳（gates_spec + gates_script）
            "src.video_agent.core.prompt_gates:spec_pause_card",
            "src.video_agent.core.prompt_gates:script_present",
            # chat_service 尾部承重壳
            "src.video_agent.web.chat_service:_acquire_request_slot",
            # 新壳
            "src.video_agent.core.fc_tool_runner:format_tool_results",
            # 任务#23 三段拆分承重壳：闸机方法壳（实现体 fc_gates）
            "src.video_agent.core.fc_tool_runner:FCToolRunner._prompt_gate",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_generate_image",
            "src.video_agent.core.prompt_gates:SPEC_GATE_ERROR",
            "src.video_agent.core.prompt_gates:parse_hard_selections",
            # P3 反向依赖下沉（任务 10）：web/provider_config.py 薄壳
            # （实现体 core/provider_config.py；provider_models 随迁无壳）
            "src.video_agent.web.provider_config:get_provider_config",
            "src.video_agent.web.provider_config:load_merged_providers",
            # 任务 22 P7-1 state/manager.py 拆分承重壳：对话域（实现体
            # conversation_ops）/落盘闸（实现体 save_ops）/快照组装（实现体
            # context_builder）；StateManager 公开 API 门面长期承重
            "src.video_agent.state.manager:StateManager.add_chat_message",
            "src.video_agent.state.manager:StateManager.create_conversation",
            "src.video_agent.state.manager:StateManager.save",
            "src.video_agent.state.manager:StateManager.board_version",
            "src.video_agent.state.manager:StateManager.get_full_snapshot",
            # 任务 23 P7-2 gate_registry 切出承重壳：注册表数据 + 别名表 +
            # 归一函数（实现体 core/gate_registry.py，纯数据无判定）；
            # guard_pipeline/planner_gate_session/routes/agent/scripts 经
            # prompt_gates.* 引用，迁移需全量改引用
            "src.video_agent.core.prompt_gates:GATE_RULES",
            "src.video_agent.core.prompt_gates:GateRuleMeta",
            "src.video_agent.core.prompt_gates:normalize_rule_id",
            # 任务 24 P7-3 action_executor.py 动作域拆分承重壳：草稿/分组域
            # （实现体 action_drafts）/文档媒体域（实现体 action_media）；
            # 生成域实现体先例已切 action_gen；执行器门面（分派+闸机判定）
            # 长期承重，实例方法壳保 patch 目标不变
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_draft_patch",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_add_draft",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_add_group",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_write_document",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_clear_media",
            "src.video_agent.core.action_executor:StateOperationExecutor._apply_insert_chat_media",
            # 任务 25 P7-4 chat_service.py 错误翻译域拆分承重壳：流式错误
            # 出口 + 人话翻译（实现体 web/chat_errors.py）；tests 经
            # chat_service.* 导入钉死，迁移需全量改引用
            "src.video_agent.web.chat_service:_emit_stream_error",
            "src.video_agent.web.chat_service:_friendly_stream_error",
            # skill_runtime/executors 与 exec_tools 承重壳已随任务#36 B5
            # 执行器一步退役删除（物理删除，不设观察期）
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
        "拆分模块变更（gates_script/gates_cards）",
        "prompt_gates 尾部 re-export；消费方旧命名空间不变"
        "（exec_split/exec_media_writer/exec_media_gen 已随任务#36 B5 退役删除）",
        (("file", "src/video_agent/core/gates_script.py"),)
        + (("file", "src/video_agent/core/gates_cards.py"),),
    ),
    CouplingRow(
        "R16_manifest_whitelist_keys",
        "frontmatter 声明键（gates/flow/pause）变更",
        "任务#5：声明唯一源 = Skill 文档头部 YAML frontmatter（外置 JSON sidecar 退役）；消费点：parse_gate_rules/agent_loop/fc_gates/planner 裁剪/"
        "prompt_builder/registry pause 节",
        _sym(
            "src.video_agent.core.prompt_gates:parse_gate_rules",
            "src.video_agent.core.fc_gates:prompt_gate",
            "src.video_agent.core.planner:Planner._compute_excluded_tools",
            "src.video_agent.core.prompt_builder:PromptBuilder.build_system_prompt",
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
        + (("testfile", "tests/unit/test_gen_confirm_gate.py"),),
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
        "chat_cards 打戳（chat_service 透传层消费）→ use-sse 携带 → chat.docWritten 落消息",
        _sym("src.video_agent.web.chat_cards:_stamp_doc_written")
        + (("vtest", "src/web/lib/__tests__/turn-groups.test.ts"),)
        + (("testfile", "tests/unit/test_doc_written_turn_stamp.py"),),
    ),
    CouplingRow(
        "R26_frontend_contract",
        "后端路由模型改名/删字段",
        "重生成 api.generated.ts → tsc 编译期报消费点；消费覆盖桥接测试",
        (("gate", "gen_api_types.py"),)
        + (("vtest", "src/web/lib/__tests__/api-contract.test.ts"),),
    ),
    CouplingRow(
        "R27_planner_split_delegation",
        "planner 拆分协作臂变更（豁免消费/闸预检/FC 响应合并；批 12 分诊/收权退场；"
        "D-02 单轮执行/回喂治理/预算装配切出 turn_executor）",
        "实现体迁出后 planner 委托必须保留（既有测试与调用方钉死委托方法）；"
        "turn_executor 经实例引用回调 _handle_fc_response，委托改名即断线",
        _sym(
            "src.video_agent.core.planner_gate_session:consume_gate_overrides",
            "src.video_agent.core.planner_triage:run_gate_precheck",
            "src.video_agent.core.pipeline_orchestrator:gate_precheck",
            "src.video_agent.core.fc_response:merge_fc_response",
            "src.video_agent.core.planner:Planner._run_gate_precheck",
            "src.video_agent.core.turn_executor:TurnExecutor.llm_call",
            "src.video_agent.core.planner:Planner._handle_fc_response",
        ) + (("testfile", "tests/unit/test_deterministic_triage.py"),),
    ),
    CouplingRow(
        "R28_layer_import_direction",
        "批 3.3：core/tools 需要消费 web 层能力（媒体注入解析/降级链/文档与"
        "生成任务面）时新增 tools→web 或 core→web import",
        "一律改走 core/ports 端口（D-01）或 storage/core 公开 API（下沉先例："
        "storage.media_urls / core.generation_fallback）；新门禁零豁免，"
        "违规即 FAIL；壳模块 re-export 名单变更须同步本行 symbol",
        _sym(
            "src.video_agent.storage.media_urls:resolve_injectable_url",
            "src.video_agent.core.generation_fallback:gen_fallback_candidates",
            "src.video_agent.core.generation_fallback:is_retryable_gen_error",
        ) + (
            ("gate", "check_layer_imports.py"),
            ("file", "src/video_agent/web/multimodal_builder.py"),
            ("file", "src/video_agent/web/generation_dispatch.py"),
        ),
    ),
]


ROW_INDEX = {r.row_id: r for r in COUPLING_ROWS}
