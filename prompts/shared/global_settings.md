== 全局生成设置（用户在「全局设置」页配置，必须遵守）==
- 分镜最大时长：{{max_shot_duration}} 秒（自己拆分镜时单个分镜时长不超该值——超限会被系统校正；duration 字段与提示词内总时长描述与其一致）
{{#if image_line}}- {{image_line}}{{/if}}
{{#if video_line}}- {{video_line}}{{/if}}
{{#if chat_image_off}}- 聊天框出图当前关闭：避免主动触发 image_generate{{/if}}
