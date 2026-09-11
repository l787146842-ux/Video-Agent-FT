# 系统回喂模板（工具结果回喂与流程提醒的单一事实源）

> `## KEY` 分节由 `load_prompt_section` 读取。这些文案是「(系统)」角色的
> 运行时消息模板：回喂进 LLM 上下文但不属于 system prompt 协议。

## FEEDBACK_MARKER
（系统）本轮调用的工具已执行完毕，结果如下：

## FEEDBACK_IMAGES_STRIPPED
（系统）此前轮次加载的故事板图片已从上下文移除以节约空间；如后续仍需看到它们，可重新调用 view_storyboard_media 加载。

## READ_RESULT_BODY_OMITTED
执行成功（全文未附：超单次回喂总量上限）

## READ_SKILL_INDEX_POINTER
执行成功（Skill 流程段与章节目录已随选中 Skill 注入系统提示，无需重复回显；具体章节按名取读）

## READ_SKILL_SECTION_HEADER
read_skill 执行成功，全文如下（skill={name}，section={section}）：

## READ_SKILL_SECTION_DUP_POINTER
执行成功（章节「{section}」全文已于此前读取并在上文中，无需重复回显）

## DIGEST_POINTER
{name}：执行成功（结果已写入工作台并投影进状态 JSON，冗长详情回喂已省略；最新状态以工作台状态 JSON 为准）

## ARG_DIGEST_PLACEHOLDER
【已落账：本参数全文已写入工作台状态 JSON，此处省略；最新状态以工作台状态 JSON 为准】

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
（系统）第 {{step}} 轮的 {{count}} 个 Tool 已执行完毕（如需最新工作台全量状态，可调用 read_state_group 按组读取）。

<!-- STEP_FEEDBACK_AT_PAUSE 已随指令收拢批补丁退役（2026-09-09 实证）：
     「节点翻转完成」≠「Skill 声明的暂停点」，探针误报逼停模型
     （规格写入完成后被谎报到点，同批建组调用全冻结）；停的判定
     唯一归《Skill 流程纪律》第 2 条判定式，回喂退回纯事实（P3，
     不携带任何方向性催促）。 -->

## MECHANICAL_HISTORY_PLACEHOLDER
（上轮为系统机械动作清单，已并入时间线；明细见状态 JSON 与事件卡）

## TOOL_RESULT_SUSPENDED
（该调用未执行完成，会话在此中断）

## COMPACTION_INSTRUCTION
请将以上对话浓缩为一份结构化摘要，供后续对话作为已确立背景继续任务：保留任务目标与用户要求、已完成步骤及关键产物（含名称/id）、重要约束与偏好、当前进度与下一步。不要新增对话、不要提问。若以上对话中已包含 <compacted-summary> 摘要块，它是此前轮次的检查点：不要逐字照抄，保留仍属实的事实、丢弃已过时内容，将新旧信息合并为单一摘要。

## COMPACTION_PREAMBLE
（系统检查点：更早的对话区间已浓缩为下方摘要；把它当作既定背景直接继续任务，无需复述或确认。）

<!-- STEP_ASSISTANT_PLACEHOLDER 已随上下文与缓存优化计划批 C2 退役删除：
     assistant 消息改带标准 tool_calls（content 为空合法），占位文案无消费点 -->

## EMPTY_RESPONSE_FALLBACK
这一步没有返回可见内容。回复「重试」可再次执行；若连续出现，可尝试切换模型。
