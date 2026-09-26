# 审计报告 A：分镜 `shotRefs` 组装链 & 分镜表格图 `refAssets` 为空

- 审计人：Python 代码审计员（**只读分析**，未修改 `src/` 下任何文件；仅新建本报告）
- 工作目录：`E:\07 天问\自己做agent`（Windows / PowerShell）
- 审计对象：`storyboard_create_group` → `shotRefs` 三源合并 → 落库 → 读口消费；`@[角色代号]` 提示词引用解析链
- 证据分级（全文沿用）：
  - **[代码]** 源码行号 + 片段（工作区当前基线）
  - **[复算]** 对真实落库 state 调**生产函数**只读复算（未写任何文件、未改 state）
  - **[探针]** 独立只读探针（`python -` 管道，进程退出即销毁）
  - **[数据]** 只读 sqlite（`mode=ro`）/ 会话 jsonl
- 现场数据：
  - `workspace/state.sqlite3` → `proj-1790358500-25465d26`（工作台 **9999**，当前活跃项目，模型记录里的现场）
  - `workspace/state.sqlite3` → `proj-1790326837-3c760e66`（**8888**）、`proj-1790255904-2e5508d2`（6666）、`proj-1790159421-bfd25491`（4444，仅在引用历史注记时出现）
  - `workspace/sessions/proj-1790358500-25465d26/*.jsonl`（模型原始 tool_call 记录）
  - `.tmp_probe/8888_state.json`
