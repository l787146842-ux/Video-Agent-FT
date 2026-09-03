# 上下文降级说明（状态压缩/降级引导语的单一事实源）
# 注入条件：状态 JSON 的 degraded=true 或 compacted=true 时由 prompt_builder 独立成段注入

> `## KEY` 分节由 `load_prompt_section` 读取。这些文案向模型陈述上下文
> 治理动作的客观事实（P3 状态即数据：状态 JSON 只留 degraded/compacted
> 布尔标志位，引导语不嵌数据体，由消费点独立成段注入）。
> 语气判据：陈述客观事实 + 至多一句可执行引导，不用祈使句，单条 ≤3 句。

## STATE_COMPACTED
（系统）工作台状态正文已截断（超注入预算，状态 JSON 的 compacted 标志为 true）：分组正文与草稿提示词全文未注入，对应全文分别经 read_state_group、read_draft 按需读回。

## STATE_DEGRADED
（系统）工作台状态已降级（预算保险丝，状态 JSON 的 degraded 标志为 true）：草稿细节未注入，仅保留组标题/编号/草稿计数，细节经 read_draft/read_project_doc 按需读取。

## ROUND_SUMMARY_PREFIX
（系统）早期轮次已压缩为摘要（原文不再占用上下文；关键句柄保留，如需全文调对应 read_* 工具读回）：
