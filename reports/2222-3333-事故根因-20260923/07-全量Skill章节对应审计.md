# 07 · 全量审计：**全部 16 个 Skill** 的章节字段在本项目中的对应情况

> **用户原问**：「**本项目的所有 skill 里面这些章节字段到底有没有对应在本项目中，要搞清楚。**」
> **本文件**：对 `data/skills/` 下**全部 16 个 Skill** 逐章节实测。
> 全部数字由 `.tmp_probe/all_skills_audit.py`、`consumption_audit.py`、`inject_fixed.py`
> 实跑产出，可重放。**Skill 零改动**（只读审计）。

---

## 一、结论先行（三句话）

1. **章节名层面：全部对应，零缺口。** 16 个 Skill 用到的 **15 个章节 tag，全部**被平台
   `SECTION_TAG_STAGES` 认识（未映射 = **0**）。**这一层没有问题。**
2. **注入层面：10 个真实章节里有 4 个"发不出去"**（`image_generate`/`generate_video`/
   `audio_generate`/`video_assembler` —— 对应 section `generation`/`assembly` **不可注入**）。
3. **字段层面：这才是真正对应不上的地方。** 15 个 tag 里**只有 2 个真正被消费**，
   **6 个半对应**、**2 个无承载**、7 个是兼容别名。
   **用户说的"字段对应不上"，准确位置在第三层。**

---

## 二、Skill 清单（16 个）

```
3D国漫古装精品短剧     AI-短剧一站式生成      人文纪录短片        剧情短片音色参考
叙事驱动的美学视频      古风甜宠短剧           商品宣传短片        多人对话访谈
宣言式概念短片         故事驱动型视频         新-Skill            未来科幻真人电影
李安美学风格短片        水墨风格武侠短片        视频拉片复刻        音乐MV需上传音乐
```

**章节数分布**：6–10 个/每 skill，合计用到 **15 个去重 tag**。

---

## 三、第一层：章节名 → 平台映射（✅ 全部对应）

| 章节 tag | 用它的 Skill 数 | 平台是否映射 |
|---|---|---|
| `<planner>` | **16**（全部） | ✅ |
| `<video_assembler>` | **16**（全部） | ✅ |
| `<script_analyze>` | 15 | ✅ |
| `<write_media_prompt>` | 15 | ✅ |
| `<storyboard_key_elements>` | 14 | ✅ |
| `<storyboard_shots>` | 14 | ✅ |
| `<storyboard_audio>` | 14 | ✅ |
| `<generate_video>` | 13 | ✅ |
| `<image_generate>` | 7 | ✅ |
| `<audio_generate>` | 6 | ✅ |
| `<storyboard_designer>` | 2 | ✅ |
| `<media_generator>` | 2 | ✅ |
| `<generation>` | 1 | ✅ |
| `<multimodal_analyze_tool>` | 1 | ✅ |
| `<write_the_prompt>` | 1 | ✅ |

**⇒ 未映射 tag = 0 个；每个 Skill 的"已映射/总章节"都是满分**（如 10/10、9/9、8/8）。

**平台映射表另有 2 个兼容别名**（无任何 Skill 使用，备给外来 Skill）：
`<resource_prepare_and_analyze>`、`<text_editor>`。

> **这一层用户不必担心**：章节名一个都没漏。

---

## 四、第二层：章节 → 能否注入执行者（⚠️ 4 个发不出去）

**注入链的正确判据是 `capability(stage) → section`，而"可委派"名单只有 3 个：**
```
PIPELINE_STAGE_KINDS = ['script_analyze', 'storyboard_design', 'write_media_prompt']
```

实测反查各 section 的注入路径：

| section | 能取到它的 capability | 可否注入 |
|---|---|---|
| `planning` | `script_analyze` | ✅ |
| `prompt_draft` | `write_media_prompt` | ✅ |
| `storyboard_ke` | `storyboard_key_elements` / **`storyboard_design`** | ✅ |
| `storyboard_shot` | `storyboard_shots` / **`storyboard_design`** | ✅ |
| `storyboard_audio` | `storyboard_audio` / **`storyboard_design`** | ✅ |
| **`generation`** | `audio_generate`（不在委派面） | ❌ **不可注入** |
| **`assembly`** | `video_assembler`（不在委派面） | ❌ **不可注入** |

### 逐真实章节（10 个）注入判定

| 章节 | stage | 可注入 |
|---|---|---|
| `<planner>` | `planning` | ✅（注入主代理） |
| `<script_analyze>` | `planning` | ✅ |
| `<storyboard_key_elements>` | `storyboard_ke` | ✅（经 `storyboard_design` 合并注入） |
| `<storyboard_shots>` | `storyboard_shot` | ✅（同上） |
| `<storyboard_audio>` | `storyboard_audio` | ✅（同上） |
| `<write_media_prompt>` | `prompt_draft` | ✅ |
| **`<image_generate>`** | `generation` | ❌ |
| **`<generate_video>`** | `generation` | ❌ |
| **`<audio_generate>`** | `generation` | ❌ |
| **`<video_assembler>`** | `assembly` | ❌ |

**⇒ 4 个章节"取得到正文却发不出去"**：实测 `tool_sections` 对
`audio_generate`(1086 字)、`video_assembler`(1113 字) 都能取到正文，
但因其 capability 不在委派面，**永远无法精准注入**。

