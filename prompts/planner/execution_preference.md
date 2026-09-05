# 执行偏好注入文案（唯一事实源）

> 消费端 = planner（轮始按 settings.execution_preference 档位选取分节签发
> context.execution_pref_note，经状态尾部消息每步注入）。
> 语义对齐 Flova「素材生成」轴：偏好由模型行为执行（主动先审后生成），
> 闸机（tool_risk / gen_confirm）兜底硬保证——确认路径口径与
> prompts/gates/messages.md 的 GENERATION_CONFIRM_BLOCKED / TOOL_RISK_BLOCKED 一致。

## PREF_CONFIRM_BEFORE_GEN
当前执行偏好：生成前确认——首次生成图片/视频前，先用 workflow_pause 向用户呈现提示词草案并请求确认；用户接受后重提的生成本轮内视为已确认，不会重复拦截；写入制片规格文档同属确认卡兑现（接受后写入不再拦截）。也可在工作台把目标草稿标「已确认」。

## PREF_AUTO_DECIDE
当前执行偏好：自动决定——活跃 Skill 指导下的常规生成免逐次确认（系统代发同意并留痕）；暂停点按所选 Skill 散文执行。

## PREF_GENERATE_DIRECTLY
当前执行偏好：直接生成——生成图片/视频无需生成前确认。
