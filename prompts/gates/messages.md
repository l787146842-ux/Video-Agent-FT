# 闸机系统文案（prompt_gates.py 的唯一事实源）

> 本文件是闸机拦截/警告/暂停文案的单一事实源：代码只负责加载与组装，
> 不再硬编码文案。`## KEY` 分节由 `load_prompt_section` 读取；
> 带选项的分节正文为 JSON（message + options）。
> 文案同时用于：回喂模型修正（自愈闭环）与前端用户侧展示（同一说辞，防两套话术）。
> 语义基线：流程闸对用户只警告不拦人；结构闸 strict 下拒收重写。

## GENERATION_CONFIRM
流程警告：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。本次生成已按用户要求照常触发，请同时在回复中提示用户审阅草稿。

## GENERATION_CONFIRM_BLOCKED
流程拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认。请先展示草案并调用暂停工具请求用户审阅；用户接受暂停卡后重提生成即视为已确认，不会重复拦截。也可在工作台把目标草稿标「已确认」后再生成。

## TOOL_RISK_BLOCKED
高风险工具确认闸拦截：'{{name}}' 为 high 级操作（宪法 §2.7），未经用户显式同意不得执行。请先用 workflow_pause 向用户说明本次将执行的操作并请求确认；用户接受暂停卡后重提即视为已确认（本轮内不再拦截）。也可在工作台确认相关草稿，或由用户点「本次放行」。

## STORYBOARD_STRUCTURE_PAUSED
{
  "message": "关键元素拆分已建立，请审阅左侧故事板的元素拆分结果（数量/命名/描述）；确认无误后按当前 Skill 流程推进下一阶段。",
  "options": [
    {"label": "确认，按当前 Skill 流程推进下一阶段", "description": "拆分无误，下一步以当前 Skill 流程为准"},
    {"label": "调整关键元素拆分", "description": "告诉我需要增删改的元素"}
  ]
}

## SHOT_STRUCTURE_PAUSED
{
  "message": "分镜拆解已完成，请在左侧故事板审阅分镜拆分方案（镜头数量/时间轴/镜头语言）；确认无误后按当前 Skill 流程推进下一阶段。",
  "options": [
    {"label": "确认，按当前 Skill 流程推进下一阶段", "description": "拆分无误，下一步以当前 Skill 流程为准"},
    {"label": "调整分镜拆分", "description": "告诉我需要增删改的镜头"}
  ]
}

## PAUSE_SLOT_ASSERTION
单一活跃暂停槽位冲突告警：已有未消费的暂停卡时再次发行 workflow_pause，旧卡作废 + trace 留痕（pause_slot_collision）+ 发行新卡 + 继续等待人工确认，不拒收。防御断言只告警留痕，不作拒因回喂；暂停三态以新卡为准事务写入，绝不未经确认自动继续。

## PROMPT_REPEAT_ESCALATION
[连续第 {{n}} 次因相同原因被拦截] 上一次重写未修正上述问题，请逐条对照原因彻底改写（不是换措辞：中文占比/字数/镜头语言标记必须实质达标），禁止再次提交相似文本。

## SINGLE_IMAGE_QUOTA_BLOCKED
image_generate（mode='single'）每轮只调用一次；需要多张图片时改用批量模式（mode='batch'，明确 target 范围）。

## DRAFTS_REVIEW_PAUSED
{
  "message": "提示词草案已写入，请在左侧故事板审阅草案内容；确认后我将按全局设置中的生成渠道触发生成。",
  "options": [
    {"label": "确认提示词草案，按当前 Skill 流程推进", "description": "将目标草稿标记为已确认，按当前 Skill 流程推进"},
    {"label": "先调整提示词", "description": "告诉我需要修改的草稿与修改意见"}
  ]
}
