---
name: AI-短剧一站式生成
description: 一站式生成短剧，按顺序确认关键信息后推进流程，适合从创意到成片快速完成。
---
<planner>
**启动协议**

用户触发本 Skill 时，按顺序确认以下信息后再推进：

1. 当前所处阶段（从零开始，还是已有部分产出？）
2. 已有素材（请用户上传或粘贴现有剧本 / 分镜 / 设定图）
3. 输出语言偏好（征询用户；提示词语言遵循档案声明（英文），用户选择优先）

**全流程阶段与依赖关系**

1. 读取并分析用户上传的剧本文件，提取角色、场景、关键道具，识别剧本类型（read_uploaded_doc）
2. 将全局制作参数写入 制片规格.md（画幅比例、目标时长、影像风格基调、输出语言；图像/视频生成渠道与分辨率遵循全局设置）→ **document_write**
3. 设计 Storyboard：登记所有 key_element（角色、场景、关键道具），将剧本拆解为有序 shot 列表，规划 audio_layer（BGM、旁白）→ **storyboard_create_group / storyboard_add_draft / storyboard_patch_draft**
4. 生成所有 key_element 设定图（角色三视图、场景四视图）：提示词先经 storyboard_patch_draft 写入草稿 → **image_generate**
5. 生成每批次运镜轨迹示意图（分镜表格图），供视频生成阶段作视觉锚点参考，这步只用来给用户确认镜头逻辑是否符合预期，不作为视频生成的参考：提示词先经 storyboard_patch_draft 写入草稿 → **image_generate**
6. 逐 shot 生成视频，每镜仅引用对应 key_element 图像；仅在与上一镜连续性极强时额外引用上一镜视频作为 reference_video：视频提示词先经 storyboard_patch_draft 写入草稿，再调用 **generate_video**
7. 生成所有 audio_layer 音频资产（台词、BGM、旁白）→ 由系统音频生成通道按各 audio_layer 类型产出（无需工具调用）
8. 按 Storyboard 顺序组装时间线，完成音画同步与剪辑输出——由用户在工作台操作，Agent 引导即可（无对应工具调用）

**依赖关系：** 3→1,2；4→3；5→3；6→4,5；7→3；8→4,5,6,7

**关键暂停点：** 每个阶段完成后必须暂停，等待用户确认再继续。绝不一口气输出全部步骤——这会让纠错成本爆炸。重点暂停节点：

- 剧本分析完毕、Storyboard 草稿确认后（进入生成前）
- 所有 key_element 设定图确认后（进入视频生成前）
- 所有分镜表格图生成完毕后（进入视频生成前）
- 所有分镜视频生成完毕后（进入组装前）

**剧本兼容性：** 若用户上传的是散文体小说而非分镜脚本，在分析阶段识别并告知用户，引导其先完成短剧改编再继续；剧本中未描述的角色外貌或场景细节一律主动询问用户（擅自补全排除在外）。

**信息缺失处理：** 剧本中未写明的角色长相、场景细节、影像风格，一律主动询问用户（静默假设或擅自补充排除在外）。
</planner>

<script_analyze>
**剧本文件接收与分类**

接受以下输入形式：.txt、.docx 文件上传，或用户直接粘贴的文本内容。

通读剧本后，首先判断其类型并输出分类结论，供 Planner 据此决定后续路径：

- **A 类 — 成熟分镜剧本：** 已按场景/镜头明确划分，包含景别、运镜、台词等要素 → 可直接进入 Storyboard 设计阶段。
- **B 类 — 散文体小说 / 纯对话文本：** 无镜头结构，仅有叙事或人物对话 → 须告知用户，建议先完成短剧化改编（将叙事转化为分镜脚本）再继续；剧本中未描述的角色外貌或场景细节一律向用户确认（自行补全排除在外）。
- **C 类 — 半结构化剧本：** 有基本场景描述或简单镜头标注，但缺少完整分镜语法（景别/机位/运镜不全）→ 可直接进入 Storyboard 设计阶段，在拆解 shot 时补全缺失的分镜要素。

**提取结构化信息**

无论哪类剧本，在分析阶段均需提取并输出以下结构化信息，供后续阶段使用：

- **角色清单：** 姓名、出场场景、外貌/服装描述（仅提取剧本中已明确描述的内容，缺失项标注"待用户补充"）
- **场景清单：** 场景名称、空间特征描述、出现的镜头范围
- **关键道具：** 对剧情或视觉有重要作用的道具
- **剧情结构：** 幕次划分（开篇/发展/转折/高潮/结尾）及各幕大致镜头数量估算
</script_analyze>

<storyboard_key_elements>
**设计 key_element**

