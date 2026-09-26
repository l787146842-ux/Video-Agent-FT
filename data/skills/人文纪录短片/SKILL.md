---
name: 人文纪录短片
description: 制作人文纪录短片，先确认制片规格（题材地域、画幅、时长、视觉风格），再推进故事板与生成。
---
<planner>
**全片流程与阶段依赖：**
1. 和用户确认并建立 制片规格.md（片名、题材地域、画幅比例、目标时长、视觉风格、输出语言）→ document_write
2. 生成故事板（关键元素、镜头列表、音频层）→ storyboard_designer。故事板准备就绪后，扫描当前上下文，查找用户提供或之前生成的、与故事板条目匹配的任何资产（例如元素图像、背景音乐）。对于每个匹配项，在进行生成步骤之前，将资产登记到相应的故事板参考字段
3. 设置元素：
- 如果用户已经上传了元素资源（例如角色图像或引用的参考角色），直接将其登记为相应 key_elements 草稿的参考资产。
- 否则，为所有元素生成图像（提示词先经 storyboard_patch_draft 写入草稿）→ image_generate。
4. 为每个镜头生成首帧图（start_frame；提示词先经 storyboard_patch_draft 写入草稿）→ image_generate
5. 参考步骤4的首帧图生成视频：视频提示词先经 storyboard_patch_draft 写入草稿，再调用 **generate_video**
6. 生成 BGM 音频层 → 由系统音频生成通道产出（无需工具调用）
7. 全片时间线组装与导出由用户在工作台操作，Agent 引导即可（无对应工具调用）

**依赖顺序：** 2→1；3→2；4→2；5→4；6→2；7→5,6
**暂停节点：** 流程分阶段推进（一次性跑完全部流程排除在外）。在 Storyboard 完成、元素图/首帧图完成、视频完成、音频生成后各暂停，等待用户确认再继续。
注意: 用户提供或预先存在的媒体（主要影响第 3-5 步）： 在填充生成内容之前，先将媒体登记到适当的故事板参考字段；避免重复生成用户已提供的内容。

**建立 制片规格.md 的指南**
1. 片名：名称应契合“人文纪录片”调性，避免过度商业或浮夸的命名
2. 题材地域
- 地域限定范围：引导用户在以下区域中选择：亚洲、非洲、中东、南美、东欧、东南亚、海岛国家、发展中国家
- 题材核心限制：题材必须聚焦“真实的人”与“普通人的生活”，拒绝“城市宣传片”
3. 画幅比例：遵循全局设置中的画幅参数（纪录片常用横屏或宽银幕画幅）
4. 视觉风格：锁定为“像真实摄影师长期驻扎拍摄”、“像奥斯卡/国际电影节纪录片”、“Netflix纪录片风格”或“国家地理式观察影像”。明确“不做”的风格（避雷清单）：“AI感、商业广告感、强戏剧感、网红风”一律排除在外。
5. 画面质感要求：
- 包含空气感：灰尘、水汽、潮湿、热浪、风。
- 光线限定：仅限自然光（晨光、黄昏、阴天、窗边光）。
- 保留不完美：允许并刻意保留轻微失焦、曝光波动、真实混乱感。
</planner>

<script_analyze>
- 若用户上传参考图片或视频，提取以下信号供下游使用：主体身份与外貌特征、场景地点与环境氛围、光线条件（方向 / 色温 / 质感）、画面色调与饱和度风格。
- 输出结构化描述，不做主观评价。
</script_analyze>

<storyboard_designer>
**全球人文纪录片剧本与剧情规划规范**
一、 核心叙事理念：观察生活，而非“拍故事”
- 去戏剧化：摒弃强戏剧冲突、商业广告式的剧情设计。剧情规划重点不在于“讲一个起承转合的故事”，而是呈现“真实世界的人类生活”。
- 偶发感：剧本中描写的场景和事件，不应有“导演刻意安排”的痕迹，必须营造出“摄影师长期驻扎时偶然观察到”的自然状态。
- 追求全球纪录片统一审美：如Netflix纪录片或国家地理式观察影像，打造全球观众都能理解和共情的人文叙事，避免刻板的单一地域风（如纯网红风、纯欧美风）。
二、 叙事主体与切入点：先拍“人”，不拍“城”
- 拒绝宣传片逻辑：永远不要把“城市面貌”或“宏大景观”作为剧本的首要表现对象，这不是城市宣传片。
- 聚焦真实人类：剧情永远从“人”切入，通过普通人的真实生活状态来折射其背后的文化与环境。
三、 剧情细节与动作设计（最易共情的描写点）
在撰写剧本和场景描述时，应着重刻画以下细节动作，而非宏大的事件：
- 聚焦手部劳作：做饭、缝纫、洗衣、写字、手工劳动。
- 人物背影与状态：在场景描述中，多使用“背影”作为主视觉，这比直接展现正脸更具高级感和故事留白感。
- 日常微小动作：点烟、喝茶、发呆、看着窗外（用这些无特定目的的“小动作”来构建时间流动的真实感）。
四、 按地域划分的场景/题材规划库
在为不同发展中国家或地区规划剧本时，直接选用以下最能体现当地原生人文气息的场景和事件：
- 亚洲题材：清晨的早餐摊、老茶馆里的闲谈、熙熙攘攘的传统市场、原生态的渔村、老旧的铁路边。
- 非洲题材：黄昏尘土下的归途、热闹的集市、奔跑的孩子、雨季的日常、传统的手工劳动。
- 南美题材：随性的街头音乐表演、充满生活气息的老城区、海边日常、街头/土路足球场、夜市的烟火气。
- 中东题材：阳光穿透的传统市场、专注的手工艺制作过程、虔诚的祈祷时刻、沙尘环境下的生活常态。

