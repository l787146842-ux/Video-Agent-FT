# ADR-0001：双轨制冻结与退役路线图

- 状态：**已执行完毕**（2026-08-19，audit-0819；冻结 4-3 → 删除 4-4 同日完成）
- 触发判据：用户书面确认不使用非 FC 通道（「不能 FC 就删掉」）+ 0B 度量非 FC 占比 0%
- 关联：宪法 Rule 2、`docs/nonfc-measurement-memo.md`、`core/scaffold_registry.py` S01

## 背景

双轨制（FC 轨 + 自由文本 studio-actions 解析轨）是本项目最大的结构性复杂度源：
双轨一致条款、流式抑制器、退化变体检测、解析自愈全部为它付费。
业界（Codex/Claude Code/AutoBe）均为单轨 tool call / 结构化输出，
自由文本围栏解析无业界背书。

0B 度量（2026-08-19）：现存持久化历史中非 FC 通道占比 0%
（样本 11 条，偏小；trace 无通道字段，交叉验证缺失）。

## 决策

1. **冻结**：`prompts/planner/text_actions.md` 停止新增动作；新动作仅进 FC 轨。
2. **升级**：文本轨解析失败由「立即丢弃」升级为「校验 + 结构化拒因重试」
   （4-2，AutoBe/C2 自愈环），作为退役前的质量兜底。
3. **退役判据**：满足任一即启动 4-4 删除——
   a. tracer 通道字段（备选方案，需单独批准）跑满 1 周且非 FC 占比 ≈ 0；
   b. 或用户书面确认日常不使用 gemini-cli/codex/jimeng 三协议。
4. **删除范围（4-4）**：action_parser 退化检测、stream_suppressor 文本轨分支、
   text_actions.md 注入；宪法 Rule 2 双轨表述简化为「循环唯一实现」。
   对应 scaffold_registry S01/S02/S14 同批下账、基线随降。

## 执行记录（4-4，2026-08-19）

已删除：
- `AgyCliChatAdapter` 及全部聊天接线（chat_opening/_channel_supports_fc/
  chat_service text_protocol/附件 full_text 降级）；CLI 三协议仅保留生图职能，
  选中 CLI 供应商聊天报人话错误；fetch-models/test-connection 对 CLI 恒返回
  chat_models=[]。
- `prompts/planner/text_actions.md` 文件与注入；PlannerContext.text_protocol 字段。
- action_parser 退化信号探测（extract_degraded_signal_blocks，S02 下账）与
  StreamingActionExtractor 流式增量提取；planner 流式「边写边填」预执行与
  _STREAM_GATE_DEFER_ACTIONS；executor 累加批次（accumulate）与流式计数器。
- agent_loop 的 4-2 拒因重试自愈环（随文本轨退役失去对象）。
- stream_suppressor 的 ```json 确认信号围栏分支与 suppressed 捕获（S01 保留
  围栏抑制本体：audit-0819 取证 FC 模型仍会写围栏，复测口径改为
  「连续 2 个模型周期零违规才可删」，为与计划书范围的诚实偏差）。

保留（文本块解析的合法消费方，写入宪法 Rule 2）：
- FC 轨内部合成确认块（planner._handle_fc_response → agent_loop 解析）；
- mock 演示通道输出；strip_action_blocks 防泄漏（双路径共用）。

## 执行记录二（audit-0819b 单轨化，2026-08-19，用户批准）

对齐业界最高标准（Claude Code AskUserQuestion / codex-cli AskUserTool /
DeepSeek Harness waterfall 审批：暂停确认一律是工具/结构化事件，从不走
正文暗号），上述「保留项」同批清零：
- 暂停确认唯一经 workflow_pause / request_confirmation FC 工具产生
  （后者新增为正式工具别名，同 schema 同行为），经 llm_call 第 5 元组
  extra={confirmation, confirmation_options} 结构化上抛 agent_loop；
  planner 不再合成 studio-actions 块（防泄漏根治：通道消失则无可泄漏）。
- stream_suppressor.py 整文件删除（S01 下账，基线 12→11）；action_parser
  删除 strip_action_blocks / has_action_block；executor 同步删委托；
  agent_loop 删除文本块解析路径，纯文本轮仅收尾（轮末策略表照常承重，
  虚报审计在 FC 确认轮同批补回，单轨化不豁免审计）。
- mock 演示通道动作改为结构化 dict 直达执行器（不经文本）；
  executing_actions SSE 事件同批退役（登记/常量/前端 i18n 同步清理）。
- 钉死：test_planner_does_not_synthesize_action_blocks（content 含
  studio-actions 即红）；结构化确认暂停/选项透传回归（audit-0819b）。

## 执行记录三（audit-0819d 四维对齐收尾，2026-08-19，用户裁决三补丁全删）

对齐业界核实（OpenAI Structured Outputs strict / Codex apply_patch 严格解析 /
AutoBe 编译器校验：坏输出=证据确凿的失败，硬校验+拒因重试，绝无宽容解析），
最后一条文本解析管道与两处别名补丁同批清偿：
- **执行器结构化输出（改造 1，S17 删）**：OpenAI 兼容适配器新增
  response_format 参数 + 400 兼容探针（剥离重试+实例记忆+遥测
  adapter.response_format_unsupported）；执行器全部 JSON 产出点下发
  json_object；`_parse_actions_from_text` 改严格 json.loads（围栏/裸数组宽容
  正则删除，失败记 executor.json_strict_parse_failed 遥测），`_llm_json_call`
  正则抠取删除，畸形产出走既有 C2 拒因纠正重试；流式逐条落盘 UX 无损。
- **暂停单一正名（改造 2）**：RequestConfirmationTool 别名工具删除，
  workflow_pause 为唯一暂停入口（对齐「只有一个 AskUserQuestion」）；
  全库双名表述（代码/提示词/测试断言）同批收敛。
- **S15 工具名翻译层删**：FOREIGN_TOOL_MAP + build_foreign_tool_note 及
  三处注入（prompt_builder ×2、read_skill）删除；运行时不再做工具名翻译，
  导入期转换归将来专用 Skill 系统；存量 Skill 文档最后一处老名字已迁。
- **S16 别名归一删**：agent_loop split_actions / _extract_confirmation 删除
  （结构化上抛后无文本别名可归一）。
- **棘轮门禁新增（改造 4）**：check_executor_skill_drift.py 升级为
  「约束主体词×数字」漂移对检测，基线实测=0（只降不升），注册进
  acceptance 第 13 门禁。
- 钉死：test_audit0819d_structured_executors（探针/严格解析/三符号防复活）；
  退役：test_foreign_tool_mapping、test_confirm_options 及 6666/7777 别名用例。
- 脚手架基线维持 11 不上调（三补丁属存量清偿，直接删除而非登记）。

## 后果

- 双轨一致条款已随单轨化废除（宪法 Rule 2 改写）；
- CLI 三协议继续提供生图能力（AgyCliImageAdapter 等），聊天职能整体移除；
- 若未来出现必须支持的非 FC 通道，按 AutoBe 模式走
  「schema 约束生成 + 校验 + 拒因反馈」，不恢复自由文本解析演进。
