# 闸机系统文案（814R2 恢复外置：prompt_gates.py 的唯一事实源）

> 本文件是闸机拦截/警告/暂停文案的单一事实源：代码只负责加载与组装，
> 不再硬编码文案。`## KEY` 分节由 `load_prompt_section` 读取；
> 带选项的分节正文为 JSON（message + options）。
> 文案同时用于：回喂模型修正（自愈闭环）与前端用户侧展示（同一说辞，防两套话术）。
> 语义基线（4444/8888 二轮）：流程闸对用户只警告不拦人；结构闸 strict 下拒收重写。

## SPEC_GATE
流程警告：规格文档尚未写入。建议先调用 document_write 写入规格文档（标题、类型、画幅、时长、视觉风格、语言、模型偏好等制作参数）并请用户审阅；本次故事板结构已按用户要求照常搭建，规格文档仍建议补写。

## STORYBOARD_PENDING
流程警告：故事板结构尚未经用户确认。按 Skill 流程建议先请用户审阅拆分方案再写提示词；本次提示词已按用户要求照常写入，请同时在回复中提示用户审阅左侧故事板。

## SHOT_SEQUENCE
流程警告：关键元素还没有任何概念图（生成或上传）。按 Skill 流程建议先让元素概念图就绪再编制分镜提示词（镜头可参考元素图像）；本次分镜提示词已按用户要求照常写入，若后续生成视频需要参考图，请先补足元素图像。

## GENERATION_CONFIRM
流程警告：目标草稿的 Prompt Draft 尚未经用户审阅确认（tag 非「已确认」）。按 Skill 流程建议先展示草案并等待确认；本次生成已按用户要求照常触发，请同时在回复中提示用户审阅草稿。

## GENERATION_CONFIRM_BLOCKED
流程拦截：目标草稿的 Prompt Draft 尚未经用户审阅确认。请先展示草案并调用暂停工具请求用户审阅；仅当用户在本次消息中明确要求「直接生成/不用确认」时才可直接触发生成。

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

## SPEC_DOC_OPTIONS
[
  {"label": "确认成片规格，按流程继续", "description": "规格内容无误，按当前 Skill 流程推进下一阶段"},
  {"label": "调整成片规格", "description": "告诉我需要修改的规格条目"}
]

## SCRIPT_REMIND_CARD
{
  "message": "这个 Skill 的创作以剧本为原料，当前还没收到剧本文件。请先上传剧本（.txt/.docx）或直接把剧本文字粘贴发给我；若本次想做无剧本从零原创，请点选确认。",
  "options": [
    {"label": "确认从零原创（无需剧本）", "description": "记账豁免，之后按原创流程推进，不再提醒", "value": "waive_script"},
    {"label": "我去上传/粘贴剧本", "description": "系统等你发送剧本，原料一到自动开工", "value": "upload_script"}
  ]
}

## SCRIPT_MODEL_NOTE
剧本未提供。本轮先引导用户上传或粘贴剧本，不做规格收集、拆解结构等下游操作。

## SCRIPT_UPLOAD_ACK
好的，我等你发送剧本（上传 .txt/.docx 或直接粘贴文字）。原料一到立刻开始分析与设计，在那之前不会推进下游环节。
