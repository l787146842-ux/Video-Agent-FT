# 系统回喂模板（工具结果回喂与流程提醒的单一事实源）

> `## KEY` 分节由 `load_prompt_section` 读取。这些文案是「(系统)」角色的
> 运行时消息模板：回喂进 LLM 上下文但不属于 system prompt 协议。

## FEEDBACK_MARKER
（系统）本轮调用的工具已执行完毕，结果如下：

## FEEDBACK_COMPRESSED
（系统）此前轮次工具读回的文档全文已从上下文移除以节约空间；其中的流程与约束仍须遵守，如确需复核原文请重新调用对应 read_* 工具。

## FEEDBACK_IMAGES_STRIPPED
（系统）此前轮次加载的故事板图片已从上下文移除以节约空间；如后续仍需看到它们，可重新调用 view_storyboard_media 加载。

## READ_RESULT_BODY_OMITTED
执行成功（全文未附：超单次回喂总量上限）

## DIGEST_POINTER
{name}：执行成功（结果已写入工作台并投影进状态 JSON，冗长详情回喂已省略；最新状态以工作台状态 JSON 为准）

## FAILURE_HINT_REPEAT
该工具已连续失败 2 次，同参重试大概率仍失败，不得再次重试；可向用户说明原因并给出替代选择。

## FAILURE_HINT_VALIDATION
入参/定位问题：按错误信息修正入参后再试，不得用原参重试。

## FAILURE_HINT_RETRYABLE
生产端标注该失败可重试：可用原参或调整参数重试一次。

## FAILURE_HINT_NON_RETRYABLE
该失败不宜原参盲重试：可向用户说明困难，或换替代方案。

## FAILURE_HINT_DEFAULT
可调整参数后重试一次，或先向用户说明困难。

<!-- SKILL_REMINDER 分节已随 S09 退役删除（用户裁决 2026-09-02，唯一消费点 planner._SKILL_REMINDER 同批删除） -->
<!-- BAD_OUTPUT_NUDGE 分节已随五项修法批 2 退役删除（用户裁决 2026-09-07：判空 = 正常收轮，
     nudge 重试退役，唯一消费点 agent_loop._bad_output_nudge 同批删除；退役记录见 core/recovery_policy.py） -->

## STEP_FEEDBACK
（系统）第 {{step}} 轮的 {{count}} 个 Tool 已执行完毕，工作台状态已刷新（见对话末尾最新的工作台状态 JSON）。请继续完成任务；全部完成后直接回复文本即可。

## STEP_ASSISTANT_PLACEHOLDER
（本轮为工具调用轮，正文见工作台状态）

## EMPTY_RESPONSE_FALLBACK
这一步没有生成可见回复（上游可能瞬时抖动）——请直接说「重试」，我再来一次；若连续出现可尝试切换模型。
