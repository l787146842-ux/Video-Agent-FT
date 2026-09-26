# 审计报告 B — 分镜表格图草稿的 `refAssets` 为空 / `@[角色代号]` 未挂引用

- 工作目录：`E:\07 天问\自己做agent`（Windows / PowerShell）
- 性质：**只读审计**（未改动 `src/` 任何文件；本报告与若干只读探针脚本写在 `.tmp_probe/`）
- 审计对象：`AI-短剧一站式生成` Skill 的「分镜表格图（运镜轨迹示意图）」草稿
- 结论先行：**该问题不是单一 bug，而是"三段链路各自独立、且没有一段覆盖 image 类分镜草稿"的结构性缺口**：
  1. Skill 模板里的 `@[角色代号]` 是**占位符**，从未有代码做「占位符 → 真实关键元素名」的替换；
  2. `@[X]` 记号本身**能被解析器匹配**（批3 已修 R1 方括号），但 `X` 是占位符 ⇒ `media_map` 必然查不到 ⇒ 只去记号、不挂引用；
  3. **`shotRefs` 自动挂载只对"视频提示词"生效**——分镜表格图（image 草稿）走 `image_generate`/`resolve_shot_refs`，而 `resolve_shot_refs` 只取元素的 **`imgUrl`**，对「角色三视图 / 场景四视图」既不按 `audioType`/`genType` 过滤，也不区分 image 草稿种类，**但生成的图不会自动回填到该路径上**；真正缺失的是「谁把元素设定图 URL 写进 `refAssets`」这一步。

---

## A. 「草稿」的 `refAssets`：定义、白名单、工具 schema、丢弃行为

### A1. 后端 pydantic 定义

`src/video_agent/state/models.py:76`

```python
class DraftRecord(BaseModel):
    ...
    ref_assets: List[str] = Field(alias="refAssets", default_factory=list)
```

模型工厂的默认值同源（唯一建卡入口）：

`src/video_agent/state/models.py:334`

```python
DRAFT_DEFAULT_FIELDS = {
    ...
    "refAssets": [],
}
```

`src/video_agent/state/models.py:338-359` 的 `build_draft_dict()` 逐字段取默认值，并对 list 做拷贝（防止共享引用）：

```python
for field_name, default in DRAFT_DEFAULT_FIELDS.items():
    value = data.get(field_name)
    # refAssets 需要拷贝列表避免共享引用
    result[field_name] = value if value is not None else (list(default) if isinstance(default, list) else default)
```

> 注意：`build_draft_dict` 只从 `DRAFT_DEFAULT_FIELDS` 取字段 ⇒ **`refAssets` 是"建卡即存在、默认空数组"**；表里没写 ≠ 字段缺失，是**空数组**（这正是用户在 UI 上看到「没有引用」而不是"字段不存在"的原因）。

自定义 REST 端点（前端/外部用，不走工具白名单）也定义了该字段：

- `src/video_agent/web/routes/storyboard.py:31` — `DraftCreate.refAssets: List[str] = []`
- `src/video_agent/web/routes/storyboard.py:46` — `DraftPatch.refAssets: Optional[List[str]] = None`

### A2. 前端 TS 类型

- `src/web/types/index.ts:113` — `refAssets?: string[];`（`Draft` 接口，主类型）
- `src/web/types/api.generated.ts:279` — `DraftCreate.refAssets?: string[];`
- `src/web/types/api.generated.ts:294` — `DraftPatch.refAssets?: string[] | undefined;`

### A3. 白名单 `ALLOWED_DRAFT_FIELDS`

`src/video_agent/state/storyboard_ops.py:137-147`

```python
# draft patch 允许写入的字段全集（双轨统一，含 imageResolution / genType / desc）
ALLOWED_DRAFT_FIELDS = (
    "label", "tag", "mediaType", "genType", "imgUrl", "videoUrl", "audioUrl", "prompt", "mode",
    "model", "providerId", "resolution", "duration", "aspectRatio", "imageResolution",
    "size", "timbre", "refAssets", "desc",
    # 2026-09-23 批5：音频归属语义（voice=角色音色卡 / bgm / narration / …）
    "audioType",
)

# 新建草稿（storyboard_add_draft / storyboard_create_group 附带）允许的字段：
# = patch 白名单 + id（新建时可显式指定 ID；patch 通道改 id 无意义仍拒收）
ALLOWED_NEW_DRAFT_FIELDS = ALLOWED_DRAFT_FIELDS + ("id",)
```

**`refAssets` 在白名单内（第 140 行）**，即：字段本身**允许写**，问题不在白名单。

### A4. 模型工具入参 schema：`refAssets` 是否暴露？

`PatchDraftInput` / `AddDraftInput` **没有为 `refAssets` 建独立字段**，而是把它挂在**自由 `Dict` 里，再用白名单文案"告知"模型**：

`src/video_agent/tools/storyboard_tools.py:176-187`

```python
class PatchDraftInput(StrictToolInput):
    draft_id: str = Field(..., description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio")
    patch: Dict[str, Any] = Field(..., description="要更新的字段字典。" + _DRAFT_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class AddDraftInput(StrictToolInput):
    group_id: str = Field("current", description="目标分组 ID 或 'current'")
    group_type: str = Field("", description="分组类型")
    draft: Union[Dict[str, Any], str] = Field(..., description="新草稿数据（JSON 对象；字符串会自动解析一次）。" + _DRAFT_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")
```

字段名提示由白名单**动态拼接**（P1 单一事实源，防漂移）：

`src/video_agent/tools/storyboard_tools.py:34-36`

```python
_DRAFT_FIELDS_HINT = (
    f"合法字段（白名单外字段整单拒收）：{', '.join(ops.ALLOWED_NEW_DRAFT_FIELDS)}。"
    "卡片名用 label（不是 title）；提示词放 prompt；卡片描述放 desc。"
    ...
```