**关键元素设计*
- 优先设计**人物元素**（年龄、外貌、着装、正在做的事）和**场景元素**（地理环境、时段、光线条件、空气质感）。
- 道具元素只在对多个镜头一致性有实质影响时才单独建立。
- 用户提供参考素材时，元素描述必须与参考内容一致（矛盾排除在外）。

**分镜镜头设计原则**
- **时长：** 镜头时长遵循全局设置中的时长参数；避免设计过短、缺乏信息量的镜头。
- **观察性叙事：** 镜头不"设计故事"，而是"偶然看见生活"。优先拍手部劳动、背影、微小日常动作（点烟、喝茶、发呆、看窗外）；避免正面表演式构图。
- **运镜极简（按优先级排序）：** 一个分镜之描述一个镜头
  1. 固定镜头（最推荐）
  2. 微弱手持（仅呼吸感 / 轻微漂移）
  3. 极慢推进或极慢横移
  - 禁止：旋转、快速推拉、无人机飞行、炫技运镜、切镜。
- **每个镜头描述必须包含：**
  - **Scene：** 引用场景元素 ID，说明时段与光线
  - **主体动作：** 人物正在做的微小动作，以肢体和神态为主，无需台词
  - **摄影语言：** 景别（特写 / 中景 / 远景）+ 运镜类型 + 焦点策略
- **画面质感：**
  - 自然光优先：晨光、黄昏、阴天散射光、窗边侧光；禁止人工补光感。
  - 空气感必须体现：灰尘、水汽、热浪、潮湿、轻雾中选一种写入镜头描述。
  - 允许不完美：轻微失焦、曝光轻微波动、人物短暂停顿均为真实感加分项。
- **色调体系：**
  - 低饱和、高层次感：高光柔和不过曝，暗部有细节不死黑，肤色真实。
  - 参考色彩风格：Kodak Vision3 / Fuji Eterna / ARRI Alexa Natural。
- **视频中的声音设计：** 市集噪声、风声、雨声、街道声等

**音频层设计**
- BGM（可选）：若使用，选择极简器乐或无调性环境音景；禁止流行音乐节奏。
- 不以对白驱动叙事。
</storyboard_designer>

<image_generate>
**元素图/首帧图生成（每个镜头的 start_frame）**
- 工具：**TextToImage/ImageToImage**，模型与分辨率按全局设置的默认渠道填写
- 首帧图须与 Storyboard 镜头描述的景别、光线、主体姿态一致，作为视频生成的视觉锚点。
- 若用户已上传参考图（人物 / 场景），将其注册为 asset_id 并绑定至对应 Storyboard 元素或镜头槽位，优先用于替代生成。
</image_generate>

<generate_video>
**镜头视频生成**
- 工具：**generate_video**（FirstFrameToVideo 首帧驱动通道），模型与分辨率按全局设置的默认渠道填写
- 以对应镜头的 start_frame 作为首帧输入。
</generate_video>

<audio_generate>
**音频层生成**
- 旁白（如有）：由系统音频生成通道（text_to_narration 旁白通道）产出，具体渠道与模型由全局设置决定，本文档不指定
- BGM：由系统音频生成通道（text_to_instrumental 纯音乐通道）产出，具体渠道与模型由全局设置决定，本文档不指定；风格描述为极简器乐 / 环境音景；不生成歌词类音乐。

**失败处理**
- 若音频生成失败，优先在同一渠道内重试；不要自动切换至其他工具，停止并告知用户。
</audio_generate>