- 登记所有**主要角色**（element character）、**关键场景**（element scene）、关键道具（prop element）作为 key_element。
- 角色描述须包含：年龄/性别/外貌/发型/服装/标志性细节；若角色在剧情中有多套造型或不同时间线形象，在描述中分别列出（如"造型A：…；造型B：…"）。
- 场景描述须包含：空间结构、固定参照物（不可移动的视觉地标）、材质/光源/色温/氛围词。这些描述是后续每个 shot 空间连续性的锚点。
- 角色的声音特征（音色/语气/情绪基调）单独登记为 key_element_audio，与角色元素绑定，用于视频生成时的音频条件。
</storyboard_key_elements>

<storyboard_shots>
**拆解 shot 列表**

- 每个 shot = 一次生成任务，时长遵循全局设置中的时长参数（超出上限必须拆分）。
- **批次拆分规则**（每个 shot 视为一个批次单元）：
  - 单 shot 时长遵循全局设置中的时长参数
  - 单 shot 内切镜数量建议 2—6 个
  - 单 shot 出场人物 ≤ 3 人，超出须拆分
  - 单 shot 保持空间一致性，跨物理空间必须切新 shot
- **优先设计较长镜头**，充分利用视频生成能力在单次生成中支持内切镜和丰富运镜；避免将一个连续场景拆成过多短镜头。
- 每个 shot 描述必须包含：
  - **场景**：引用对应 element scene ID
  - **人物动作与对白**：以时间顺序描述人物行为、面部表情、台词（写出具体台词文本）
  - **分镜语法三件套**：景别（大特写/特写/近景胸像/中景/中全景/全景/大全景）+ 机位（平视/俯拍/仰拍/过肩/正侧面等）+ 运镜（固定/推进/拉远/横摇/跟随/环绕/升降等），三者缺一不可
- 同一物理空间的连续场景尽量归入同一或相邻 shot；跨场景需明确标注空间切换。
- 人物在相邻 shot 之间的位置/朝向/手持物必须连贯，Storyboard 中需显式维护这一状态。

**全局空间锚点卡（每 shot 开头声明）**

每个 shot 描述的开头须附一张空间锚点卡，格式如下：

【空间锚点 / 场景名】
固定参照物：（不可移动的视觉地标，如"破旧防盗门位于画面中心"）
人物当前状态：
· 角色A：\[位置 + 朝向\]
· 角色B：\[位置 + 朝向\]
光影基调：（光源类型 + 色温 + 氛围词）

空间锚点卡是跨镜保持空间一致性的关键锚点，确保相邻 shot 之间人物位置、光影连贯（省略排除在外）。

**Storyboard 完稿前自检清单**

交付 Storyboard 前逐项核查并向用户报告结果：

- \[ \] **遗漏检查**：原剧本中所有关键动作、台词、转折是否都有对应 shot？
- \[ \] **逻辑一致性**：人物在前后 shot 的位置/朝向/手持物是否连贯？
- \[ \] **接镜顺畅度**：前一 shot 出画方向与后一 shot 入画方向是否符合轴线规则（不跳轴）？
- \[ \] **时长合规**：每个 shot 合计时长是否符合全局设置中的时长参数？每个内切镜是否在景别建议时长内？
- \[ \] **空间一致性**：同一 shot 内是否未跨场景？光影基调是否与前 shot 衔接（除非剧情需要硬切）？
- \[ \] **角色一致性**：角色代号是否全程统一，无同人异名？
- \[ \] **音效/台词位置**：是否紧贴对应动作，无错位？

如有问题，先与用户确认是否修改，再继续下一步（静默修改原稿排除在外）。
</storyboard_shots>

<storyboard_audio>
**设计 audio_layer**

- **BGM**：全剧至少规划一条背景音乐轨。若剧情有明显情绪转折点（如 3 分钟以上长片），可分段设计多条 BGM（各有独立 audio_layer ID 和覆盖镜头范围）。
- **旁白**：如有画外音/旁白，以 narration 类型登记，注明音色特征、语气、具体台词文本及覆盖的镜头范围。
- 视频生成阶段视频本身**不内嵌 BGM**（在 audio_layer 独立生成后于组装阶段混音）；台词/音效可在视频生成时内嵌。
</storyboard_audio>

<image_generate>
**key_element 设定图生成**

- 使用 **TextToImage** 生成所有角色和场景设定图，模型与分辨率按全局设置的默认渠道填写。
- **角色三视图**：单张图中并排三个全身视角（正面/侧面90°/背面），服装/配饰/发型/体型在三个视角中保持完全一致，中性灰背景，柔和均匀的影棚光。
- **场景四视图**：单张图中 2×2 宫格排列四个角度（建立全景/主入口中景/关键道具特写/反向视角），光源/色调/陈设在四格之间保持一致，画面中无人物。
- 设定图生成后必须暂停，由用户确认视觉风格与剧本一致后，再绑定到对应 key_element 并进入视频生成阶段。

