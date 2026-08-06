# Tool 使用说明（Function Calling 不支持时的 fallback 文本）

当 LLM 供应商不支持 OpenAI 标准 function calling 时，将以下内容注入 system prompt，
让 LLM 以 JSON 文本方式输出工具调用意图，由系统解析执行。

## 可用工具

### storyboard_create_group
创建新的故事板分组（关键元素/分镜/音频），可附带草稿。
参数：group_type(keyElement|shot|audio), title, desc, duration, rough_desc, shot_type, scene_refs[], draft{}

### storyboard_patch_draft
修改指定草稿的字段（提示词、标签、模型等）。
参数：draft_id, draft_type, patch{}

### storyboard_add_draft
给指定分组新增一个草稿卡片。
参数：group_id, group_type, draft{}

### storyboard_delete_group
删除整个故事板分组（含其全部草稿）。
参数：group_id, group_type

### storyboard_confirm_draft
将指定草稿标记为「已确认」。
参数：draft_id, draft_type

### storyboard_media_to_chat
把故事板草稿卡片里的媒体（图片/视频/音频）自动添加到右侧 Agent 对话输入框，供用户确认后发送。
参数：draft_ids[](与 target 二选一，优先), target(current|all|all_keyElements|all_shots|all_audio), media_type(image|video|audio，可选), limit

### view_storyboard_media
按需把故事板草稿卡的图片加载进你的上下文（服务端转 base64 内联，你能直接看到画面）。
编写/修改某条提示词草案前先调用本工具加载对应草稿的图片；每轮只加载当前正在处理的那几张，不要一次拉全部。
参数：draft_ids[](草稿 ID 或「组号-卡序号」编号，与 target 二选一，优先), target(all|all_keyElements|all_shots|all_audio), limit

### document_write
写入/更新项目文档工件（如制作规格、脚本大纲）。已存在同名文档则覆盖。
参数：name, content

### image_generate
触发图片生成（危险操作）。仅当用户明确要求时才可调用。
参数：target(all_keyElements|all_shots|draft_id), provider_id, model

### workflow_pause
暂停工作流并请求用户确认。
参数：message

## 输出格式

在回复末尾追加 JSON 块：
```studio-actions
[{"action": "工具名", ...参数}]
```