<write_media_prompt>
**首帧提示词**
核心逻辑：聚焦于“决定性瞬间”的捕捉、胶片色彩质感、真实的光影与空气感。摒弃任何运镜和节奏词汇。
1. Prompt 万能公式
[画面主体与微小动作] + [环境与空气感] + [光线状态] + [摄影机语言与景别] + [色彩体系与胶片质感] + [核心精神关键词与大师参考]
2. 核心模块与词汇库
主体与微动作：人物背影 / 抽烟的双手 / 凝视窗外 / 停顿的发呆瞬间。
环境与空气感：弥漫的灰尘 (dusty air)、清晨的水汽 (morning mist)、潮湿感 (dampness)、风吹动衣角 (wind blowing)。
光线状态：自然光 (natural light)、窗边柔和侧光 (soft window light)、阴天漫反射 (overcast diffused light)。
摄影语言：Medium shot (中景) / Close-up (特写) / 极简构图 / 留白 (negative space)。
色彩体系 (原样直出)：Kodak Vision3, Fuji Eterna, ARRI Alexa Natural, low saturation, soft highlights, detailed shadows, real skin tone.
风格与大师参考：Magnum Photos, Leica Documentary, National Geographic, 是枝裕和 (Hirokazu Kore-eda), 贾樟柯 (Jia Zhangke).
3. 示例 Prompt (图片)
(EN) A medium shot of an old man's weathered hands rolling a cigarette, sitting in a dimly lit traditional tea house. Morning mist and dust particles floating in the soft window light. Kodak Vision3 film stock, low saturation, soft highlights, real skin tone. Magnum Photos style, Leica Documentary, observational, honest, real, quiet, timeless. Hirokazu Kore-eda aesthetic.
(ZH解析) 中景，一位老人在昏暗的老茶馆里卷烟的沧桑双手。晨雾和灰尘颗粒在柔和的窗边光线中漂浮。柯达 Vision3 胶片质感，低饱和度，高光柔和，真实的肤色。马格南摄影风格，徕卡纪录片，观察性，诚实，真实，安静，永恒。是枝裕和美学。

**视频提示词**
核心逻辑：聚焦于“时间的流动”、“极慢的节奏与运镜”、“环境的微小变化”以及“长镜头观察感”。
1. Prompt 万能公式
[极其克制的镜头运动] + [主体持续的微小动作] + [环境与光线的微小流逝/变化] + [色彩体系] + [纪录片节奏与电影级参考] + [核心精神关键词]
2. 核心模块与词汇库
镜头运动 (必须克制)：Fixed camera (固定镜头) / Slight handheld breathing (微弱手持呼吸感) / Extremely slow push-in (极慢推进) / Extremely slow pan (极慢横移)。
动作与环境流逝：持续的微小动作 (continuous subtle movement) / 光影随时间缓缓移动 (light shifting slowly) / 持续的微风 (continuous gentle breeze)。
节奏与剪辑指令：Long take (长镜头) / Slow pacing (慢节奏) / No fast cuts (禁止快剪) / Breathing space (呼吸感留白)。
色彩体系：Sony Venice Documentary LUT, ARRI Alexa Natural, cinematic color grading, cinematic shadows.
视频风格与参考：Netflix Documentary (Chef’s Table, Our Planet), Oscar Documentary (Nomadland, Honeyland), 侯孝贤 (Hou Hsiao-hsien) pacing.
3. 示例 Prompt (视频)
(EN) Fixed camera with slight handheld breathing. A slow long take of a South American woman washing clothes by the river. Her back is to the camera. The damp morning air slowly blows her hair. Natural overcast light with subtle environmental shifts. ARRI Alexa Natural, Sony Venice Documentary LUT, low saturation, soft highlights. Cinematic pacing, breathing space, no fast cuts. Nomadland and Honeyland style, Netflix documentary vibe, observational, slow, human, quiet, timeless.
(ZH解析) 固定镜头带有微弱的手持呼吸感。一个缓慢的长镜头：一位南美妇女在河边洗衣服，背对镜头。潮湿的晨风缓缓吹动她的头发。自然的阴天光线，带有微妙的环境变化。ARRI Alexa Natural，索尼威尼斯纪录片LUT，低饱和度，高光柔和。电影级节奏，呼吸感留白，无快剪。无依之地与蜂蜜之地风格，Netflix纪录片氛围，观察性，缓慢，人文，安静，永恒。
</write_media_prompt>

<video_assembler>
**节奏原则**
- 长镜头优先，保留完整的时间流动感；不为追求"有趣"而剪短镜头。
- 镜头间可用 0.5–1s 的黑场或声音延续过渡，制造呼吸感。
- 禁止快剪、音乐卡点、特效转场、TikTok 节奏。

**音画关系**
- BGM（如有）音量低于视频层声音；淡入淡出，不抢画面。
- 不做强制音画同步；画面与声音各自自然流动。
</video_assembler>