- 不可读项：`pt_run2\` 在本会话沙箱内被拒绝（access denied），未纳入比对；经 grep 确认其为 `data\skills\` 镜像，引用统一走可读的 `data\skills\`。

> **基线声明（可复现性）**：工作区 `git status` 显示 `src/` 下已有一批**审计开始前就存在**的未提交改动（`storyboard_ops.py` 等，最后写入时间 2026-09-25 19:58 与 2026-09-26 01:0x）。本报告的代码行号基线 = **当前工作区文件**（不是 `HEAD`）。审计期间本人**未修改任何 `src/` 文件**（只读探针均为独立 `python -` 进程；唯一写入物 = 本报告）。若后续有人把工作区改动提交/回滚，行号可能漂移。

---

## 0. 结论速览

| # | 问题 | 确定性结论（一句话） |
|---|---|---|
| **A** | `shotRefs` 组装链 | 三源齐全：显式 `shot_refs` ∪ `[令牌]` 匹配 ∪ 裸名提及，落库前经 `merge_shot_refs`→`canonicalize_shot_refs` 归一为**元素组全称**；但三源合并**只在建组期跑一次**，`patch_group` 明确**不重跑**。 |
| **B** | 匹配规则 | 令牌正则 `\[([^\[\]]{1,60})\]`；令牌匹配=**精确→双向包含**（不剥前缀、无大小写/全半角归一）；裸名提及=**候选串逐字子串包含**，候选仅两种形态（完整标题 / `strip_type_prefix` 后的整串），**没有任何"短名/别名"形态**；合并顺序=显式→令牌→裸名，去重键=`strip_type_prefix`。 |
| **C** | 回喂 | 有，但**只覆盖 `[...]` 令牌**（`storyboard_tools.py:387-393`）；**裸名路径没有"未命中"概念，静默**。 |
| **D** | 中文名 vs `Element_艾AA（AA）` | 令牌 `[艾AA]` → **命中**（靠双向包含）；裸名 `艾AA` → **不命中**（候选只有 `Element_艾AA（AA）`/`艾AA（AA）`）；`艾AA（AA）` 全称 → **命中**。别名短名 `艾AA` 在**任何**路径（写口 3 源 + 前端渲染候选）都不是候选串。 |
| **E** | 态快照 / 后建元素 | 用 `svc.state_dict` 的**创建时刻**快照（`append` 之前）；元素后建**不会**回填；全仓 `merge_shot_refs` 仅 2 处调用，**无 backfill 通道**。 |
| **F** | 问题 2 | `@` 引用**从不写 `refAssets`**（前端刻意不写，后端只在生成提交时解析）→ `refAssets=[]` 属**预期**；真正问题是 `@[角色代号]`/`@[场景代号]` 这类 **Skill 占位符永远解析不到素材**（键里没有），且未命中时**静默去掉 `@` 留文字**。 |

**问题 1 的确定根因（含两条同时成立的缺陷）**

- **缺陷 ①（现场实证，直接对应用户描述）**：`shotRefs` 里**其实挂着** `Element_艾AA（AA）`，但 desc 里写的是**短名** `艾AA`；前端内联图块候选 `descChipNames`（`src/web/lib/desc-ref-utils.ts:119-132`）只产 `Element_艾AA（AA）`/`艾AA（AA）`，`renderDescToDOM` 按候选串逐字匹配（`:157`）→ **desc 里的 `艾AA` 永远渲染不出图块**。9999 实测：shot1/2/3 的 `艾AA`、shot2/3 的 `曹彬` 共 5 处全部属此类（§D.5）。
- **缺陷 ②（机制确定，现场暂无留痕的"地雷"）**：若模型**没**手抄全称进显式 `shot_refs`（而工具文档恰恰鼓励留空交给系统解析，`storyboard_tools.py:150`），desc 里的短名 `艾AA` 会让**三源全部落空** → `shotRefs` 真缺引用，且**零告警**（同 desc 里 `[全息信息窗]` 这类令牌则会触发告警，形成"同一条 desc 里两种命运"）。
- 两条共同的上游根因 = **候选形态缺"别名短名"这一级**：写口 `scan_bare_name_mentions`（`storyboard_ops.py:674-678`）与前端 `descChipNames`（`desc-ref-utils.ts:127-129`）**同一处缺口、同构镜像**。

---

## A. `storyboard_create_group` 如何组装 shot 的 `shotRefs`

### A.1 唯一落库点 [代码]

`src/video_agent/tools/storyboard_tools.py:337-379`：

```python
337:        _desc = _unescape_desc(params.desc)
338:        new_group: Dict[str, Any] = {"id": new_id, "title": _title, "desc": _desc, "drafts": []}
...
349:        if cat_key == CAT_SHOTS:
354:            new_group["duration"] = (
355:                params.duration or _derive_duration_from_summary(params.summary) or "5s")
358:            new_group["summary"] = str(params.summary or "").strip()
...
372:            _tokens = ops.parse_element_tokens(_desc or "")
373:            _, unmatched_tokens = ops.match_element_titles_report(
374:                svc.state_dict, _tokens)
375:            new_group["shotRefs"] = ops.merge_shot_refs(
376:                svc.state_dict, _desc or "", params.shot_refs)
377:
378:        async with svc.lock:
379:            svc.state_dict.setdefault(cat_key, []).append(new_group)
```

- 解析与落库共用**同一份归一后的 desc** `_desc`（`storyboard_tools.py:370-371` 注释：防「存的」与「解析的」两份事实源）。
- 合并发生在**写入之前**（`append` 在 `:379`）。
- `shotRefs` **不经过** `normalize_group_title`（那只用于 `title`，`:331-332`）；`shotRefs` 只经 `merge_shot_refs`。

### A.2 三源分别在哪里实现 [代码]

| 源 | 实现 | 位置 |
|---|---|---|
| ① 显式 `shot_refs` | schema 声明 + 合并时清洗 | `storyboard_tools.py:150`；`storyboard_ops.py:754` |
| ② `[元素名]` 令牌 | 提取 + 匹配 | `storyboard_ops.py:629-650`（`parse_element_tokens`）、`765-791`（`match_element_titles_report`） |
| ③ 裸名提及 | 扫描 | `storyboard_ops.py:653-684`（`scan_bare_name_mentions`） |

`schema` 对模型的**文档承诺**（`storyboard_tools.py:150`）：

```python
150:    shot_refs: List[str] = Field(default_factory=list, description="引用的关键元素标题数组；留空时系统自动从分组描述里的 [元素名] 令牌与裸名提及解析合并")
```

工具描述里的正面契约（`storyboard_tools.py:265-269`）：

```python
265:        "建组规范：关键元素——每个元素单独一组，组名=元素名，"
266:        "元素设定全文写在分组描述 desc 上；分镜——每个镜头单独一组，组名=镜头名，"
267:        "完整镜头描述写在 desc 上，引用到的元素用 [元素名] 令牌写在描述里"
268:        "（系统会自动解析为引用并挂参考），也可用 shot_refs 显式指定。"
269:        "desc 中 [元素名] 令牌与裸名提及由系统自动解析为引用。"
```

### A.3 落库前的归一 [代码]

`storyboard_ops.py:754-762`：

```python
754:    explicit = [r for r in (explicit_refs or []) if str(r).strip()]
755:    tokens = parse_element_tokens(desc or "")
756:    matched_titles, _unmatched = match_element_titles_report(state, tokens)
757:    bare_hits = scan_bare_name_mentions(
758:        desc or "", state.get(CAT_KEY_ELEMENTS, []))
759:    # 三源合并 → canonical 去重 → **归一为元素组全称**（唯一实现 = canonicalize_shot_refs）。
762:    return canonicalize_shot_refs(state, list(explicit) + matched_titles + bare_hits)
```

`canonicalize_shot_refs`（`storyboard_ops.py:687-719`）把命中元素的值替换为**元素组真实 `title`**，查无此元素则**保留原值**：

```python
703:    index = build_ref_index(state, CAT_KEY_ELEMENTS)
709:        hit = index.get(canonical_ref_key(ref)) or index.get(ref.strip())
710:        value = str(hit.get("title")) if hit is not None else ref
714:        key = canonical_ref_key(value)
```

- `canonical_ref_key(ref) = strip_type_prefix(str(ref or "").strip())`（`storyboard_ops.py:216-222`）；`strip_type_prefix` 只剥 `Element_`/`Shot_`/`Audio_`（`storyboard_ops.py:182-195`）。
- **[复算]** 9999 现场（shot1 desc 写短名 `艾AA` 与 `程心`）与 8888（desc 写裸名 `AA`）：`scan_bare_name_mentions` 对 `程心`/`AA` **命中**，对 `艾AA` **不命中**（详见 §D）。8888 历史注释里"裸名占 43/47"的存量裸名（`storyboard_ops.py:690-694`）在**当前代码复算下会被归一成全称**：
  ```
  stored : ['程心', 'AA', '木星轨道「星环」号球形舱']
  canon  : ['Element_程心', 'Element_AA', 'Element_木星轨道「星环」号球形舱']
  ```

### A.4 重要边界：三源合并**只在建组期**跑一次 [代码]

`storyboard_tools.py:542-553`（`StoryboardPatchGroupTool` docstring）：

```python
545:    事故背景与取舍见 `PatchGroupInput` docstring。本工具**不做**三源合并
546:    （`[元素名]` 令牌 ∪ 裸名提及）：那是**建组**期的一次性解析语义，若在 patch
547:    上重做，「删掉某条引用」会立刻被 desc 里的裸名重新加回来（引用删不掉）。
548:    故 patch 一律**以模型显式传入的 shotRefs 为准**（只做 canonical 去重）。
```

落点 `storyboard_tools.py:607-609`（仅 `canonicalize_shot_refs`，不重跑 desc 解析），以及 `storyboard_ops.py:425-428`（`patch_group` 的 shotRefs 分支走 `dedup_shot_refs`）。

### A.5 现场实证：引用**是模型手抄的**，不是系统解析的 [数据]

9999 会话原文里 11 次 `storyboard_create_group`（shot 类）**全部**显式携带 `shot_refs`——从 `workspace/sessions/proj-1790358500-25465d26/conv-1790358720-e0a3aeef.jsonl` 解析出的 tool_call 参数：

```
title='程心与艾AA在星环号球形舱中冬眠初醒'
   shot_refs = ['程心', '艾AA（AA）', '星环号球形舱（木星轨道）']
   desc mentions 程心 / 艾AA(无令牌) / 星环号球形舱(无令牌)
