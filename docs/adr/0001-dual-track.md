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

## 后果

- 双轨一致条款已随单轨化废除（宪法 Rule 2 改写）；
- CLI 三协议继续提供生图能力（AgyCliImageAdapter 等），聊天职能整体移除；
- 若未来出现必须支持的非 FC 通道，按 AutoBe 模式走
  「schema 约束生成 + 校验 + 拒因反馈」，不恢复自由文本解析演进。