**分镜表格图（运镜轨迹示意图）生成**

- 在视频生成阶段开始前，为每个 shot 生成一张运镜轨迹示意图作为视觉施工图纸。
- 使用 **ImageToImage**，模型与分辨率按全局设置的默认渠道填写；同时上传该 shot 涉及的角色三视图和场景四视图作为 reference_image，确保画风/角色/场景一致。
- 分镜表格图需包含四大要素：运镜轨迹箭头（推进/拉远/环绕/升降/跟随/固定各用不同颜色区分）、每切镜的中文动作说明、景别与时长标注、机位示意（相机图标+虚线轨迹）。
- 具体提示词写法见下方「媒体提示词」章节。
</image_generate>

<generate_video>
**分镜视频生成**

- 使用 **generate_video**（MultiModalToVideo 多模态参考通道），模型与分辨率按全局设置的默认渠道填写。
- 每个 shot 的参考输入默认包含：该镜涉及的所有角色 key_element 图像 + 对应场景 key_element 图像。
- 仅当本镜与上一镜的连续性极强（如同一动作的延续、无剪切的场景推进）时，额外添加上一镜的 final_shot 视频作为 reference_video；**通常不加视频参考**，避免模型过度继承上一镜构图而削弱本镜的运镜设计。
- 每个 shot 视频生成时，将对应角色的 key_element_audio 作为音频条件，保持角色音色跨镜一致。
</generate_video>

<audio_generate>
**音频生成**

- BGM（music 类型）：由系统音频生成通道（text_to_instrumental 纯音乐通道）按草稿配置产出，模型与分辨率按全局设置的默认渠道填写（注意：提示词中知名音乐人名字排除在外）。
- 旁白（narration 类型）：由系统音频生成通道（text_to_narration 旁白通道）按草稿配置产出，模型与分辨率按全局设置的默认渠道填写。
</audio_generate>

<write_media_prompt>
**内切镜时长估算（视频提示词撰写前）**

若 Storyboard shot 未标注各内切镜时长，按以下经验值估算，确保单 shot 合计时长符合全局设置中的时长参数：

| 镜头类型 | 建议时长 |
| --- | --- |
| 大特写 / 手部脚部特写 | 1.5–2.5s |
| 面部特写（含台词） | 2–4s |
| 近景胸像（含台词） | 2.5–4s |
| 中景 / 中全景 | 3–5s |
| 全景 / 大全景建立镜 | 3–5s |
| 运镜推进 / 拉远 / 环绕 | 基础景别时长 +1s |

超出全局设置的时长上限必须拆分为独立 shot。

**角色三视图提示词（TextToImage，具体渠道与模型由全局设置决定，本文档不指定）**