title='全息窗弹出苍老曹彬，艾AA质问木星城为何未躲进掩体'
   shot_refs = ['程心', '艾AA（AA）', '曹彬（老年）', '星环号球形舱（木星轨道）', '全息信息窗']
   desc mentions 程心 / 艾AA(无令牌) / 曹彬(无令牌) / 全息信息窗(有令牌 [全息信息窗]) / 星环号球形舱(无令牌)
... （共 11 次，全部 shot_refs present=True）
```

**关键推论**：`艾AA`、`曹彬`、`星环号球形舱`、`启示号控制舱` 在 desc 里**通篇没有 `[令牌]`**，唯一能进 `shotRefs` 的通道就是**模型显式手抄全称**。对照之下，desc 里带令牌的 `[全息信息窗]`/`[白色薄片]`/`[无人太空艇]` 才会走系统自动挂载。

（另注：对 8888 的会话目录做**原始子串计数**得 `storyboard_create_group` 提及 95 次、`shot_refs` 键 24 次——这是未解析的字符串计数，只作旁证，不作结论；结论以 9999 的 JSON 解析结果为准。）

---

## B. `src/video_agent/state/storyboard_ops.py` 逐函数审计

### B.1 `parse_element_tokens(text)` — 正则与边界（`:629-650`）[代码]

```python
642:    tokens: List[str] = []
645:    cleaned = re.sub(r"\\[\[\]]", "", str(text or ""))
646:    for raw in re.findall(r"\[([^\[\]]{1,60})\]", cleaned):
647:        token = raw.strip()
648:        if token and token not in tokens:
649:            tokens.append(token)
650:    return tokens
```

| 问题 | 结论 |
|---|---|
| 正则 | `\[([^\[\]]{1,60})\]`——方括号内**不得再含方括号**，长度 1–60 |
| `[...]` 之外匹配什么？ | **什么都不匹配**：无 `【】`、无 `@名`、无 `<<<image_名>>>`、无裸名（裸名是另一个函数） |
| 预处理 | 先删除 **Markdown 转义方括号** `\[` / `\]`（`:645`），使 `\[角色描述…\]` 这类模板占位**不被提取**（`:635-641` 记述：旧实现曾把它当令牌并产出尾部带反斜杠的脏 token，触发**误报警告**） |
| 匹配不到时 | 本函数返回空/短列表；未命中令牌由 `match_element_titles_report` 放入 `unmatched`，**建组通道丢弃不拒收**（`:770-771`） |

**[探针]** `parse_element_tokens("分镜里 [程心] 与 [艾AA（AA）] 出现，模板占位 \\[角色描述\\] 不提取")` → `['程心', '艾AA（AA）']`（占位未被提取，符合预期）。

### B.2 `match_element_titles_report` / `match_element_titles`（`:765-799`）[代码]

```python
772:    titles = [
773:        str(g.get("title") or "").strip()
774:        for g in (state.get(CAT_KEY_ELEMENTS, []) or []) if isinstance(g, dict)
775:    ]
776:    titles = [t for t in titles if t]
777:    matched: List[str] = []
778:    unmatched: List[str] = []
779:    for token in tokens or []:
780:        token = str(token or "").strip()
781:        if not token:
782:            continue
783:        hit = next((t for t in titles if t == token), None)
784:        if hit is None:
785:            hit = next((t for t in titles if token in t or t in token), None)
786:        if hit:
787:            if hit not in matched:
788:                matched.append(hit)
789:        else:
790:            unmatched.append(token)
791:    return matched, unmatched
```

| 追问 | 结论 | 证据 |
|---|---|---|
| 用哪个 state 的哪个键 | 传入 `state` 的 `CAT_KEY_ELEMENTS`（= `"keyElements"`）中每个分组的 **`title`** | `:772-775` |
| 是否剥前缀 | **不剥**。两条比对都在**原始标题**（含 `Element_`）上做 | `:783`、`:785` |
| 大小写 / 全半角归一 | **完全没有**。无 `casefold/lower/unicodedata/NFKC/translate` | `:783-785`；全仓 grep `unicodedata\|NFKC` → 0 命中 |
| 匹配规则 | **精确优先 → 双向子串包含**（`token in t or t in token`） | `:783-785` |
| 未匹配 | 进 `unmatched`；`match_element_titles`（`:794-799`）**静默丢弃**（docstring：令牌是引导不是闸） | `:789-790`、`:794-799` |

**方向性要点**：双向包含是**非对称宽容**——`[艾AA]`（token 是 title 子串）会命中；但**裸名路径没有任何包含逻辑**（见 B.3），所以"写短名"在两条路径上命运完全不同。这是 §D 的核心。

### B.3 `scan_bare_name_mentions` — 「提及即绑定」（`:653-684`）[代码]

```python
656:    """K4 批（2026-09-16 对齐 flova）：裸名提及自动绑定——分镜正文里
657:    提到元素名（原全称/归一裸名）即自动挂引用（提及即绑定）。
658:
659:    镜像前端 desc-ref-utils.ts descChipNames 语义：候选源 = keyElements
660:    全集（原全称 + 归一裸名两形态，Set 去重、≥2 字符守卫、最长优先防重叠）；
661:    命中规则 = 候选名在 desc 子串出现；返回 = 命中的关键元素组标题
662:    （shotRefs 存储口径，去重保序）。纯函数，不改状态。"""
...
668:    for ke in key_elements or []:
671:        title = str(ke.get("title") or "").strip()
674:        bare = strip_type_prefix(title)
675:        for cand in (title, bare):
676:            if len(cand) >= 2 and cand not in seen:
677:                seen.add(cand)
678:                candidates.append((cand, title))
679:    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
680:    hits: List[str] = []
681:    for cand, title in candidates:
682:        if cand in text and title not in hits:
683:            hits.append(title)
684:    return hits
```

| 追问 | 结论 | 证据 |
|---|---|---|
| 「提及即绑定」规则存在吗 | **存在**，且与前端 `descChipNames` 同口径（docstring 明写） | `:656-662`；前端 `desc-ref-utils.ts:119-132` |
| 候选形态 | **只有两种**：① 完整组标题；② `strip_type_prefix(标题)`。**没有短名、没有别名、没有词表映射、没有括号剥离** | `:674-678` |
| 命中口径 | `cand in text` —— **逐字子串包含**；**大小写敏感、全/半角敏感** | `:682` |
| 守卫 / 顺序 | `len(cand) >= 2`；候选按长度**降序**（最长优先防重叠误切） | `:676`、`:679` |
| 返回值 | 命中的**组标题**（shotRefs 存储口径，去重保序） | `:662`、`:682-684` |
| 未命中时 | **不产生任何"未命中"记录**（函数只返回命中项） | `:680-684` |

**缺口一句话**：`Element_艾AA（AA）` 只产 `{Element_艾AA（AA）, 艾AA（AA）}` 两串；desc 里写的 `艾AA` 不是任何一串的子串 → **恒不命中**。

### B.4 `merge_shot_refs` — 三源合并顺序与去重键（`:722-762`）[代码]

- **顺序**：`显式 shot_refs` → `令牌匹配标题` → `裸名提及标题`（`:762`），保序留首。
- **去重键**：`canonical_ref_key(value) = strip_type_prefix(value.strip())`（`:216-222`；与写口 `dedup_shot_refs` `:160-174` 同键）。
- **落库形态**：命中 → 元素组真实 `title`（带前缀全称，2026-09-25 用户裁决见 `:690-701`）；未知引用 → **保留原值**不丢弃。

### B.5 `resolve_shot_refs(...)` 用途与调用点（`:559-585`）[代码]

```python
571:    shot_refs = group.get("shotRefs") or []
572:    if not shot_refs:
573:        return refs
574:    for ref_title in shot_refs:
577:        ke_group = find_ref_group(state, ref_title)
578:        if ke_group is None:
579:            continue
580:        for d in ke_group.get("drafts", []):
581:            img = d.get("imgUrl") or ""
582:            if img:
583:                refs.append({"url": img, "role": "reference"})
584:                break
585:    return refs[:limit]
```

- 用途：把分镜 `shotRefs` 解析为**关键元素概念图 URL**（默认上限 5），供生成参考。
- 比对走 `find_ref_group`（canonical 唯一入口，`:241-254`）——2026-09-23 批10（事故 4444/P0-A）修复：旧实现逐字比对恒不命中（`:198-213`、`:564-566`）。
- **调用点**：
  - `src/video_agent/tools/document_tools.py:888` —— `image_generate` 批量轨：`refs = ops.resolve_shot_refs(state, group) if group else []`
  - `src/video_agent/web/generation_submit.py:273` —— `collect_shot_video_refs`（视频生成自动挂图）
  - 姊妹函数 `resolve_shot_audio_refs`（`:588-626`）→ `generation_submit.py:279`
  - 等价 inline 写口：`src/video_agent/web/routes/generate_image.py:190-198`、`src/video_agent/web/multimodal_builder.py:146-157`
- **对问题 2 的作用**：`resolve_shot_refs(state, group)` 的 `group` 是"被生成草稿所在的分组"，**任何类目**都照跑；关键元素/音频组通常没有 `shotRefs` → 返回 `[]`（见 §F.1）。

---

## C. 失败时的回喂警告在哪里

### C.1 令牌未匹配 → 有警告（shot 专属）[代码]

`src/video_agent/tools/storyboard_tools.py:386-394`：

```python
386:        result_data: Dict[str, Any] = {"group_id": new_id}
387:        if unmatched_tokens:
388:            _miss = "、".join(unmatched_tokens[:5]) + ("…" if len(unmatched_tokens) > 5 else "")
389:            result_data["detail"] = (
390:                f"已建组，但描述中的 [元素名] 令牌未匹配到关键元素组（已丢弃、未挂引用）：{_miss}。"
391:                "元素名须与关键元素组标题一致（read_state_group 可查），必要时修正 desc 里的 [元素名] 令牌。")
392:            result_data["warnings"] = [
393:                f"分镜「{_title[:12]}」的元素令牌未匹配：{_miss}（引用缺失，跨镜一致性可能断链）"]
394:        return ToolResult(success=True, data=result_data)
```

- 两条文案唯一家即此：`已建组，但描述中的 [元素名] 令牌未匹配…`（`:390`）、`引用缺失，跨镜一致性可能断链`（`:393`）。
- **模型可见通道**：`detail` 经 `src/video_agent/core/fc_feedback.py:383-403`

```python
386:            data = tr.get("data") or {}
387:            detail = str(data.get("detail") or "").strip()
394:            _gid = str(data.get("group_id") or "").strip()
397:                detail = f"{_gid_line}。{detail}" if detail else _gid_line
401:            if detail and total + len(detail) <= FEEDBACK_MAX_TOTAL_CHARS:
403:                lines.append(f"- {name}：执行成功，{detail}")
```

- **用户可见通道**：`src/video_agent/core/fc_tool_runner.py:815-821`

```python
815:            # --- 工具成功结果携带的警告（如建组闸机回喂清单）
816:            # 升级为轮末用户可见警告，不得只留在 trace（静默丢失禁令） ---
817:            if data and isinstance(data.get("warnings"), list):
818:                for _tw in data["warnings"]:
820:                    if _tws and _tws not in self.gate_warnings:
821:                        self.gate_warnings.append(_tws)
```

- 另有一道**硬拒收回喂**（strict 模式、空引用或标题点名未引）：`src/video_agent/core/fc_gates.py:318-337`

```python
318:        missing = [
319:            t for t, kid in ke_map
321:            if ops.strip_type_prefix(t) in ops.strip_type_prefix(title)
322:            and kid not in refs
323:            and ops.strip_type_prefix(t) not in ref_keys
324:        ]
325:        if not refs or missing:
326:            detail = (
327:                "引用为空" if not refs
330:                else f"标题提及的 {'、'.join(ops.strip_type_prefix(t) for t in missing[:3])} 未被引用"
331:            )
332:            return (
333:                f"storyboard_create_group 被拒收：分镜「{title[:12]}」{detail}。"
334:                "引用须非空并覆盖标题提及的角色/场景（关键元素 id 或标题，"
335:                "或写进 desc 的 [元素名] 令牌由系统自动解析）。"
336:                "请补全引用后重试。"
337:            )
```

  启用条件：`fc_gates.py:280-283`（`name == "storyboard_create_group"` 且 `ctx.injected_skill` 且 `gate_mode()=="strict"`）；判定引用集合与写口**同引** `ops.merge_shot_refs`（`fc_gates.py:305-310`）。

### C.2 裸名提及失败 → **完全静默** [代码]

- `unmatched_tokens` 初值在 `storyboard_tools.py:348` 置空，**只**由令牌通道赋值（`:372-374`）。
- `scan_bare_name_mentions` **没有"未命中"概念**（只返回命中项，`:680-684`）→ desc 里写短名导致漏绑时，`detail` 与 `warnings` 都是空。
- 全仓 grep `引用缺失|令牌未匹配|未挂引用` 仅 3 处命中：`storyboard_tools.py:347/369/390/393` 一带 + `storyboard_ops.py:639,768-770` 的 docstring——**没有任何一条覆盖"desc 提到元素但没挂上引用"**。

**⇒ 这解释了用户报告的"没有任何提示"**：现场 9999 的 desc 里，`艾AA` 没有令牌，所以连 C.1 的告警都不会出现。

### C.3 现场会话里确实**没有**任何引用类告警 [数据]

对 `workspace/sessions/proj-1790358500-25465d26/*.jsonl` 全量 grep `被拒收|引用须非空|未被引用|已建组，但描述中`：

```
conv-1790358604-3ed9aa21.jsonl  被拒收 x2   （上下文是"打卡后后续工具调用会被拒收"，与引用无关）
conv-1790359332-2ee652b5.jsonl  被拒收 x2   （同上）
—— 无一处 "已建组，但描述中的 [元素名] 令牌未匹配"、无 "引用须非空"、无 "未被引用"
```

即：**整条引用链在本项目上从未报过警**，与 C.2 的静默结论一致。

---

## D. 中文人名 vs `Element_艾AA（AA）`：逐条比对式判定（**问题 1 根因**）

### D.1 逐条比对式清单 [代码]

| # | 通道 | 比对式 | 位置 |
|---|---|---|---|
| ① | 令牌提取 | `re.findall(r"\[([^\[\]]{1,60})\]", cleaned)` | `storyboard_ops.py:646` |
| ② | 令牌精确 | `t == token` | `storyboard_ops.py:783` |
| ③ | 令牌包含 | `token in t or t in token` | `storyboard_ops.py:785` |
| ④ | 裸名候选生成 | `for cand in (title, strip_type_prefix(title))` | `storyboard_ops.py:674-678` |
| ⑤ | 裸名守卫 | `len(cand) >= 2` | `storyboard_ops.py:676` |
| ⑥ | 裸名命中 | `cand in text` | `storyboard_ops.py:682` |
| ⑦ | 归一（落库值，不参与"是否命中"） | `strip_type_prefix(value.strip())` | `storyboard_ops.py:216-222, 709-714` |
| ⑧ | 前端内联图块候选 | `titles.add(raw)` + `titles.add(stripTypePrefix(raw))` | `src/web/lib/desc-ref-utils.ts:127-129` |
| ⑨ | 前端内联图块渲染 | `new RegExp('(' + names.map(escapeRe).join('|') + ')', 'g')` + `re.exec(text)` | `src/web/lib/desc-ref-utils.ts:157-160` |

### D.2 判定表（标题 = `Element_艾AA（AA）`，desc 写中文人名）

| 路径 / desc 写法 | 命中？ | 依据 | 前提条件 |
|---|---|---|---|
| 令牌 `[艾AA]` | **命中** | ③ `'艾AA' in 'Element_艾AA（AA）'` | 必须写成**方括号令牌**；写裸名则 ① 提取不到，通道根本不参与 |
| 令牌 `[AA]` | **命中** | ③ 同上 | 同上 |
| 令牌 `[艾AA（AA）]` | **命中** | ② 精确相等 | — |
| 令牌 `[艾AA(AA)]`（半角括号） | **不命中** | ②③ 全角/半角互不相等 | 半角括号是另一串，既不等也不是子串 |
| 裸名 mention `艾AA` | **不命中** | ④ 候选 = `{Element_艾AA（AA）, 艾AA（AA）}`；⑥ 二者都不是子串 | 需 desc 出现**完整** `艾AA（AA）` 或 `Element_艾AA（AA）` |
| 裸名 mention `艾AA（AA）`（全称） | **命中** | ⑥ `'艾AA（AA）' in desc` | 全角括号逐字一致 |
| 裸名 mention `Element_艾AA（AA）` | **命中** | ⑥ 完整标题形态（候选 ①） | — |
| 标题若为 `Element_艾AA`（无别名） | 裸名 `艾AA` **命中** | 候选含 `艾AA` | 无括号别名时短名==裸名，退化为可用 |
| 前端内联图块（desc 写 `艾AA`） | **不渲染** | ⑧⑨ 候选不含 `艾AA` | 即使 `shotRefs` 已挂该元素 |
| 前端内联图块（desc 写 `艾AA（AA）`） | **渲染** | ⑧⑨ | — |

**确定结论**：
1. 令牌路径 **会**命中（双向包含救的），**前提是写 `[艾AA]` 形态**；
2. 裸名路径 **不会**命中，**除非** desc 逐字出现 `艾AA（AA）`/`Element_艾AA（AA）`；
3. **别名短名（括号外的部分）在整个代码库里不是任何一处候选串**——写口（④）与前端（⑧）同构同缺，这是问题 1 的机制根因；
4. 大小写、全/半角、全角括号**一律不归一**（无 `NFKC`/`casefold`；grep 佐证）。

### D.3 只读探针实证 [探针]

```
T1 tokens : ['程心', '艾AA（AA）']                          # 转义占位未被提取
T2 match  : (['Element_程心', 'Element_艾AA（AA）'], ['艾AA(AA)'])
            # 艾AA / AA 靠③双向包含命中；半角括号的 艾AA(AA) 进 unmatched
T3 desc='艾AA 与程心并肩走在月面上。' -> bare=['Element_程心']      # ★ 艾AA 漏绑
   merge=['Element_程心']                                        # ★ 三源合并后仍漏
T3 desc='艾AA（AA）走来'             -> bare=['Element_艾AA（AA）'] # 写全称才命中
T3 desc='艾AA(AA) 走来'              -> bare=[]                   # 半角括号漏绑
T3 desc='艾aa 走来'                  -> bare=[]                   # 大小写敏感
T3 desc='[艾AA] 走来'                -> merge=['Element_艾AA（AA）'] # 令牌路径命中
T5 空 state -> ops.merge_shot_refs({}, "艾AA 与程心走来", []) = []   # 元素未建时静默为空
```

### D.4 别名 vs 非别名的自然对照实验 [复算]

用**同一份生产函数**对两个真实项目的全部关键元素跑"裸名绑定"，只看**函数返回值**（不看落库 refs，避免被模型手抄行为污染）：

| 项目 | 标题形态 | 裸名可否绑定 |
|---|---|---|
| 8888 | `Element_程心`、`Element_AA`、`Element_瓦西里`、`Element_白色薄片` …（**无别名**） | **全部 True** |
| 9999 | `Element_艾AA（AA）`、`Element_曹彬（老年）`、`Element_启示号控制舱（太阳系外缘）`（**带全角括号别名**） | **False** |
| 9999 | `Element_程心`、`Element_瓦西里`、`Element_白Ice`、`Element_全息信息窗` …（无别名） | True |

```
-- 8888 (no alias)
   Element_程心   alias=False  bareOccursInDesc=5  shortBindable=True
   Element_AA     alias=False  bareOccursInDesc=5  shortBindable=True
   ...            （无别名者全部 True）
-- 9999 (alias)
   Element_艾AA（AA）          alias=True  bareOccursInDesc=0  shortForm='艾AA'  shortOccurs=3  shortBindable=False
   Element_曹彬（老年）         alias=True  bareOccursInDesc=0  shortForm='曹彬'  shortOccurs=2  shortBindable=False
   Element_启示号控制舱（太阳系外缘） alias=True  bareOccursInDesc=4  shortBindable=False
```

注意 `bareOccursInDesc` 一列：带别名标题的**全称/裸名在 desc 中出现 0 次**，而**短名出现 3/2 次**——即"元素名与 desc 写法天生对不上"。

### D.5 现场复现：用户所说的「艾AA 没被挂上引用图块」[复算 + 数据]

**先厘清两个不同 UI 构件**（用户说的"引用图块"落在哪一个，结论不同）：

- **引用 chips 行**（`引用: 程心 ×  艾AA（AA） ×  + 添加`）：`src/web/components/left-panel/group-card/ShotRefsChips.tsx:82-108`，数据源 = `group.shotRefs`（`:15`），经 `resolveRefElement`（`:26`）canonical 解析 → 9999 的 shot1/2/3 **会**显示 `艾AA（AA）`。
- **desc 内联图块**（分镜正文里把提到的人物渲染成块）：`src/web/components/left-panel/group-card/ShotDescEditor.tsx:31-37` → `descChipNames` + `renderDescToDOM` → **不会**显示 `艾AA`。

住户报告是"**分镜描述（desc）里**有些提到的人物没有被挂上引用图块"——正对上第二项。复算结果：

```
shot KE title                  desc含短名   在shotRefs   图块渲染   判定
1    Element_艾AA（AA）          艾AA         True         False     引用已有但 desc 渲染不出图块
2    Element_艾AA（AA）          艾AA         True         False     同上
2    Element_曹彬（老年）          曹彬         True         False     同上
3    Element_艾AA（AA）          艾AA         True         False     同上
3    Element_曹彬（老年）          曹彬         True         False     同上

--- 用户例子 艾AA 的三个 shot 明细 ---
shot 1 refs=['Element_程心', 'Element_艾AA（AA）', 'Element_星环号球形舱（木星轨道）']
    desc 中形态: 短名'艾AA'=True   全称'艾AA（AA）'=False
shot 2 / shot 3 同上（refs 里都有 Element_艾AA（AA），desc 里都只有短名）
```

即 9999 现场：**`艾AA`（×3）、`曹彬`（×2）全部是"引用在、desc 块不在"**；成因是 ⑧⑨ 的候选串不含短名。

**同时存在的地雷（缺陷 ②）已用 token 统计定位** [数据]：9999 的 15 个元素里，只有 `全息信息窗`/`白色薄片`/`无人太空艇` 在 desc 中出现 `[令牌]` 形态；`艾AA`(3 镜)、`曹彬`(2 镜)、`星环号球形舱`(3 镜)、`启示号控制舱`(4 镜) 的 desc **一律无令牌**。这些引用能落库，**只可能**来自模型手抄的显式 `shot_refs`（§A.5 已证 11/11 都传了）。**一旦模型哪次照工具文档留空**（`storyboard_tools.py:150`、`:265-269`），这些短名就会变成真正的"漏绑 + 零告警"。

---

## E. 「关键元素在分镜之后才创建」是否会导致匹配不到？ [代码]

**结论：会；解析用创建时刻快照，且全库无任何回填通道。**

1. **创建时刻快照**（不是最终 state）：

```python
373:            _, unmatched_tokens = ops.match_element_titles_report(
374:                svc.state_dict, _tokens)
375:            new_group["shotRefs"] = ops.merge_shot_refs(
376:                svc.state_dict, _desc or "", params.shot_refs)
...
379:            svc.state_dict.setdefault(cat_key, []).append(new_group)
```

   —— `:373-376` 读 `svc.state_dict`，新组在 `:379` 才写入；没有延迟重算。

2. **闸机（读口）用同一时刻的 `ctx.state()`**：`core/fc_gates.py:309-310`（`merge_shot_refs`）、`:313-317`（`ke_map` 来自 `ctx.state()`）；strict 下元素缺失会直接拒收（`:325-337`），逼模型先建元素。

3. **无 backfill**：全仓 `merge_shot_refs` 仅 2 处调用（`storyboard_tools.py:375`、`fc_gates.py:309`）；`canonicalize_shot_refs` 仅 2 处写口（`storyboard_ops.py:762`、`storyboard_tools.py:608`）。元素后建后**没有任何代码回填旧 shot 的 `shotRefs`**。

4. **唯一补救路径**：`storyboard_patch_group` **显式**传 `shotRefs`（`storyboard_tools.py:607-609` + `storyboard_ops.py:428`）；或删组重建（4444 事故里模型为此删光 22 个 shot 组，见 `storyboard_tools.py:199-204` 记述）。**改 desc 不会重算引用**（A.4），所以"事后往 desc 补 `[艾AA]`"也补不上引用。

5. **次生现象**：读口（`find_ref_group`/`canonical_ref_key`）已完全 canonical 化，但它只能解析**已经写进 `shotRefs` 的东西**；写口漏绑 → `resolve_shot_refs` 返回 `[]`（[探针] T5：空 state 下 `merge_shot_refs({}, "艾AA 与程心走来", []) == []`）。

---

## F. 问题 2：分镜表格图草稿 `refAssets` 为空（`@[角色代号]` 不生效）

**总结论：`refAssets` 为空是"预期行为"（`@` 引用从不写 `refAssets`），真正的缺陷是 `@[角色代号]` / `@[场景代号]` 这类 Skill 占位符不可能解析出素材。**

### F.1 `@` 引用**从设计上就不写 `refAssets`**

前端插入 `@` chip 时**有意不加入参考栏**：`src/web/hooks/use-prompt-mention.ts:141-143`

```ts
141:   /** 选中提及项：把光标处的 @query 替换为缩略块 chip。
142:    *  用户决策：@ 故事板素材不自动加入参考素材栏（生成时由后端按 @ 解析随请求发送）。 */
143:   function insertMentionChip(item: MentionItem) {
```

（对照：真正写参考栏的路径是 `RefAssetBar.addRefUrl`，`src/web/components/middle-panel/RefAssetBar.tsx:68-82`，以及 `src/web/lib/ref-upload.ts:16-29`。）

后端只在**提交生成时**把 `@` 解析结果并入参考：`src/video_agent/web/generation_submit.py:80-89`（生图）、`:336-346`（生视频）

```python
 81:    base_ref_urls: List[str] = [u for u in (draft.get("refAssets") or []) if u]
 86:    media_map = build_storyboard_media_map(state_dict)
 87:    eff_prompt, final_refs = resolve_prompt_mentions(
 88:        draft.get("prompt", ""), base_ref_urls, media_map, max_refs=settings.image_ref_limit
 89:    )
```

生成入口对**任何类目**的草稿都只按 `group.shotRefs` 挂图：`src/video_agent/tools/document_tools.py:887-900`

```python
887:        for group, draft, dtype in targets:
888:            refs = ops.resolve_shot_refs(state, group) if group else []
...
894:            task_id = submit_image_task(
895:                state, draft, provider_id, model, refs,
```

（等价 inline 实现：`src/video_agent/web/routes/generate_image.py:190-198`。）

**[数据]** 9999 的 11 张 `*-运镜轨迹示意图`（`mediaType=image`，挂在 **shot** 组内）**全部 `refAssets=[]`**，并且**提示词里一处 `@` 都没有**——模型把 Skill 模板改写成了「无参考图：场景与人物外观以本提示词文字描述为准」：

```
group='Shot_程心与艾AA在星环号球形舱中冬眠初醒' draft='Shot01-运镜轨迹示意图' refAssets=[] atMentions=[]
... （共 11 条：refAssets 全为 []，atMentions 全为 []）
```

### F.2 `@[角色代号]` 为什么必然失败

**（a）名称映射表里没有这些键**：`src/video_agent/core/prompt_refs.py:65-108`（`build_storyboard_media_map`）只登记：KE 组标题、其剥前缀裸名、草稿 `label`、URL 文件名。

```
[探针] media_map keys = ['Element_艾AA（AA）', '艾AA（AA）', '艾AA 三视图', 'aa.png',
                        'Element_木星轨道「星环」号球形舱', '木星轨道「星环」号球形舱', 'jup.png']
```

**（b）未命中时静默降级**（去掉 `@` 留文字，不报错）：`prompt_refs.py:129-142`

```python
131:        info = media_map.get(name)
132:        if not info:
133:            return name  # 未命中：去掉记号，保留文字
```

**（c）用 Skill 模板原句实测**（正则 = `prompt_refs.py:35-38`）：

```
Skill 模板原句     -> resolved 里 @ 与包络被吃掉、refs=[]         ← 问题 2 直接复现
'画面 @艾AA 站在舱内'       -> 未命中（该键不存在），refs=[]        ← 别名短名不是键
'画面 @艾AA（AA） 站在舱内'  -> 命中，refs=['/a/aa.png']           ← 必须写全称（含括号）或全裸名
'画面 @Element_艾AA（AA）'  -> 命中，refs=['/a/aa.png']
```

**（d）转义方括号的二次坑**：Skill 原文是 `@\[角色代号\]`（`data/skills/AI-短剧一站式生成/SKILL.md:207-210`），而技能注入是**逐字不反转义**的（`src/video_agent/web/skill_docs.py:103-132`，`_add` 直接 `(body or "").strip()`）。用**文件原文**做探针：

```
RAW SEGMENT repr: '...- Image 1: Character sheet for @\\[角色代号\\] — replicate exactly\\\n...'
_MENTION_RE.findall(block) -> [('', '\\'), ('', '\\')]        # 只吃到一个反斜杠字符
resolved -> '... for \\[角色代号\\] — replicate exactly ...'   # 记号原样留下，refs=[]
```

即：`@\[…\]` 形态下 **@ 记号根本不吃方括号**，只吃掉了 `\`。这与后端令牌解析器 `parse_element_tokens`（`storyboard_ops.py:645` 主动剔除 `\[`/`\]`）是**两套"转义方括号"口径**，是易踩的次生坑。

（前端同轨正则确有可选包络 `[@＠]\\[?(${alt})\\]?`，`src/web/lib/prompt-ref-utils.ts:144-147`；但它是把**候选名**内插进正则，候选名来自 `storyboardMediaMap()`（`src/web/lib/prompt-mentions.ts:51-84`）——同样没有"角色代号/场景代号/别名短名"这些键，因此同样渲染不出 chip。）

### F.3 问题 2 判定表

| 断言 | 判定 | 证据 |
|---|---|---|
| "`refAssets` 为空 = 图块没被引用" | **部分错**：`@` 引用**从不写** `refAssets`（设计如此），它是"生成时才解析"的另一条通道 | `use-prompt-mention.ts:141-142`；`generation_submit.py:80-89` |
| "`@[角色代号]` 应该被解析出参考图" | **不会**：占位符不是映射表的键；未命中静默降级为纯文字 | `prompt_refs.py:98-107,131-133` + 探针 |
| 表格图草稿能否拿到参考图 | **取决于挂在哪**：挂在 shot 组 → 生成时按 `group.shotRefs` 自动挂（`document_tools.py:888`）；挂在 KE 组（如 3333 的 15 张 image 卡）→ `shotRefs` 恒空 → 只能靠显式 `refAssets` | `document_tools.py:887-900`；`scripts/migrate_storyboard_existing.py:37-39` 记录 3333 那批卡在 shot 组内 |
| 正确写法门槛 | 提示词写 `@艾AA（AA）` / `@Element_艾AA（AA）`（**含括号的完整标题**）或 `<<<image_名称>>>`，或把素材显式加进参考栏 | 探针 (c) + `prompt_refs.py:98-104` |

---

## G. 根因清单与建议方向（供主代理决策，本次不改码）

| 优先级 | 根因 | 唯一/关键位置 | 建议方向（不在本报告实施） |
|---|---|---|---|
| P0 | 候选形态缺"别名短名"一级——写口与前端同构同缺，导致 desc 写短名时**图块渲染不出**（缺陷①，现场实证 5 处） | `storyboard_ops.py:674-678` ↔ `src/web/lib/desc-ref-utils.ts:127-129` | 在**单一事实源**处补"别名短名"候选（取括号前片段等），两侧同引；须先定"什么算别名"的词法规则，避免误切（与 `desc-ref-utils.ts:92-102` 的编号剥离同属"显示层兜底"族） |
| P0 | 裸名漏绑**零告警**——`unmatched` 只覆盖令牌，desc 提到元素却没挂引用时用户/模型都无感 | `storyboard_tools.py:347-394`、`storyboard_ops.py:680-684` | 让裸名扫描也产出"疑似未绑定"清单（新增一条 `warnings`，文案可复用 `:393`），不改拒收口径 |
| P1 | 三源合并**只在建组期**跑一次，desc 后改不重算，元素后建不回填 | `storyboard_tools.py:545-553`、`.py:607-609` | 提供"重算引用"的显式通道（例如 patch 支持 `recomputeShotRefs: true`），或 `patch_group` 在 desc 变更且 shotRefs 未显式给出时给出**提示**（不是静默） |
| P1 | 创建时刻快照 + 无 backfill | `storyboard_tools.py:373-379` | 同上；或在元素新建后扫描历史 shot 的 desc（只告警不自动改） |
| P1 | `@` 引用的名称键缺"别名短名/占位符"→ Skill 模板 `@[角色代号]` 必然落空 | `prompt_refs.py:98-107,131-133`；`prompt-mentions.ts:71-76` | ① Skill 侧把占位符改成真实标题写法；② 或把"未命中"从**静默**改为**可见警告**（当前连 `warnings` 都没有） |
| P2 | 转义方括号两套口径（令牌解析器剔除 vs mention 正则只吃反斜杠），技能注入不反转义 | `storyboard_ops.py:645`、`prompt_refs.py:35-38`、`skill_docs.py:115-132` | 统一"模板占位"语义；至少在注入或解析其一做确定性转义归一 |
| P2 | 未决项：`refAssets` 双形态（URL vs `draft-*` id） | 见下方"未决" | 需专门确认写入方后再定 |

### 未决 / 未取证项（诚实登记）

1. **`refAssets` 双形态**：9999 现场表格图卡 `refAssets=[]`，而**视频卡** `refAssets=['draft-1790359321-a010380d', …]`（**KE 草稿 id**，非 URL；已验证这些 id 确实存在）。前端 `RefAssetBar.addRefUrl`/`ref-upload.ts` 写入的是 **URL**，后端 `generation_submit.py:81` **直接把 refAssets 当参考 URL 发送** ⇒ id 形态在生成链路上**不被解析**（`buildRefAssetMap` 的键是 KE 草稿 `label` 与文件名，`prompt-ref-utils.ts:60-73`）。写入方（Agent 手写 vs 前端某路径）**本次未穷尽**。
2. **问题 2 的现场文本**：当前 DB 里 9999 的 11 张表格图草稿**已无 `@` 记号**（模型改写为「无参考图」），故 F.2 由**代码 + 探针**给出，而非现场草稿原文。
3. `workspace/state.sqlite3` 的 `generation_tasks`（`kv` 表）只保留 12 条任务，**不含**表格图生图记录，无法从任务日志侧核对"实际发送给模型的参考图列表"。
4. `pt_run2\` 不可读（沙箱拒绝），未与 `data\skills\` 做历史比对。
5. 8888 会话目录的 `shot_refs` 计数（24/95）为**原始子串计数**、非 JSON 解析值，仅作旁证。
