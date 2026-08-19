# 系统回喂模板（工具结果回喂与流程提醒的单一事实源）

> `## KEY` 分节由 `load_prompt_section` 读取。这些文案是「(系统)」角色的
> 运行时消息模板：回喂进 LLM 上下文但不属于 system prompt 协议。

## FEEDBACK_MARKER
（系统）本轮调用的工具已执行完毕，结果如下：

## FEEDBACK_COMPRESSED
（系统）此前轮次工具读回的文档全文已从上下文移除以节约空间；其中的流程与约束仍须遵守，如确需复核原文请重新调用对应 read_* 工具。

## SKILL_REMINDER
【提醒】当前有选中 Skill：遵守其阶段划分与暂停点，到达确认点时用 workflow_pause 真正停下，不要一口气做完全部阶段。
