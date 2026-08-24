# ADR-0003：Workflow Runtime 单一控制实体（宪法 v6 Rule2）

- 状态：已接受（2026-08-20，用户审定计划「Workflow Runtime 正态整改」）
- 被取代注记（2026-08-21，已被 ADR-0004/宪法 v7 取代；本 ADR 取代 ADR-0002 决策 2/3）：
  「runtime 机械直跑 / 审批直跑」决策退役，模型永远唯一行动主体；
  阶段表/依赖图/客观探针/闸内嵌执行路径/原子轮提交/四投影同源保留为账本与裁判数据层职能。
- 触发事故：1111 项目 v2——批 12 范式（模型主动权 + 平台否决权）现场五现象：
  1. 前两轮回合作被伪装成 Agent 回合（机械卡 0.7s，无状态转换语义）；
  2. 确定性管线付 agent 延迟税：3 个规划轮 ≈40s（阶段切换靠模型 ReAct 猜测），
     script_analyze 103.3s 内藏两次串行内层 LLM（分析 + 候选出题）；
  3. 顺序漂移：模型自造「继续拆分关键元素」跳过 spec 阶段，平台仅能在下一轮
     预检迟到纠偏（选项不是工具调用，否决闸查不到）；
  4. 三通道违约：机械卡 `text=""` + 引导词塞 confirm → 正文「(空回复)」；模型裸值
     选项击穿「维度：值」机械消费契约，用户选择被静默丢弃一整轮；
  5. 可见性分裂：read_skill 无 canonical 身份（名字写错即报错、注入后仍反复读）；
     文档卡 SSE 早于订阅丢失；tracer 轮前记录被 start_trace 清空；前端 trace 遮罩合成日志。

## 业界依据

| 原则 | 依据 |
|---|---|
| 定义良好的管线用 workflow（代码持有控制流），agent loop 只留开放任务 | Anthropic《Building Effective Agents》 |
| Hooks guarantee behavior; prompts suggest——确定性强制内嵌执行路径 | Claude Code hooks |
| 一致性流程用编排器驱动模型-工具循环，循环只负责单元内开放决策 | OpenAI Codex / Agents SDK cookbook |
| 模型做语义内容，运行时做确定性顺序/持久状态/审批恢复/产物账本 | Temporal Durable Execution / LangGraph persistence（checkpoint + human-in-the-loop interrupt） |

## 独立诊断收敛

Qoder 与 Codex 两份只读审计独立收敛同一根因：**控制权分裂**——Skill、模型 FC
循环、预检编排器、规格直写链、前端投影各持一部分流程控制权，没有唯一
Workflow Runtime。本 ADR 为其根治裁决。

## 决策

1. **宪法 v6 Rule2**：`core/workflow_runtime.py` 为控制流唯一驱动器。Skill 激活
   编译 `WorkflowDefinition`（canonical slug + revision + content hash，源 = sidecar
   声明，`validate_sidecar` 注册期门禁）；持久化 `WorkflowRun`
   （current_node/completed_nodes/pending_gate/artifacts），**仅 runtime reducer
   可改**（StateManager 仍唯一写入点，Rule3）。
2. **确定性阶段直跑**（阶段表声明 executors，零模型规划轮）；**创作型阶段**
   （deterministic=False）交接有界模型循环（`agent_loop` 节点内唯一实现）。
   模型不决定阶段顺序、不撰写暂停卡选项面。
3. **平台否决权保留**：stage_precondition/暂停纪律闸/原料闸/规格闸内嵌执行路径
   首位（hooks guarantee behavior），不依赖模型自觉。
4. **原子轮提交**：一轮只提交一个 `TurnResult`（body+artifacts+timeline_events+
   decision_request+next_transition，turn_id 归组）；正文只承载成果；暂停卡只承载
   一句问句 + 系统派生选项（`core/pause_composer.py` 唯一发行点）；文档卡源自同轮
   artifact；正常完成禁空正文；`ArtifactCommitted` 先于 `StageSucceeded`；
   SSE/历史/时间线/卡片四投影同源派生；瞬态通道不得作为唯一可见性。
5. **批 12 范式退役**：GOVERNANCE §13.13 同批改指针；本 ADR 取代 ADR-0002
   决策 2/3。

## 与 ADR-0002 的关系

- 决策 1（阶段前置闸）保留，并入 runtime 否决层；
- 决策 2/3（确定性分诊 advance 接管 / between_steps 回收）被 runtime 驱动器取代；
  分诊的兜底卡装配职能保留为 runtime 的 gate_precheck 节点，不再是独立控制流入口；
- 决策 4（可观测性）保留并强化（一切机械动作进转录一等条目）。

## 后果

- 验收锚点：`tests/fixtures/workflow_1111_baseline.json`（修复前基线）+
  `tests/test_workflow_runtime_1111.py`（修复后黄金轮次契约）；
- 确定性阶段零规划轮；暂停卡选项面全系统派生；发卡前校验（无迟到纠偏）；
- `check_legacy_orchestration` 同批登记新退役符号防复活；
- 治理：控制流范式表述唯一归宪法 Rule2（P1），ADR/GOVERNANCE 仅指针。