⇒ **答案：`refAssets` 在工具 schema 里是"可见但非结构化"的**——名字出现在 `patch`/`draft` 的 description 文本里（拼接自 `ALLOWED_NEW_DRAFT_FIELDS`），**没有类型校验、没有 `List[str]` 约束、没有"何时必须填"的正面契约**。对比同一文件里 `audioType`、`mediaType`、归属类目都写了长段正面契约（`storyboard_tools.py:37-70`），**`refAssets` 一句契约都没有**——模型没有任何提示"分镜表格图要挂角色三视图/场景四视图"。

### A5. `storyboard_patch_draft` 会把白名单外字段静默丢弃吗？

**不会静默——是"整单拒收"（fail-loud）。** 这是 2026-09-23 批 3·B5 之后的语义。

工具入口先做差集判定、命中即原子拒收：

`src/video_agent/tools/storyboard_tools.py:409-420`

```python
# T2 第一步「错误可见」：白名单外字段原子拒收（不写入任何字段，
# 避免部分写入后报错）；批 3 · B5 报错三要素 = 原因 + 状态保留
# 声明 + 缺什么才能继续。差集只引用 ALLOWED_DRAFT_FIELDS，不复制名单（P1）
dropped = ops.dropped_patch_fields(params.patch, ops.ALLOWED_DRAFT_FIELDS)
if dropped:
    return ToolResult(
        success=False,
        error=(f"Validation Error: patch 含白名单外字段: {', '.join(dropped)}。"
               "本次调用已拒收、未写入草稿，现有故事板与该卡片保持原样。"
               f"请只用合法字段（{', '.join(ops.ALLOWED_DRAFT_FIELDS)}）重新提交。"),
        error_code="validation", retryable=False,
    )
```

差集与就地写入的实现：

`src/video_agent/state/storyboard_ops.py:388-416`

```python
def dropped_patch_fields(patch: Dict[str, Any], allowed: Tuple[str, ...]) -> List[str]:
    """白名单差集：返回 patch 中不在允许集内的字段名（排序，确定性输出）。
    名单唯一事实源 = ALLOWED_DRAFT_FIELDS/ALLOWED_GROUP_FIELDS，只引用不复制（P1）。"""
    return sorted(set(patch or {}) - set(allowed))


def patch_draft(draft: Dict[str, Any], patch: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """按 ALLOWED_DRAFT_FIELDS 白名单就地更新 draft，返回 (是否有字段被修改, 被丢弃字段名列表)。
    被丢弃字段透出给调用方（T2 第一步「错误可见」），由调用方决定拒收/告警口径。
    ...
    """
    dropped = dropped_patch_fields(patch, ALLOWED_DRAFT_FIELDS)
    ...
    for field in ALLOWED_DRAFT_FIELDS:
        if field in patch:
            draft[field] = patch[field]
            changed = True
```

`storyboard_add_draft` 走同构路径、但用 `ALLOWED_NEW_DRAFT_FIELDS`：

`src/video_agent/tools/storyboard_tools.py:466-475`

```python
dropped = ops.dropped_patch_fields(draft_payload or {}, ops.ALLOWED_NEW_DRAFT_FIELDS)
if dropped:
    return ToolResult(
        success=False,
        error=(f"Validation Error: draft 含白名单外字段: {', '.join(dropped)}。"
               "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
               ...
```

> **关键推论（对本案重要）**：**唯一会"静默丢弃字段"的地方不是工具链，而是 REST 端点。**
> `src/video_agent/web/routes/storyboard.py:114-128`：
> ```python
> async def update_draft(draft_id: str, body: DraftPatch):
>     patch = body.model_dump(exclude_none=True)
>     ...
>     draft.update(patch)          # ← 直接 update，无白名单
> ```
> 该路径反而是"无白名单、任意字段可写"，但它**只接受 `DraftPatch` 里已声明的字段**（pydantic 默认忽略未知字段）——`refAssets` 在其中（第 46 行），所以前端能写、模型工具也能写，**没有一条路径把 refAssets "吃掉"**。
>
> ⇒ **`refAssets` 为空不是被丢弃造成的，而是从来没有人（模型或前端）往里写过值。**

---

## B. `@名称` / `@[名称]` 记号解析器（`src/video_agent/core/prompt_refs.py`）

### B1. 正则原文与行号

`src/video_agent/core/prompt_refs.py:35-38`

```python
_MENTION_RE = re.compile(
    r"<<<\s*image\\?_([^<>]+?)\s*>>>"
    r"|[@＠]\[?([^\s@＠\[\]]+)\]?"
)
```

紧邻的设计说明（第 23-34 行）明确指出批3 修的两条根因：

```python
# 2026-09-23 批3（Q4/Q6，用户裁决「引用记号必须能工作」）：修三条独立根因——
#   R1 方括号被吞：原排除类不含 [ ]，`@[程心]` 捕获出 `[程心]` → 查 map 必落空。
#       现将可选的 [ ] 包络排除在捕获组外（@[名] 与 @名 等价）。
#   R2 转义下划线：Skill 模板原文是 `<<<image\_场景>>>`（Markdown 转义，字符码 92
#      反斜杠），原正则要求裸 `image_` → 连匹配都不成立、整段原样进入生成请求。
#      现容许 `image` 与 `_` 之间存在可选反斜杠。
#   两条都不改变「未命中即去记号留文字」的既有语义。
```

前端镜像同一条正则（同契约）：

`src/web/lib/prompt-mentions.ts:35`

```ts
const MENTION_RE = /<<<\s*image\\?_([^<>]+?)\s*>>>|[@＠]\[?([^\s@＠[\]]+)\]?/g;
```

### B2. 能匹配哪些写法？`@[角色代号]` 会不会被匹配？

**会被匹配（含方括号整体吃进 `m.group(0)`，但捕获组只取括号内名字）。**

实测（只读探针 `.tmp_probe/_probe_b_refs.py`，输出 `.tmp_probe/_probe_b_refs_out.txt`）：

