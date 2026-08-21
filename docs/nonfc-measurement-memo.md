# 非 FC 通道占比度量 memo（0B 只读版）

> **【档案化 · 2026-08-21 审核整改批0】** 本 memo 为双轨退役前（ADR-0001 前）的一次性只读度量；
> 4-4 双轨已退役、动作通道唯一 = FC，度量对象不复存在，本文档仅供历史追溯。

> 对应《正向设计修复改进计划书》阶段 0B / 4-1。只读统计，未改动任何运行时。

## 口径

- **非 FC 通道** = provider protocol ∈ `{jimeng, codex, gemini-cli}`（走 `AgyCliChatAdapter`，
  无 function calling；见 `web/chat_opening.py::_channel_supports_fc` 与
  `web/provider_config.py::CLI_PROTOCOLS`）。
- **FC 通道** = 其余协议（openai/apimart 等，`OpenAICompatChatAdapter.supports_function_calling=True`）。
- **数据源**：`workspace/projects/*/state.json` 持久化聊天消息的 `modelName` → 反查
  `data/api_providers.json` 的 provider → protocol。
- mock 消息（`mock-chat`）不经过 LLM 通道，不计入分母。

## 结果（2026-08-19 快照）

| 项 | 值 |
|---|---|
| 带 modelName 的 agent 消息总数 | 11 |
| FC（openai 协议） | 7 |
| 非 FC（CLI 三协议） | **0** |
| mock（不计入） | 4 |
| **非 FC 占比** | **0.0%** |
| 未映射模型 | `mock-chat`×4（已归入 mock） |

## 局限性（必须声明）

1. **样本极小**：仅 2 个项目、11 条消息，不足以单独支撑 4-4 硬删判据。
2. `data/agent_traces.jsonl`（1810 条）**无通道/provider 字段**（仅有
   trace_id/timestamp/steps/llm_calls 等），无法从 trace 侧交叉验证。
3. 历史持久化只覆盖当前 workspace；更早的使用痕迹不可考。

## 结论与建议

- **方向性结论**：现存真实历史中非 FC 通道零调用，文本轨**当前不承重**。
- **决策建议**（按计划书风险条款，4-4 删除前必须满足数字判据，禁止拍板）：
  1. 请用户确认日常是否使用 gemini-cli/jimeng/codex 通道（记忆外验证）；
  2. 若需精确数字，批准备选方案：`tracer.py` 增加 `channel` 记录字段（约 1 行），
     跑 1 周真实流量后复测；
  3. 无论 1/2 结果如何，**阶段 4-2（结构化输出替换）与 4-3（冻结）可先行**，
     4-4（删除）排队等数字判据。

## 销账（2026-08-19）

- 用户书面确认不使用非 FC 通道（「不能 FC 就删掉」）→ 满足退役判据 b；
- 4-4 已执行：非 FC 聊天通道与文本轨解析链整体删除，见 `docs/adr/0001-dual-track.md`
  执行记录。本 memo 使命终结，留档作判据链证据。
- 注：口径中引用的 `_channel_supports_fc` 已随 4-4 删除；CLI 三协议保留生图职能。
