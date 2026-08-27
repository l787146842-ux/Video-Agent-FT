# ADR-0006：阻塞化暂停——问即停 / 三态消费 / 事务性写入

- 状态：已接受（2026-08-27，交互确认彻底改革批 A）
- 取代注记：部分取代 ADR-0004 条款 4（单一活跃暂停槽位的「互斥拒收并结构化
  回喂」语义退役，降级为防御断言）；「暂停卡唯一发行主体 = 模型
  workflow_pause」与槽位唯一性保留不变。
- 触发：暂停语义三重病灶——①暂停发行后循环仍可能继续烧 token（问而不停）；
  ②`workflow_pause` 工具体先写状态、卡片后组装，存在「状态已写但卡片未达
  用户」的半提交态；③用户对暂停卡的回应只有「自由打字即确认」单态，点选/
  拒绝/改主意三种真实意图被压平成同一语义。

## 业界对标（交互确认即阻塞点）

| 基准 | 事实 |
|---|---|
| Claude Code `canUseTool` | 权限确认是同步阻塞点：工具执行悬挂，等用户裁决后以结构化结果（允许/拒绝+理由）回注 |
| OpenAI Agents SDK `interrupt` | 中断即抛 `interrupt` 冻结运行；`resume` 以结构化值恢复，悬挂状态显式持久化 |
| LangGraph `interrupt/resume` | 人在环 = 图在 `interrupt()` 处暂停并落检查点，`Command(resume=...)` 携带用户值恢复 |
| MCP elicitation | 服务端向客户端发起结构化追问，请求阻塞等待用户回答（接受/拒绝/取消三态） |
| AutoGen UserProxyAgent | 人类输入是循环内阻塞调用；回复原样作为消息回注对话 |
| Codex CLI | 审批档位决定逐条确认；确认点即循环边界，通过后从悬挂点继续 |
| 共识 | **询问 = 阻塞点：发行确认请求即结束当前执行片；用户回应是结构化三态值（接受/拒绝/取代），不是纯文本猜测；状态只在确认送达后原子落盘** |

旧形态（非阻塞 + 单态 + 工具体内写状态）与上述共识全部相悖。

## 决策

1. **问即停**：`workflow_pause` 发行成功 = 立即结束本轮、控制流冻结。
   执行段（core/fc_tool_runner.py）在暂停成功后终止本批循环——同批后续
   工具调用不执行、不产生拒因回喂，悬挂调用留在 history 末尾；循环骨架
   （core/agent_loop.py）复用协作式停止通道标记收尾（`stopped=True`、
   `stop_phase="pause"`），web 层对 `pause` 相位豁免，照常走成功路径发
   done（暂停卡随 done payload 下发）。
2. **三态消费**（web/chat_consume.py）：
   - `accept`：点选暂停卡选项，tool result 携带
     `{pause_id, value, label, decision:"accept"}`；
   - `decline`：卡片拒绝/取消选项，`decision:"decline"`，提示模型原方案作废；
   - `cancel-supersede`：自由打字/新指令且存在悬挂暂停，用户消息文本即回应，
     新指令优先，同步清除 `active_pause`。
   三种回应全部经 `reduce_interaction` 落盘 `last_pause_decision` 并进
   控制流 trace。
3. **事务性写入**：`awaiting_confirmation` / `confirmation_message` /
   `active_pause` 仅在发行确认后，由发行点经 `reduce_interaction`
   （flush=True）一次原子写入；`workflow_pause` 工具本体不写状态。文案以
   批末对账后的最终口径为准。
4. **槽位互斥降级为防御断言**：已有未消费暂停时重复发行 `workflow_pause`，
   只告警 + 控制流 trace 留痕，照常发行（新卡覆盖旧卡解除死锁），不再作为
   正常拒因回喂模型（旧「执行后拒收」形态退役，其回喂路径同步删除）。

## 后果与验收

- 测试按新语义重写：`test_pause_structure::TestPauseSlotMutex`（防御断言 +
  事务写入断言）、`test_deterministic_triage` 轮内暂停纪律（同批续执行由
  拒收改为不执行）、`test_pause_structure::TestConsumePauseResponse`
  （标记携带 decision）。
- 代价（用户已知悉并接受）：暂停点后的同批悬挂调用作废重发（问即停换语义
  正确性）；自由打字一律按「取代暂停」消费，不再有「打字也算确认又保留
  暂停」的模糊中间态；前端需按 `pause_response` 结构化回携（批 C 完成前，
  点选经由既有回携通道兼容）。
- 批 B 接口提示：闸兜底卡（汇流点二）与轮末策略卡仍经 `_issue_pause` 签发
  （无预置 pause_id 路径保留）；提醒出槽与策略前置改造基于本批的
  `pause_id` 幂等契约与 `stop_phase="pause"` 豁免。