```
_MENTION_RE.pattern = '<<<\\s*image\\\\?_([^<>]+?)\\s*>>>|[@＠]\\[?([^\\s@＠\\[\\]]+)\\]?'

IN : 'Character sheet for @[角色代号] — replicate exactly'
  matches=['@[角色代号]']
IN : 'Character sheet for @角色代号 — replicate exactly'
  matches=['@角色代号']
IN : 'Location sheet for @[场景代号]'
  matches=['@[场景代号]']
IN : '<<<image_角色>>> and <<<image\\_场景>>>'
  matches=['<<<image_角色>>>', '<<<image\\_场景>>>']
IN : '@[Element_程心] 与 @程心 与 ＠AA'
  matches=['@[Element_程心]', '@程心', '＠AA']
IN : '@[甲 乙] 行内空格'
  matches=['@[甲']          ← 空格截断（名称不含空白，属设计内）
```

汇总：

| 写法 | 是否匹配 | 说明 |
|---|---|---|
| `@名称` | ✅ | 半角 `@` |
| `＠名称` | ✅ | 全角 `＠` |
| `@[名称]` | ✅ | **方括号整体被吃掉，捕获组只含名字**（批3 R1 修复点） |
| `＠[名称]` | ✅ | 同上 |
| `<<<image_名称>>>` | ✅ | 外部标杆 Skill 方言 |
| `<<<image\_名称>>>` | ✅ | 容许 `image` 与 `_` 间有反斜杠（批3 R2 修复点） |
| `@[甲 乙]`（名字含空格） | ⚠️ 部分 | 只匹配到 `@[甲` |

**⇒ 对 `@[角色代号]` 而言，正则不是问题。问题在名字是占位符。**

### B3. 解析把素材加进哪个列表？

**加进 `resolve_prompt_mentions` 返回的第二个值 `refs`（局部列表），它最终被上游当 `reference_images` 传给生成适配器——不是 `refAssets` 字段。**

`src/video_agent/core/prompt_refs.py:111-145`（全函数）

```python
def resolve_prompt_mentions(
    prompt: str,
    base_refs: List[str],
    media_map: Dict[str, Dict[str, str]],
    max_refs: int = 5,
) -> Tuple[str, List[str]]:
    """解析提示词中的 @提及，返回 (重写后的提示词, 最终参考素材 URL 列表)。

    - base_refs：草稿已有的参考素材（refAssets），保持原顺序；
    - @名称 命中的素材若不在 base_refs 且未满上限则自动追加；
    - @名称 重写为 [参考图N：名称]（N 为该素材在最终列表中的序号）；
      未命中 / 超限的 @名称 仅去掉 @ 前缀保留文字，避免模型困惑。
    """
    refs: List[str] = [u for u in (base_refs or []) if u][:max_refs]

    def index_of(url: str) -> int:
        return refs.index(url) if url in refs else -1

    def replace(m: re.Match) -> str:
        name = (m.group(1) or m.group(2) or "").strip()
        info = media_map.get(name)
        if not info:
            return name  # 未命中：去掉记号，保留文字        # ← 本案落点
        url = info["url"]
        idx = index_of(url)
        if idx < 0:
            if len(refs) >= max_refs:
                return name  # 超限：无法随请求发送，仅保留文字
            refs.append(url)
            idx = len(refs) - 1
        label = _KIND_LABEL.get(info.get("kind", "image"), "参考图")
        return f"[{label}{idx + 1}：{name}]"

    resolved = _MENTION_RE.sub(replace, prompt or "")
    return resolved, refs
```

**⚠️ 关键：第 133 行 `return name`——"未命中即去掉记号、保留文字"。既不改名、不告警、不报错。**
名字是占位符（`角色代号`）⇒ `media_map.get("角色代号")` 恒为 `None` ⇒ **静默降级**：提示词里剩下一段纯文字 `Character sheet for 角色代号 — replicate exactly`，参照图列表一张不加。**这就是用户观察到的问题的直接落点。**

名字映射表构建点（决定"哪些名字能命中"）：

`src/video_agent/core/prompt_refs.py:65-108`

```python
def build_storyboard_media_map(state: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """构建 名称 → {url, kind} 映射（与前端 PromptEditor 命名规则对齐）。

    命名来源（后写不覆盖先写，保证关键元素标题优先）：
    - 关键元素：分组 title（如 Element_月球）**及其剥前缀裸名**（月球）
    - 所有草稿：label
    - URL 文件名（兜底，与前端 refAssetName 的文件名规则一致）
    ...
    """
    media_map: Dict[str, Dict[str, str]] = {}
    def put(name, url, kind): ...
    for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
        for g in state.get(cat, []) or []:
            for d in g.get("drafts", []) or []:
                for field in ("imgUrl", "videoUrl", "audioUrl"):
                    url = d.get(field) or ""
                    if not url: continue
                    ...
                    if cat == CAT_KEY_ELEMENTS:
                        title = g.get("title", "")
                        put(title, url, kind)
                        bare = strip_type_prefix(title)      # R3：裸名别名
                        if bare != title: put(bare, url, kind)
                    put(d.get("label", ""), url, kind)
                    fname = Path(str(url).split("?")[0].split("#")[0]).name
                    put(fname, url, kind)
    return media_map
```

实测映射键（同一探针，输入含 `Element_程心` 组 + 一张三视图草稿）：

```
media_map keys = ['Element_程心', 'chengxin.png', '程心', '程心·三视图设定图']
PROMPT: 'Character sheet for @[角色代号] — replicate exactly\nLocation sheet for @[场景代号]'
  -> resolved='Character sheet for 角色代号 — replicate exactly\nLocation sheet for 场景代号'
  -> refs=[]                                    ← ★ 零引用
PROMPT: '参考 @程心 与 @[程心] 与 @[Element_程心]'
  -> resolved='参考 [参考图1：程心] 与 [参考图1：程心] 与 [参考图1：Element_程心]'
  -> refs=['http://x/chengxin.png']             ← 真名可用时正常命中
PROMPT: '<<<image_程心>>> 样式'
  -> resolved='[参考图1：程心] 样式'
  -> refs=['http://x/chengxin.png']
```

**⇒ 解析器本身工作正常；`@[角色代号]` 之所以"不挂图"，是因为 `角色代号` 不是一个存在于 `media_map` 里的真实名称。**
**Skill 模板 `data/skills/AI-短剧一站式生成/SKILL.md:207-210` 里写的就是字面占位符：**

