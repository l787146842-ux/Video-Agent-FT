== studio-actions 文本协议（仅纯文本通道注入：Function Calling 不可用时，用文本块完成全部操作） ==

可用 action:
- add_group: 新建故事板分组（关键元素/分镜/音频）。字段：group_type(keyElement/shot/audio), title, desc, 可选 shotType/sceneRefs/duration/timeRange, 可选 draft(单个草稿) 或 drafts(草稿数组)。
- update_draft: 修改草稿（提示词、标签、参数等）。字段：draft_type(keyElement/shot/audio), draft_id/current, patch。
- clear_media: 清空草稿卡片内的媒体内容（图片/视频/音频），保留提示词与参数。字段：draft_type, draft_id/current。
- update_group: 修改故事板分组。字段：group_type(keyElement/shot/audio), group_id/current, patch。
- add_draft: 给某个分组新增草稿。字段：group_type, group_id/current, draft。若分组不存在会自动创建。
- confirm_draft: 确认草稿。字段：draft_type, draft_id/current。
- delete_draft: 删除草稿。字段：draft_type, draft_id。
- delete_group: 删除整个分组（含其全部草稿）。字段：group_type, group_id。
- bind_asset: 绑定资产。字段：asset_id 或 name/url/type，可选 draft_type/draft_id。
- insert_chat_media: 把故事板卡片里的媒体（图片/视频/音频）自动添加到右侧对话输入框，供用户确认后发送。字段：draft_ids(草稿 ID 数组，优先) 或 target("current"/"all"/"all_keyElements"/"all_shots"/"all_audio")，可选 media_type(image/video/audio)、limit。当用户说“把某个素材/分镜/音频发到对话框”或需要引用故事板媒体时使用；单次最多 8 个。
- select_draft: 选中草稿。字段：draft_type, draft_id。
- write_document: 写入/更新项目文档工件。字段：name（如 "Final_Video_Spec.md"）, content（Markdown 全文）。用于产出制作规格、脚本大纲等文档；已存在同名文档则覆盖更新。
- generate_image: 触发图片生成。字段：target("all_keyElements"/"all_shots"/具体 draft_id), provider_id, model。
  系统会在执行前自动校验目标 Prompt Draft 是否已经用户确认，未确认会被拦截（用户明确要求生成且草稿已确认时调用即可）。
  系统会自动将 sceneRefs 引用的关键元素概念图作为参考图注入。
- generate_video: 触发分镜视频生成。字段：target("all_shots"/具体 draft_id), provider_id, model, resolution, duration。
  确认校验同上（未确认的 Prompt Draft 会被系统拦截）。
  系统会自动将 sceneRefs 引用的关键元素概念图（多参考图）与草稿 refAssets/audioUrl 中的音色参考音频随请求发送给视频模型（Seedance MultiModalToVideo 媒体列表格式）。
{{include:shared/gen_channel_rules.md}}
- script_analyze: 调用 Skill 独立执行器解析上传素材（剧本/图片/PDF），输出一句话总结并保存。字段：可选 doc_name/doc_id。
- storyboard_key_elements: 调用 Skill 独立执行器按当前 Skill 的「故事板设计·关键元素」章节拆解关键元素（角色/场景/道具）并写入故事板。只建关键元素结构，不建分镜与音频。
- storyboard_shots: 调用 Skill 独立执行器按当前 Skill 的「故事板设计·镜头」章节基于已确认的关键元素拆解分镜（镜头列表）。只建分镜结构，不改关键元素与音频。
- storyboard_audio: 调用 Skill 独立执行器按当前 Skill 的「故事板设计·音频」章节拆解音频层（背景音乐/旁白/音效）。只建音频结构，不改关键元素与分镜。
- write_media_prompt: 调用 Skill 独立执行器按当前 Skill 的「提示词写法」章节为草稿逐条编写提示词。
- audio_generate: 调用 Skill 独立执行器生成音频规划（旁白/BGM/音效）或绑定用户上传音频；不生成音频文件。
- video_assembler: 调用 Skill 独立执行器输出成片素材清单、时间轴顺序与组装建议。
- flow_directive: 流程指令。仅当用户本条消息明确要求一条龙/自动推进（如「一条龙」「一口气做完」「中途别问我」）时发出 {"action":"flow_directive","auto_continue":true}，豁免本条消息的流程暂停；用户未明确要求时不得发出。
  以上 7 个执行器会由系统自动注入当前选中 Skill 的对应章节并独立执行，不需要你输出 prompt 全文。

patch/draft 可包含：title, desc, roughDesc, timeRange, duration, label, tag, prompt, imgUrl, videoUrl, mode, model, resolution, aspectRatio, size, timbre, refAssets。
分组（group）级还可包含：shotType（镜头语言，如"长镜头/特写/缓推全景横移/含内部剪辑"）, sceneRefs（本分镜引用的关键元素 title 数组）。

格式示例：
```studio-actions
[
  {"action":"add_group","group_type":"keyElement","title":"Element_二维空间平面","desc":"绝对无厚度、极其锋利的无形平面，任何三维物质与之接触均瞬间被平摊展开","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"深空黑背景中，一条绝对水平的冷蓝白色荧光细线横贯画面中央……（分层描述画面空间与叙事）Hard sci-fi realism, ultra-precise technical illustration, strong chiaroscuro contrast, no text, no labels, no watermarks"}},
  {"action":"add_group","group_type":"shot","title":"Shot_太空艇与宇航员坍缩","shotType":"长镜头","sceneRefs":["Element_监视太空艇","Element_二维空间平面"],"duration":"10s","desc":"太空艇触碰二维平面后逐层坍缩","roughDesc":"起初(0-4s)：中景，太空艇底部接触二维平面，瞬间失去厚度…然后切至(4-7s)：特写，宇航员双脚触碰平面…最后切至(7-10s)：远景，只剩太空艇与人体的平面图案。","draft":{"label":"分镜卡片","tag":"Agent","mediaType":"image","prompt":"……"}},
  {"action":"continue","reason":"下一轮进行审美自检并优化弱提示词"}
]
```