**这是 2026-09-22 批6「三阶段合并」的未登记副作用**：
合并把 3 个原子阶段从委派面退役，**能力面仍留 7 个名字**，
两边漂移至今**无任何 lint 覆盖**。

---

## 五、⭐ 第三层：章节 → 字段/承载（❌ 用户说的"对应不上"在这里）

| 章节 tag | 章节要求产出 | 平台承载 | 消费状态 |
|---|---|---|---|
| `<planner>` | 全局流程编排（阶段/依赖/暂停点） | 主代理编排依据 | ✅ **消费** |
| `<script_analyze>` | 剧本分析报告 | `script_analysis_report` + analysis 类目 | ✅ **消费** |
| `<storyboard_key_elements>` | key_element 登记 + **角色音色卡** | keyElements 类目 | ⚠️ **半**：无 `elementType`/`audioType` 字段；`key_element_audio` 无语义承载 |
| `<storyboard_shots>` | shot 列表（内切镜/时长/三件套） | shots 类目（`desc`+`summary`） | ⚠️ **半**：`summary` 只校验非空+键序；**逐内切时长不校验** |
| `<storyboard_audio>` | audio_layer（BGM/旁白） | audioItems 类目（`desc`） | ⚠️ **半**：无 `audioType` 字段 |
| `<write_media_prompt>` | 四类提示词 | 卡片 `prompt` 字段 | ⚠️ **半**：`<<<image_>>>` 前端不渲染；`@` 引用 **0 命中**；逐内切时长未校验 |
| `<image_generate>` | KE 设定图 | `image_generate` 工具 | ⚠️ **半**：章节不可注入；工具可用 |
| `<generate_video>` | 逐 shot 视频 | `generate_video` 工具 | ⚠️ **半**：章节不可注入；工具可用 |
| **`<audio_generate>`** | BGM/旁白/音色样本 | ❌ **承载不存在** | ❌ **未消费** |
| **`<video_assembler>`** | 组装/首尾帧/混音/导出 | ❌ 无工具 | ❌ **无承载** |
| （7 个兼容别名） | — | 归对应 stage | ? 别名 |

### 归类统计（15 个 tag）

| 类别 | 数量 | 清单 |
|---|---|---|
| ✅ 真正消费 | **2** | `planner`、`script_analyze` |
| ⚠️ 半对应 | **6** | `storyboard_key_elements`、`storyboard_shots`、`storyboard_audio`、`write_media_prompt`、`image_generate`、`generate_video` |
| ❌ 未消费/无承载 | **2** | `audio_generate`、`video_assembler` |
| ? 兼容别名 | 7 | `multimodal_analyze_tool`、`resource_prepare_and_analyze`、`text_editor`、`storyboard_designer`、`write_the_prompt`、`media_generator`、`generation` |

**（真实章节 10 个：✅2 / ⚠️6 / ❌2）**

---

## 六、"字段对应不上"的精确机制

用户点名的三章**确实对应**三个类目：

| Skill 章节 | 前端类目 | 成立 |
|---|---|---|
| `<storyboard_key_elements>` | **keyElements** | ✅ |
| `<storyboard_shots>` | **shots** | ✅ |
| `<storyboard_audio>` | **audioItems** | ✅ |

**但对应只到「类目」这一层，没到「字段」这一层。** 原因是三级链缺中间一级：

```
Skill 章节  ──✅──▶  section 代号（storyboard_ke…）  ──❌──▶  前端类目  ──❌──▶  字段
   （模型看得懂）        （模型看不到）                    （模型看不到）      （模型可见但无 Skill 语义）
```

- 章节 → **section 代号** ✅（平台内部有）
- 章节 → **stage 名** ✅（平台内部有）
- section → **类目** ❌ **缺**（船长全仓检索「章节名+类目名」同现 → **四个组合全为「无」**）

**⇒ 模型拿到的只有**：`group_type` 三选一（`keyElement|shot|audio`）+
草稿字段白名单 20 个（`label,tag,mediaType,genType,…,timbre,desc,id`）
——**没有一个字段承载 Skill 的章节语义**。

**⇒ 这就是"字段对应不上"的根因**：不是章节漏映射，
而是**章节语义止步于平台内部代号，没有落到模型可见的字段上**。

---

## 七、对方案的补充（并入批 4/5）

| 补丁 | 内容 | 层 | 影响面 |
|---|---|---|---|
| **P-1** | 补「章节 → 类目 → 字段」完整链，并把 `group_type`/字段描述与之一致 | 说明层+字段层 | **全部 16 skill 共享** |
| **P-2** | 补 lint：「能力面 ⊇ 委派面」集合比对（防再次漂移） | 门禁 | 全部 skill |
| **P-3** | 裁决 4 个"发不出去"的章节：①补进委派面；②显式登记"归主代理直调、不注入" | 需用户裁决 | 全部 16 skill（`<video_assembler>` 16/16 都用了） |
| **P-4** | `<audio_generate>` / `<video_assembler>` 属**无承载章节**：补承载（大工程）或显式登记缺失 | 需用户裁决 | 6 / 16 个 skill 用了 `audio_generate` |

> ⚠️ **注意影响面**：`<video_assembler>` **16/16 个 skill 全部使用**，
> `<audio_generate>` **6 个 skill 使用**——这两个"发不出去/无承载"的章节
> **不是个别 skill 的问题，是平台级缺口**。