```
Reference images attached:\

- Image 1: Character sheet for @\[角色代号\] — replicate exactly\
- Image 2: Location sheet for @\[场景代号\] — replicate exactly
```

（模板里连方括号都是 Markdown 转义的 `@\[角色代号\]`：`\` + `[`。落库时若被模型逐字照抄或经 `_unescape` 去掉反斜杠，就变成 `@[角色代号]`。）

### B4. 调用点（谁用了这个解析器）

**全仓只有 2 个 Python 调用点，且都在 `generation_submit.py`：**

| 调用点 | 行号 | 用途 |
|---|---|---|
| `submit_image_task` | `src/video_agent/web/generation_submit.py:65-68`（import）、`86-89`（调用） | 生图（Agent/工具链） |
| `submit_video_task` | `src/video_agent/web/generation_submit.py:320-323`（import）、`342-346`（调用） | 生视频（Agent/工具链） |

```python
# src/video_agent/web/generation_submit.py:86-89  （生图）
media_map = build_storyboard_media_map(state_dict)
eff_prompt, final_refs = resolve_prompt_mentions(
    draft.get("prompt", ""), base_ref_urls, media_map, max_refs=settings.image_ref_limit
)
```

```python
# src/video_agent/web/generation_submit.py:342-346  （生视频）
media_map = build_storyboard_media_map(state_dict)
eff_prompt, final_refs = resolve_prompt_mentions(
    draft.get("prompt", ""), base_ref_urls, media_map,
    max_refs=settings.video_ref_limit_total,
)
```

前端对应实现（手动点「生成」按钮走这条）：

- `src/web/lib/prompt-mentions.ts:146-172` — `resolvePromptForGeneration(prompt, baseRefs, maxRefs)`（`MENTION_RE` 见第 35 行）
- 调用点：`src/web/lib/generate-actions.ts:40`（生图，`IMAGE_GEN_LIMIT`）、`src/web/lib/generate-actions.ts:103`（生视频，`VIDEO_GEN_LIMITS.total`）

**⚠️ `web/routes/generate_image.py` 与 `web/multimodal_builder.py` 都不调用解析器。**

- `generate_image.py` 的**单张端点** `/generate/image`（第 37-136 行）**完全不做 @解析**：它只取 `body.reference_images` 里前端已解析好的 URL（`generate_image.py:72`）：

```python
# 提取参考素材 URL（@ 引用的素材），随请求发送给多模态模型
ref_urls = [r.get("url", "") for r in (body.reference_images or []) if r.get("url")]
```

  ⇒ **若草稿的 `refAssets` 为空且前端解析又未命中（占位符），该请求就是"零参考图"的纯文生图。**

- `multimodal_builder.py` 只用 `refAssets` 做 **LLM 上下文注入优先级**（不是生成参考图），见 `multimodal_builder.py:138-140`，且**只对"当前选中草稿"生效**（`_selected_draft_related_urls` 需要 `selected_draft_id`，第 127-128 行直接 `return []`）。

---

## C. 生成图片时参考素材是怎么收集的（来源优先级 + 各自生效条件）

`src/video_agent/web/generation_submit.py:80-89`（**唯一的生图参考汇总点**）

```python
# --- 解析 @引用：重写提示词 + 汇总参考图（草稿自身 refAssets 优先，shotRefs 其次）---
base_ref_urls: List[str] = [u for u in (draft.get("refAssets") or []) if u]
for r in refs:
    u = r.get("url") if isinstance(r, dict) else ""
    if u and u not in base_ref_urls:
        base_ref_urls.append(u)
media_map = build_storyboard_media_map(state_dict)
eff_prompt, final_refs = resolve_prompt_mentions(
    draft.get("prompt", ""), base_ref_urls, media_map, max_refs=settings.image_ref_limit
)
```

`final_refs` 最终作为 `reference_images` 送给适配器：

```python
# src/video_agent/web/generation_submit.py:134-138
url = await _gen_image_throttled(
    pid, mdl, eff_prompt,
    size=size, aspect_ratio=aspect_ratio, resolution=resolution,
    reference_images=final_refs,
)
```

### 四源优先级与生效条件

| # | 来源 | 代码位置 | 生效条件 |
|---|---|---|---|
| 1 | **草稿自身 `refAssets`** | `generation_submit.py:81` | **无条件**，只要非空即排在列表最前 |
| 2 | **调用方显式传入 `refs`（即 shotRefs 解析结果）** | `generation_submit.py:82-85` | 由调用方的 `refs` 参数决定；`submit_image_task` 本身不解析 shotRefs |
| 3 | **提示词 `@引用` 解析** | `generation_submit.py:86-89` | 仅当 `media_map` 里**存在同名条目**（真名/裸名/文件名）时命中；未命中静默去记号 |
| 4 | **元素 image 列表**（`resolve_shot_refs`） | `storyboard_ops.py:559-585` | 仅当**传入的 `group` 非空 且 `group["shotRefs"]` 非空**，且被引用的关键元素组内**有草稿带 `imgUrl`** |

### C1. 判定代码位置：`shotRefs` 自动挂载是否只对「视频提示词」草稿生效？

**是。它只按 `group` 生效，不按草稿种类生效——但"哪个工具/端点会去调它"决定了实际覆盖面：**

**(a) 生图工具 `image_generate`（batch）** —— `src/video_agent/tools/document_tools.py:887-900`

```python
for group, draft, dtype in targets:
    refs = ops.resolve_shot_refs(state, group) if group else []
    eff_resolution = (...)
    draft["imageResolution"] = eff_resolution  # 参数栏同步可见
    task_id = submit_image_task(
        state, draft, provider_id, model, refs,
        aspect_ratio=(draft.get("aspectRatio") or "16:9"),
        resolution=eff_resolution,
        on_failure_save=svc.save_debounced,
        draft_type=dtype,
    )
```

**(b) `resolve_shot_refs` 本身** —— `src/video_agent/state/storyboard_ops.py:559-585`

```python
def resolve_shot_refs(
    state: Dict[str, Any], group: Optional[Dict[str, Any]], limit: int = 5,
) -> List[Dict[str, str]]:
    """解析分镜的 shotRefs → 对应关键元素的概念图 URL 作为参考图（默认最多 5 张）。
    ...
    """
    refs: List[Dict[str, str]] = []
    if not group:
        return refs
    shot_refs = group.get("shotRefs") or []
    if not shot_refs:
        return refs
    for ref_title in shot_refs:
        if not isinstance(ref_title, str):
            continue
        ke_group = find_ref_group(state, ref_title)
        if ke_group is None:
            continue
        for d in ke_group.get("drafts", []):
            img = d.get("imgUrl") or ""      # ← ★ 只取 imgUrl，无 genType/audioType 过滤
            if img:
                refs.append({"url": img, "role": "reference"})
                break                        # ← ★ 每个元素组只取"第一张有图"的卡
    return refs[:limit]
```

**(c) 批量生图端点 `/generate/batch-image`** —— `src/video_agent/web/routes/generate_image.py:186-198`（一份独立抄写）

```python
# 自动注入 shotRefs 参考图
# 2026-09-23 批10（事故 4444/P0-A）：比对改走 ops.find_ref_group 唯一入口。
# 旧实现逐字比对 ke.title == ref_title，而落盘标题带前缀（Element_程心）、
# shotRefs 存裸名（程心）⇒ 恒不命中（同一失配在本文件的第二份抄写）。
refs: List[Dict[str, str]] = []
for ref_title in (group.get("shotRefs") or []):
    ke = ops.find_ref_group(state, ref_title)
    if ke is None:
        continue
    for kd in ke.get("drafts", []):
        if kd.get("imgUrl"):
            refs.append({"url": kd["imgUrl"], "role": "reference"})
            break
```

**(d) 视频专有路径（对照组：这里才有"分镜自动挂接"）** —— `src/video_agent/web/routes/generate_video.py:85-103` + `generation_submit.py:260-288`

```python
def collect_shot_video_refs(
    state_dict: Dict[str, Any],
    group: Optional[Dict[str, Any]],
    draft: Dict[str, Any],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """自动收集分镜视频生成的参考素材：
    1. shotRefs 引用的关键元素概念图（多参考图，role=reference）；
    2. 草稿 refAssets / audioUrl 中的音色参考音频（role=reference_audio）；
    3. 批 6 · A3：shotRefs 引用元素的 audioUrl（元素自带音色锚点，
       外部标杆「按引用自动挂声音锚点」形态）同轴自动挂为 reference_audio。
    ...
    """
    image_refs: List[Dict[str, str]] = ops.resolve_shot_refs(
        state_dict, group, limit=settings.video_ref_limit_image
    )
    ...
```

### C2. 对本案（分镜表格图 image 草稿）逐条判定

用真实落库数据（`.tmp_probe/projects/proj-1790255904-2e5508d2.json` 与 `workspace/state.sqlite3` 只读导出，见 `.tmp_probe/_probe_b_sqlite_out.txt`）：

```
group='Shot_程心与AA在星环号舱室苏醒，窗外木星云带旋转'
  shotRefs=['Element_星环号球形舱', 'Element_程心', 'Element_AA']
draft id=draft-1790258630-0c36e457 label='Shot1·分镜表格图' mediaType=image genType=''
imgUrl=''
refAssets=[]
prompt 尾部：
【Reference images attached】Character sheet（程心、AA）；Location sheet（星环号球形舱）；
replicate exactly——缩略图中人物造型与舱室结构严格复刻设定图。
```

14 个分镜组 × 2 张草稿（视频 + 表格图），**全部 28 张草稿 `refAssets` 均为 `[]`**（同上探针输出）。

| 来源 | 该草稿的实际判定 |
|---|---|
| ① 草稿 `refAssets` | **空数组** ⇒ 贡献 0 |
| ② 显式 `refs`（`resolve_shot_refs`） | **会生效**——`group.shotRefs` 非空、`find_ref_group` 按 canonical 命中，但取的是元素组的 `imgUrl`。本案中**所有关键元素草稿 `imgUrl` 全部为空**（这批数据里设定图尚未生成/未回写），⇒ 贡献 0；且该函数**只取每元素"第一张有 imgUrl 的卡"**，无法区分"三视图设定图"与其它 image 卡 |
| ③ 提示词 `@引用` 解析 | **不命中**——这批 prompt 里写的是**中文全角括号 + 无 @**：`Character sheet（程心、AA）`（见上），正则只认 `@`/`＠`/`<<<image_...>>>` ⇒ 0 个 token ⇒ 贡献 0。**若换成 Skill 模板原文的 `@[角色代号]`，同样 0 命中**（名字是占位符，见 B3 实测） |
| ④ 元素 image 列表 | 与 ② 同一条路径，无独立实现 |

**⇒ 结论：分镜表格图草稿在四条来源上全部落空。用户报的"refAssets 为空所以图块没被引用"是准确的现象描述；根因不只是 `refAssets` 空，而是"没有任何一条链路负责给 image 类分镜草稿自动挂设定图"。**

**并且：`shotRefs` 自动挂载在语义上"是给视频提示词设计的"。** 证据链：

- `shotRefs` 的写口契约就写着"分镜视频"用途：`src/video_agent/web/skill_docs.py:226`
  ```
  6. 用户说"生成关键帧" → image_generate(target="all_shots")，自动注入 shotRefs 参考图
  ```
- `storyboard_tools.py:76-80` 的 `_GROUP_FIELDS_HINT` 明确 `shotRefs` 是 `shot` 组的字段——**它挂在组上，不区分组内草稿是 video 还是 image**；`resolve_shot_refs` 因此**对 image 草稿"技术上会生效"，但仅覆盖 `imgUrl` 且无种类过滤**。
- 真正区分草稿种类的分支只存在于**写回标签/参数**这类旁路（如 `document_tools.py:836` 的 `targets.append((group, draft, "shot" if cat == CAT_SHOTS else "keyElement"))`），**不在参考素材收集上**。

**⇒ 准确答案：不是"shotRefs 只对视频提示词生效"的显式判定，而是"没有任何判定"**——`resolve_shot_refs` 对分镜组内**所有**草稿一视同仁地返回同一份 `imgUrl` 列表；表格图草稿能拿到的是"元素概念图"，而它需要的"角色三视图/场景四视图"在数据上就是同一批 `imgUrl`（若已生成）——**但一旦元素组内的第一张有图卡是音色卡或别的卡，`break` 就取错图**。

---

## D. 关键元素设定图的图片 URL 存在哪里？生成分镜表格图时谁把「三视图/四视图」挂为参考图？

### D1. URL 字段：**`imgUrl`**（不是 `mediaUrl`）

**全仓没有 `mediaUrl` 字段。** 设定图 URL 落在草稿的 `imgUrl`：

- 后端模型：`src/video_agent/state/models.py:73` — `img_url: str = Field(alias="imgUrl", default="")`
- 前端类型：`src/web/types/index.ts:114` — `imgUrl?: string;`
- 字段取值唯一入口：`src/video_agent/core/prompt_refs.py:43-62` 的 `media_of_draft()`
  ```python
  def media_of_draft(d: Dict[str, Any]) -> Tuple[str, str]:
      """取草稿的主媒体 (url, kind)：按 mediaType 优先，其次按已有字段兜底。..."""
      kind = infer_media_type(d)
      if kind == "video":
          url = d.get("videoUrl") or d.get("imgUrl") or ""
          return url, "video"
      if kind == "audio":
          url = d.get("audioUrl") or ""
          return (url, "audio") if url else ("", "image")
      url = d.get("imgUrl") or d.get("videoUrl") or d.get("audioUrl") or ""
      ...
  ```
- 真实落库数据佐证（`.tmp_probe/projects/proj-1790255904-2e5508d2.json`）：
  ```
  KE group=Element_程心   | label=程心·三视图设定图     | mediaType=image | imgUrl=
  KE group=Element_星环号球形舱 | label=星环号球形舱·四视图设定图 | mediaType=image | imgUrl=
  KE group=Element_白色薄片 | label=白色薄片·道具参考图    | mediaType=image | imgUrl=
  ```
  （该批次 imgUrl 为空是因为设定图尚未生成；字段本身是 `imgUrl`。）

### D2. 生成分镜表格图时，系统如何把角色三视图/场景四视图挂为参考图？

**唯一存在的自动路径 = `shotRefs` → `resolve_shot_refs` → 元素组里第一张有 `imgUrl` 的卡 → `role="reference"`。**

- `src/video_agent/state/storyboard_ops.py:559-585`（见 C 节引用）
- `src/video_agent/tools/document_tools.py:888` → `submit_image_task(..., refs, ...)`
- `src/video_agent/web/routes/generate_image.py:191-198`（批量端点独立抄写）

**⇒ 这条路径存在，但它是"按元素取第一张有图的卡"，没有"三视图/四视图"这一级语义。**

**"按卡种类取三视图/四视图"的路径：不存在。** 明确说：**无此路径。** 证据：

1. **`resolve_shot_refs` 无任何卡种类判据**——不读 `label`、不读 `genType`、不读 `audioType`（`storyboard_ops.py:571-584` 全文只有 `imgUrl` 判空与 `break`）。
2. **`genType` 在白名单里但从不参与参考收集**——`ALLOWED_DRAFT_FIELDS` 含 `"genType"`（`storyboard_ops.py:138`），全仓引用只出现在写回/展示路径。
3. **Skill 契约要求的"同时上传该 shot 涉及的角色三视图和场景四视图作为 reference_image"没有任何代码承接**：
   `data/skills/AI-短剧一站式生成/SKILL.md:129`
   ```
   - 使用 **ImageToImage**，模型与分辨率按全局设置的默认渠道填写；同时上传该 shot 涉及的角色三视图和场景四视图作为 reference_image，确保画风/角色/场景一致。
   ```
   全仓 grep `ImageToImage` / `image_to_image` / `img2img` = **0 命中**（`src/` 内）——**Skill 说的 `ImageToImage` 通道在代码里没有专门实现，只能靠"有参考图就走多模态"这一通用行为近似。**
4. **占位符替换路径也不存在**——没有代码把 `@[角色代号]` 里占位符替换成 `shotRefs` 指向的真实元素名。全仓 grep `Character sheet` 只命中 Skill 模板与历史会话日志，**无任何生成期替换逻辑**。

**⇒ 结论：`@[角色代号]` / `@[场景代号]` 是**没人实现的占位符**；分镜表格图的参考图只能靠 `shotRefs` 的 `imgUrl` 兜底，而该兜底（a）要求元素卡已有图，（b）不区分设定图/音色卡/道具卡，（c）每元素只取第一张。**

---

## E. 前端：`refAssets` 在 UI 上如何显示与编辑？空时会显示「无引用」吗？

### E1. 组件：`RefAssetBar`

`src/web/components/middle-panel/RefAssetBar.tsx`（237 行，参考素材横条）

- 组件签名：`RefAssetBar.tsx:20-27`
  ```tsx
  export function RefAssetBar(props: {
    /** 当前选中草稿记录 */
    rec: () => DraftRecord | undefined;
    /** 当前草稿参考素材 URL 列表 */
    refAssets: () => string[];
    /** 参考素材上限（shot=2 / 其他=5） */
    maxRefs: () => number;
  }) {
  ```
- 挂载点：`src/web/components/middle-panel/PromptEditor.tsx:146-149`
  ```tsx
  {/* 参考素材横条（音频草稿无参考素材概念，不显示） */}
  <Show when={state.selectedType !== 'audio'}>
    <RefAssetBar rec={rec} refAssets={refAssets} maxRefs={maxRefs} />
  </Show>
  ```
  `refAssets` 取值：`PromptEditor.tsx:60` — `const refAssets = () => draft()?.refAssets || [];`

### E2. 编辑方式

| 操作 | 代码 |
|---|---|
| 添加（+ 菜单 / 弹窗选取） | `RefAssetBar.tsx:68-88` → `studioActions.updateDraftLocal(r.type, r.draft.id, { refAssets: [...refs, url] })`（第 80 行） |
| 删除（缩略图 ✕） | `RefAssetBar.tsx:95-101`（第 99 行 `refAssets: (r.draft.refAssets \|\| []).filter((u) => u !== url)`） |
| 本地上传 | `src/web/lib/ref-upload.ts:16-29`（第 29 行同样写 `refAssets`） |
| 拖拽上传 | `RefAssetBar.tsx:103-107` |
| 分镜只读绑定 chips | `RefAssetBar.tsx:119-130`（`boundAssetTitle`，只有 `selectedType === 'shot'` 时渲染） |

**⚠️ 上限 ≠ ∞ 的坑**：`showToast` 里写的是「参考素材最多 N 个」，但 `PromptEditor.tsx:62` 给出 `shot` 类型 `Infinity`：

```tsx
/** 参考素材上限：keyElement≤5；shot 不设上限（用户决策） */
const maxRefs = () => (state.selectedType === 'shot' ? Infinity : 5);
```

**分镜表格图草稿的 `selectedType === 'shot'` ⇒ 无上限，用户可以手动加任意多张参考图。**

### E3. 空时会显示「无引用」吗？

**不会。空 `refAssets` 时该区域只剩三样东西，没有任何"无引用/暂无参考"提示：**

1. `<For each={props.refAssets()}>`（`RefAssetBar.tsx:133`）空循环 ⇒ 不渲染缩略图；
2. `<Show when={props.refAssets().length < props.maxRefs()}>`（第 169 行）⇒ 恒显示「+」按钮；
3. 固定文案（第 213-216 行）：
   ```tsx
   <div class="ref-drop-hint">
     <FiImage size={16} />
     <span>拖拽/上传素材，或点 + 从画布选取（提示词中按 @ 引用关键元素/分镜/音频素材）</span>
   </div>
   ```

**但右侧计数徽章不是 0**——它会额外统计提示词里 `@` 命中的故事板素材（**这份统计不写回 `refAssets`，只影响显示**）：

`RefAssetBar.tsx:43-65`

```tsx
/** 右侧计数：参考栏素材 + 提示词中 @ 引用的故事板素材（URL 去重，按类型统计） */
const refCounts = createMemo(() => {
  const counts: Record<'image' | 'video' | 'audio', number> = { image: 0, video: 0, audio: 0 };
  const seen = new Set<string>();
  for (const url of props.refAssets()) {
    counts[refAssetType(url, state.keyElements)] += 1;
    seen.add(url);
  }
  const prompt = props.rec()?.draft.prompt || '';
  if (prompt.includes('@') || prompt.includes('＠')) {
    const map = storyboardMediaMap();
    const re = /[@＠]([^\s@＠]+)/g;          // ← ★ 与后端 _MENTION_RE 不同：不认 <<<...>>>，也不剥 [ ]
    let m: RegExpExecArray | null;
    while ((m = re.exec(prompt))) {
      const info = map[m[1]];
      if (!info || seen.has(info.url)) continue;
      seen.add(info.url);
      counts[info.kind] += 1;
    }
  }
  return counts;
});
```

> **⚠️ 前端计数徽章的独立缺陷（与本案直接相关）**：第 54 行的 `/[@＠]([^\s@＠]+)/g` **没有方括号容忍**，`@[程心]` 捕获出的是 `[程心]`（含方括号）⇒ `map['[程心]']` 未命中 ⇒ 计数少算。这与 B 节后端正则（已修 R1）**是同一处口径漂移的"第三份抄写"**，2026-09-23 批3 修了后端 `prompt_refs.py` 与前端 `prompt-mentions.ts`，**漏改了 `RefAssetBar.tsx:54`。**

**⇒ 对本案的意义：即便用户把提示词写成 `@[程心]`，右侧计数徽章也不会把它算进去（显示 0），进一步强化了"图块没有被引用"的观感。**

编辑器内部的 chip 渲染走另一条路径（`renderPromptToDOM`，`src/web/lib/prompt-ref-utils.ts:130-157`，其正则第 144-147 行**容忍方括号**，与后端对齐）——**所以提示词框里 `@[程心]` 能渲染成图块 chip，但右侧计数是 0**，两处不一致。

---

## 结论摘要（可直接引用）

**A. `refAssets` 定义与白名单 —— 字段可写，但模型没有正面契约**
- 后端 `src/video_agent/state/models.py:76` `ref_assets: List[str] = Field(alias="refAssets", default_factory=list)`；默认空数组见同文件 `:334`（`build_draft_dict` 建卡即写空数组）。
- 前端 `src/web/types/index.ts:113`；REST 端点 `src/video_agent/web/routes/storyboard.py:31/46`。
- 白名单 `src/video_agent/state/storyboard_ops.py:137-143`，**`refAssets` 在内（第 140 行）**；`ALLOWED_NEW_DRAFT_FIELDS` 见 `:147`。
- 工具 schema 里 `refAssets` **没有独立字段**，只作为 `patch: Dict[str, Any]` / `draft: Union[Dict, str]` 的自由键（`src/video_agent/tools/storyboard_tools.py:176-187`），靠 description 拼接白名单名（`:34-36`）——**没有任何"分镜表格图要挂角色三视图/场景四视图"的正面契约**（对比 `audioType` 有长段契约 `:37-70`）。
- **不静默丢弃**：白名单外字段**整单拒收**（`storyboard_tools.py:412-420` 与 `:466-475`），差集实现 `storyboard_ops.py:388-391`，就地写入 `:394-416`。真正"无白名单"的路径是 REST `PATCH /storyboard/drafts/{id}`（`routes/storyboard.py:114-128` 直接 `draft.update(patch)`），但它也含 `refAssets`——**没有一条链路把该字段吃掉，它就是从来没人写过。**

**B. `@` 记号解析器 —— 正则没问题，名字是占位符才是病灶**
- 正则 `src/video_agent/core/prompt_refs.py:35-38`：`r"<<<\s*image\\?_([^<>]+?)\s*>>>" r"|[@＠]\[?([^\s@＠\[\]]+)\]?"`（前端镜像 `src/web/lib/prompt-mentions.ts:35`）。
- **`@[角色代号]` 会被匹配**（批3 R1 已修方括号吞噬；实测 `.tmp_probe/_probe_b_refs_out.txt`：`matches=['@[角色代号]']`）；`<<<image\_场景>>>` 也匹配（R2 转义下划线）。
- 解析结果进**函数返回值 `refs`**（最终当 `reference_images` 传给适配器），**不回写 `refAssets`**：`prompt_refs.py:111-145`。**未命中时第 133 行 `return name` 静默去记号留文字**——`角色代号` 不在 `media_map`（`build_storyboard_media_map` `:65-108`，键实测为 `['Element_程心','chengxin.png','程心','程心·三视图设定图']`）⇒ `refs=[]`。
- 调用点**全仓仅 2 处**：`src/video_agent/web/generation_submit.py:86-89`（生图）与 `:342-346`（生视频）；`generate_image.py` 与 `multimodal_builder.py` **都不调用**（前者只吃前端已解析的 `body.reference_images`，`generate_image.py:72`）。
- Skill 模板 `data/skills/AI-短剧一站式生成/SKILL.md:207-210` 写的就是字面占位符 `@\[角色代号\]` / `@\[场景代号\]`，**全仓无占位符替换逻辑**。

**C. 生图参考素材收集 —— 四源对表格图草稿全部落空**
- 汇总唯一入口 `src/video_agent/web/generation_submit.py:80-89`：①`refAssets`（`:81`，无条件）→ ②调用方 `refs`（`:82-85`）→ ③`@引用` 解析（`:86-89`，需 `media_map` 命中）；`final_refs` 送 `reference_images`（`:134-138`）。
- ④ 元素 image 列表 = `ops.resolve_shot_refs`（`state/storyboard_ops.py:559-585`）：**只取 `imgUrl`、每个元素组 `break` 取第一张有图的卡、无任何种类过滤**。生图侧调用点：`tools/document_tools.py:888`；批量端点独立抄写 `web/routes/generate_image.py:191-198`。
- **`shotRefs` 自动挂载不是"只对视频提示词生效"的显式判定，而是根本没有种类判定**——`shotRefs` 是**组级**字段（`storyboard_ops.py:154` 白名单），`resolve_shot_refs` 对组内所有草稿返回同一份列表；真正区分草稿种类的分支只在写回标签处（`document_tools.py:836`）。对照视频专有路径 `generation_submit.py:260-288` + `routes/generate_video.py:85-103`——**"分镜自动挂接"这个名字只出现在视频链上**。
- 实测（`.tmp_probe/_probe_b_sqlite_out.txt`）：14 个分镜组 × 2 草稿，**28 张草稿 `refAssets` 全为 `[]`**，所有关键元素 `imgUrl` 亦为空 ⇒ 四条来源全部贡献 0。

**D. 关键元素设定图 URL 字段与"挂三视图/四视图"路径**
- 字段是 **`imgUrl`**（**不是 `mediaUrl`**，全仓无 `mediaUrl`）：`src/video_agent/state/models.py:73`、`src/web/types/index.ts:114`；读取统一入口 `src/video_agent/core/prompt_refs.py:43-62`。
- **"按卡种类取三视图/四视图"这条路径：无此路径。** 唯一存在的自动路径是 `shotRefs` → `resolve_shot_refs` → 元素组第一张有 `imgUrl` 的卡（`storyboard_ops.py:577-584`），无 `label`/`genType`/`audioType` 判据。
- Skill 要求「同时上传该 shot 涉及的角色三视图和场景四视图作为 reference_image」（`data/skills/AI-短剧一站式生成/SKILL.md:129`）**无代码承接**：`src/` 内 grep `ImageToImage`/`image_to_image`/`img2img` **0 命中**；`@[角色代号]` → 真实名的替换逻辑**不存在**。

**E. 前端显示与编辑 —— 空时不显示「无引用」，且计数徽章有独立口径漂移**
- 组件 `src/web/components/middle-panel/RefAssetBar.tsx`（增删见 `:68-101`；挂载 `src/web/components/middle-panel/PromptEditor.tsx:146-149`）。
- **空 `refAssets` 时不显示「无引用」**：`<For>`（`:133`）空循环 + `<Show>` 恒显「+」按钮（`:169`）+ 固定提示文案（`:213-216`）。
- **独立缺陷**：右侧计数徽章 `RefAssetBar.tsx:43-65` 用 `/[@＠]([^\s@＠]+)/g`（第 54 行）**不剥方括号** ⇒ `@[程心]` 计为未命中、显示 0；与后端 `prompt_refs.py:35-38`、前端 `prompt-mentions.ts:35`（2026-09-23 批3 已修 R1）**口径不一致，属漏改的第三份抄写**。
- 分镜类型上限为 `Infinity`（`PromptEditor.tsx:62`），但 `RefAssetBar.tsx:76-78` 的 toast 文案仍写「最多 N 个」。

---

## 附：本次审计的只读探针与证据文件（均在 `.tmp_probe/`，未触碰 `src/`）

| 文件 | 用途 |
|---|---|
| `.tmp_probe/_probe_b_refs.py` | 只读调用 `prompt_refs._MENTION_RE` / `resolve_prompt_mentions`，验证 `@[名]` 匹配与未命中降级 |
| `.tmp_probe/_probe_b_refs_out.txt` | 上者的 UTF-8 输出（正则、matches、media_map 键、resolved/refs） |
| `.tmp_probe/_probe_b_sqlite.py` / `_probe_b_sqlite2.py` / `_probe_b_sqlite3.py` | 只读打开 `workspace/state.sqlite3`（`mode=ro`）定位带 `Character sheet` / `@[` 的草稿 |
| `.tmp_probe/_probe_b_sqlite_out.txt` | 上者输出：分镜组 `shotRefs`、表格图草稿 `mediaType=image` / `imgUrl=''` / `refAssets=[]`、prompt 尾部 |
| `.tmp_probe/projects/proj-1790255904-2e5508d2.json` | 现存项目快照（14 KE / 14 shot / 3 audio），用于核对全量 `refAssets` 与 `imgUrl` 为空 |