A character turnaround sheet of \[角色描述，含年龄/性别/外貌/服装/标志性细节\].
Show three full-body views in one image, evenly spaced left-to-right:
Front view (facing camera) | Side view (90° profile, facing right) | Back view (facing away).
Identical clothing, accessories, hairstyle, and body proportions across all three views.
Plain neutral gray background (#888888), soft even studio lighting, no shadows on background.
Photorealistic, cinematic film still aesthetic, PANAVISION lens look, 8K detail.
No text, no labels, no watermark.

**场景四视图提示词（TextToImage，具体渠道与模型由全局设置决定，本文档不指定）**

A location reference sheet of \[场景描述，含空间结构/材质/光源/色温/标志物\].
Show four angles of the same location in one composite image (2×2 grid):
Top-left: Wide establishing shot |
Top-right: Medium shot from main entry point |
Bottom-left: Detail shot of key prop or feature |
Bottom-right: Reverse angle from opposite side.
Identical lighting, color palette, and props across all four panels.
No people in frame. Photorealistic, \[光影基调描述\], PANAVISION cinematic, IMAX 70mm film grain.
No text, no labels, no watermark.

**分镜表格图（运镜轨迹示意图）提示词（ImageToImage，具体渠道与模型由全局设置决定，本文档不指定）**

A professional storyboard sheet titled "\[Shot ID\] 运镜轨迹示意图" in Chinese,
clean white background, top-to-bottom vertical layout.

\[Header\]: bold Chinese title "镜头运动轨迹示意图"; subtitle: "\[本 shot 剧情一句话概括\]";
legend box — colored dashed arrows: 推进=red, 拉远=blue, 环绕=green, 升降=purple, 跟随=orange, 固定=cyan.

\[Main content — one row per internal cut\]:
Left (10%): numbered circle + Chinese shot description (景别 + 动作摘要, 2–3 lines)
Center (70%): wide cinematic frame showing the scene; camera icon 📷 marks start position,
dashed arrow shows movement path
Right (20%): Chinese shot type label + one-sentence purpose note

\[Footer\]: pacing summary in rounded box: "整体节奏：\[情绪词1\]→\[情绪词2\]→\[情绪词3\]"

Style: all text Simplified Chinese, clean sans-serif; frame thumbnails photorealistic,
matching attached reference images exactly; vertical 3:4 layout.

Reference images attached:\

- Image 1: Character sheet for @\[角色代号\] — replicate exactly\
- Image 2: Location sheet for @\[场景代号\] — replicate exactly

**单 shot 视频提示词**

每个 shot 输出一段提示词，结构如下：

\[影像风格\]: PANAVISION cinematic, anamorphic widescreen, IMAX 70mm film grain,
24fps, natural depth of field, three-point dramatic lighting, cinematic color grading.

\[场景\]: <<<image\_场景>>> — \[当前光影基调描述\]

\[角色\]: <<<image\_角色>>> — \[当前服装/状态，与设定图一致\]

\[镜头\]: \[景别\] + \[机位角度\] + \[运镜方式\]
示例: Medium waist shot, fixed camera, eye-level

\[动作\]: \[人物动作分解，按叙事顺序推进，主要动作→次要动作；
避免写绝对秒数，用 slow / quick / lingering 描述节奏\]

\[音效\]: <\[音效描述，紧贴对应动作\]>

\[台词\]: {\[角色\]说: "\[台词原文\]"} (with \[情绪词\] tone)

\[禁止\]: No subtitles, no background music, no text overlay, no watermark.

\[时长\]: Approximately \[X\]s

**固定尾部规则：**

- 所有视频提示词末尾必须包含 No subtitles, no background music, no text overlay——BGM 在 audio_layer 独立生成，后期混音；台词/音效可内嵌。
- 若所选视频渠道支持内嵌音频/文本标记（具体渠道与模型由全局设置决定，本文档不指定）：音乐 (...)、音效 <...>、台词 {...}（非项目语言需在括号前标明语言）、片内字幕 【...】；台词括号内只写原文，不加情绪标注。
- 不依赖绝对时间戳（如 "0–3s"）描述动作节奏，改用速度形容词。
</write_media_prompt>

<video_assembler>
**首尾帧衔接策略**

- 第一个 shot：以对应场景 key_element 四视图中的建立全景角度作为 start_frame。
- 后续每个 shot：以上一个 shot 视频的最后一帧作为本 shot 的 start_frame，确保人物位置/朝向/手持物与 Storyboard 空间锚点卡中该 shot 的初始状态完全吻合。如有偏差，须重新生成上一 shot 或调整本 shot 空间锚点描述（跳过检查直接拼接排除在外）。

**剪辑节奏与过渡**

- 按 Storyboard shot 顺序顺序组装；对话密集段落保持紧凑剪辑，情绪特写给足呼吸时间。
- 同一物理空间内的相邻 shot 优先使用无缝硬切；跨空间切换可使用淡入淡出（0.3s 以内），避免过度使用转场特效。
- 注意 180° 轴线规则：若两个相邻 shot 之间出现跳轴，在中间插入一个正面或过肩过渡 shot，而非强行拼接。

**音频混音层级**

- BGM（audio_layer）音量低于人声 8–12 dB，作为底层垫乐；情绪高潮段可适当提升 3–5 dB。
- 台词/音效已内嵌在视频轨中，组装时不额外叠加同类音频，避免重复。
- 旁白（narration audio_layer）音量与台词层平齐，需在时间线上与对应 shot 对齐。
- BGM 与旁白/台词交叉淡化处理（crossfade 0.5s），防止硬切产生音量跳变。

**常见生成失败与组装修复**

| 现象 | 原因 | 修复方向 |
| --- | --- | --- |
| 角色外貌跨 shot 漂移 | 提示词角色描述不够具体 | 在「媒体提示词」章节规则中强化设定图特征词，重新生成该 shot |
| 跳轴 | 相邻 shot 机位跨过 180° 轴线 | 插入正面或过肩过渡 shot |
| 镜头时长偏差 | 模型对绝对秒数不敏感 | 改用 slow / quick / lingering 节奏词，组装时用时间线裁剪微调 |
| 字幕乱入 | 视频提示词未明确禁止 | 强化 no subtitles, no text overlay，重新生成 |
| 首尾帧不衔接 | 上一 shot 末帧人物已偏离空间锚点 | 将本 shot 第一个内切镜设计为过渡镜，引导画面回到锚点 |

**导出基准**

- 视频轨分辨率对齐生成时的最高规格；如需提升，经 super_resolution（待平台补齐工具）上采样后再导出。
- 帧率 24fps；如需流畅慢动作片段，对目标 shot 单独执行帧插值（fps 提升至 60）后再并入时间线。
</video_assembler>