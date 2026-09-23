# CHANGELOG — 裁决 / 批次 / 事故历史留痕（唯一家）

> 本文件是「批次号 / 裁决编号 / 事故注记 / 已退役机制」**历史留痕的唯一登记处**（P1 单一事实源）。
> 规则正文（`ARCHITECTURE_RULES.md`、`AGENTS.md`）与代码注释只写**现行规则与结论**，不内嵌考古编号；
> 需要出处时查本文件（较早留痕已物理分卷至 `docs/history/`，索引见 §五），整卷原文查 §四 对应 git tag。
> 追加式登记：新裁决 / 新批次在对应小节顶部加一条，不改写既有条目。

---

## 一、架构决策记录（ADR）编号对照

原 `docs/adr/0001-0007` 已整卷归档删除，原文见 git tag `adr-archive-20260901`。
仓内代码与文档原先以「ADR-000X」标注出处的位置，现只保留**语义术语**
（问即停 / 主体回归 / 协议单轨 / 指令性制作手册 / 三态消费 等），编号与结论以本表为唯一对照。

| 编号 | 裁决日期 | 结论（一句话） | 现行规则落点 |
|---|---|---|---|
| ADR-0001 | 2026-08-19 | 双轨制冻结与退役路线图：动作通道单轨 = FC 工具调用；文本协议（`text_actions.md` / `action_parser` / 非 FC 聊天适配器）冻结与删除同日执行完毕（已执行完毕） | 宪法 Rule 2、Rule 6 |
| ADR-0002 | 2026-08-19 | 控制流统一：废除概率路由、单一外层循环；决策 1（阶段前置闸）保留为平台否决层，决策 4（可观测性）保留并强化 | 宪法 Rule 2 |
| ADR-0003 | 2026-08-20 | Workflow Runtime 单一控制实体（宪法 v6）：阶段表 / 依赖图 / 客观探针 / 原子轮提交 / 四投影同源 | 已被 ADR-0004 取代（机械直跑 / 审批直跑退役，其余降为账本职能） |
| ADR-0004 | 2026-08-21 | 主体回归：模型永远唯一行动主体，`workflow_runtime` 降级为账本 + 裁判数据层、不发起任何行动；直跑驱动符号入防复活清单 | 宪法 Rule 2 |
| ADR-0005 | 2026-08-27 | 子代理隔离（**草案，未接受、本期零编码**）：子代理 = 隔离上下文中的模型调用，不是新行动主体；实现须另行立项裁决 | 未落地 |
| ADR-0006 | 2026-08-27 | 阻塞化暂停（问即停）：暂停发行成功即经 reducer 事务性写入三态并结束本轮；accept / decline / cancel-supersede 三态消费；单一活跃暂停槽位的「互斥拒收并结构化回喂」降级为防御断言 | 宪法 Rule 2、§2.7 |
| ADR-0007 | 2026-08-29 | Skill = 指令性制作手册（用户显式裁决，不可再议）：只读属性废除、压制性包壳退役、manifest 无权覆盖平台硬边界 | 宪法 §2.2、§2.8；`docs/GOVERNANCE.md` §四 G1 |

取代关系为双边注记（ADR-0002↔0003、ADR-0003↔0004、ADR-0004↔0006），原文见 git tag；
adr-bilateral 检查项的现行状态以 `scripts/check_doc_pointers.py` 为准（门禁清单唯一事实源 = `scripts/acceptance.py` GATES / RATCHETS 表）。

---

## 二、宪法正文迁出的批次 / 裁决 / 事故注记

以下条目原内嵌于 `ARCHITECTURE_RULES.md` 规则正文（地质层）。每条保留原编号、裁决日期与结论；
规则的**现行语义**仍在宪法正文，本处只留历史细节。

> **分卷重定向（任务17 / R-6）**：本节只保留 **2026-09-02 起**的近期活跃留痕；**2026-09-01 及更早**的条目已 verbatim 物理迁至 `docs/history/`（不改写历史正文），逐卷索引见 §五。
> 泛化指针（「留痕见 CHANGELOG.md」一类）经本节 → §五 索引一跳可达；已知段级指针同批直连分卷文件（宪法 §五「事故经过」→ `docs/history/2026-08.md`）。

### 2026-09-23 · 批13 `todo_write` 收窄为子代理专属 + 补齐 dsh 漏抄校验 + 动作日志漏登记
- **用户裁决（先取证后裁决）**：用户提出「todo 对本项目没什么用，反是上下文浪费——只要激活了 skill 按 skill 流程走，是不是就没必要这个工具」。查证后用户裁定：**主代理删、子代理保留、尾部注入删掉（回到原版）、重复校验补上**；`describe_fc_tool` 漏登记**独立照修**。
- **取证结论（依据全部来自 dsh 原版源码/README，非推断）**——两平台**前提不同**，故同一工具在两边价值不同：
  - dsh **Skill 无步骤流**（`dsh-skill` 只给 `<skill_content>` 方法参考），todo 是**流程的唯一来源**（填空缺），故必需；
  - 本平台 **16/16 个 Skill 都有 `<planner>` 段**（步骤 + `依赖关系` 全文注入），主代理的 todo 是把同一份步骤**誊第二遍** ⇒ **同一事实源两份（P1 违规）**。
  - **4444 实证**：主代理清单 `59fbf12bb8b2`／`c2a5551242fc` 逐字是「第 1 步…第 8 步」= Skill `<planner>` 誊本；而子代理清单（`14f0c0c569d8`）含**项目实例信息**（「批次1：程心/AA/曹彬/白Ice/瓦西里A」），**不是章节誊本** ⇒ 子代理处仍是填空缺。**这就是「主代理删、子代理留」的判据。**
- **D-13a 主代理摘除（可见面）**：`todo_write` 并入 `subagent.CHILD_ONLY_TOOLS`（**复用 `structured_output` 既有单一机制**，不新造）。**为何不用 `MAIN_AGENT_DENY`**：该集语义是「阶段产物写入工具」且有 import 期 fail-loud 校验要求成员必须属于某 `_STAGE_TOOLS` 阶段——todo 不是阶段产物工具，塞进去会撞闸；且 `MAIN_AGENT_DENY` 会经 `child_deny_set` 反向裁掉**所有子代理**，与「仅子代理持有」正相反。端到端行为验证：主代理（生产编排）裁掉 ✅／子代理（`script_analyze`）保留 ✅。
- **D-13b 尾部注入整段删除（回到 dsh 原版口径）**：`build_todo_note` 与 `_read_todos_from_raw` **真删**（**不留兼容空壳**——回归钉 `test_note_builder_is_gone` 断言 `hasattr` 为假）。依据：dsh **不回注模型**（`dsh-session-projection` README「模型体验：**无**」；原版注释原文「the complete `todo/write` session event is UI and replay state, **not a second model message**」）。批8 自加这条注入与 Skill `<planner>` 段构成双事实源；且尾部注入的正是**模型自己上一轮刚提交的内容**（零新增信息）。`prompts/shared/todo_write.md` 的 `LIST_HEADER`/`LIST_FOOTER` 分节**同批删除**（无消费方即不得留孤立文案，有钉）。
- **D-13c 补齐 dsh 漏抄项（fail-loud，停掉静默 flattening）**：原版 `toTodoList`（`lib/index.js:45-62`）对**空/重复 content 一律 `throw`**，注释原文「the logged snapshot must equal what the model believes it wrote... **fails loud at the schema boundary instead of silently flattening**」。批8 只抄了 schema 层形状：空 content 是 `continue` **静默跳过**、重复项**照收**——**恰好是原版点名禁止的 silently flattening**（本清单用途就是「模型以此核对进度」，账本被静默改写后模型会按**自己以为的**清单继续，与落盘事实分叉，违反 P3 状态即数据）。同批把条数/单条长度上限也从**静默截断**改为**显式拒收**（截断同样使落盘内容 ≠ 模型所写）；描述文案同步告知拒收条件（原先静默吞、无需告知，改拒收后不告知会白费往返）。
- **C-1′ 动作日志漏登记（`describe_fc_tool`）**：批8 新增 `todo_write` 只加进注册表、没加进 `describe_fc_tool`（FC 轨动作日志唯一入口）⇒ 日志回落兜底句「**执行工具 todo_write（累计失败 N 次）**」，**英文工具名裸奔给用户**——与批12/C-1 的 `storyboard_patch_group` 漏登记是**同一个病**（新工具只改注册表、未改展示层）。→ 补分支输出成果语「更新任务进度清单（N 项进行中）」。**同时更正批12 的一处顺带判断**：`list_skills`/`get_skill_asset` 落到同一兜底句**并非漏登记**，而是**故意**用该句作 `_LOW_INFO_KEYS` 折叠键（既有设计，脆弱耦合，本批不动、如实登记）。
- **同批修正的悬空承诺（散文层）**：`prompts/planner/skill_runtime.md` 第 6 条删去「用 `todo_write` 记账」（主代理已无该工具，留着即悬空指令）；`prompts/planner/subagent.md` 的 DELEGATION_CONTEXT 把「清单**会随状态注入**」改为「清单整表覆盖、每会话一份；进度以自己最近一次提交为准」——**注入已删，旧句成了假承诺**（正是本仓反复在修的「承诺了却没做」病）。
- **未一并处理（如实登记，防遗忘）**：① `read_session_todos` 当前**仅测试消费**（尾部注入删除后唯一生产消费方消失）；保留理由是它是账本读取的**单一入口**（防内部结构成为多份事实源，P1），已在 docstring 写明现状与保留理由；② dsh 的 `todos` **会话投影 + `TodoPanel` UI** 本平台**没有**（属「照抄未抄全」的已知缺口，且是**用户可见面**的缺口）；③ `run_subagent` 等仍走通用兜底句（4444 窗口内 82 次调用）——是否登记成果语属产品面取舍，未擅动。
- **验证**：`acceptance --quick` **15/15 全绿**；后端全量 **2552 passed / 42 failed**（42 条全为债务 D-22 既有红：`test_openai_compat` 27 / `reasoning_passthrough` 7 / `adapter_stream_protocol` 4 / `cached_tokens_telemetry` 3 / `progressive_disclosure_relocation` 1，**分布与既有记录一致、新增失败 0**；根因仍为 `NO_PROXY` 含 `[::1]`）；前端 **124 文件 / 1041 用例全绿**；`tsc --noEmit` PASS；**四处突变验证已做**（回退 `CHILD_ONLY_TOOLS` → 2 钉红；回退重复校验 → 2 钉红；回退空 content 校验 → 1 钉红；把 `build_todo_note` 空壳加回 → 1 钉红）。

### 2026-09-23 · 批12 结构闸两处坏判定 + 改分组动作日志 + sceneRefs 全链更名 shotRefs
- **用户裁决**：①「开干」；② **字段名一并改**（「`sceneRefs` 翻译过来是场景引用，有歧义」）；③ **存量数据不用管**（「那些项目都是测试，我待会儿会删掉跑新的」）；④ 命名取 **`shotRefs`**、**全链一起改**。
- **B-1（结构闸只看显式入参，不看 desc）**：工具对模型的**文档承诺**是「`scene_refs` 留空时系统自动从分组描述里的 `[元素名]` 令牌与裸名提及解析合并」，写口（`storyboard_create_group`）**确实这么做了**；但闸机**只读 `args.get("scene_refs")`**、为空即拒 ⇒ **在合并之前就把人拦了**。**4444 实证**（`conv-1790159633` seq55–59）：前 5 次建镜头按文档留空、元素规范写在 desc 的 `[令牌]` 里 ⇒ **5 次全被拒**；此后 22 次改为一律显式重抄。全量统计：该子代理 53 次建组，**31 次未传、22 次传了**。⇒ **平台亲手教模型放弃了它的正确行为**（与 4444/Q2① 同型的自伤）。→ 合并体抽为 `ops.merge_shot_refs` **唯一实现**，写口与闸机**同引之**——闸机判的就是该镜头真实会落库的引用集合。
- **B-2（结构闸第二半判定恒空转）**：判定式 `t in title` 拿**带前缀**的 KE 标题（`Element_程心`，写口 `normalize_group_title` 幂等补）去比**不带前缀**的镜头标题（`程心…`）⇒ `missing` **恒为空**（与批10 P0-A 是**同一个 canonical 口径病**）。**4444 实证**：全部镜头标题命中数 = **0**。→ 改用 `ops.strip_type_prefix` canonical 比对（**不新造函数**）；回喂文案同步改用**裸名**（内部容器前缀对模型无意义）。
- **B-3（测试桩失真，B-2 一直被藏住的原因）**：`test_structure_integrity_gate.py` 原桩 `title: "程心"`（**无前缀**），而生产落库是 `Element_程心`——**桩与生产形态不一致**，故 B-2 从未被该文件发现。→ 桩改为生产形态，新增两条反向钉（带前缀标题须被认出 / 按文档留空须放行）。**突变验证已做**：回退 B-1 → 2 条钉红；回退 B-2 → 1 条钉红（**非空转测试**）。
- **C-1（改分组工具漏登记动作日志）**：批10 新增 `storyboard_patch_group` 后漏登记 `describe_fc_tool`（FC 轨动作日志**唯一入口**）⇒ 日志回落成兜底句「执行工具 storyboard_patch_group」，而同类工具都是成果语。→ 补分支，输出「**故事板引用已更新（字段）**」——改分组是**增量动作**，不套用 `create_group` 的笼统「故事板已更新」。同批补前端档位契约清单（`timeline.test.ts`：该工具**已声明** `detail_tier=expand`，只是清单没跟；该清单是前端唯一的档位契约面，**漏登记无门禁可拦**）。
- **U-1（`sceneRefs` → `shotRefs` 全链更名，332 处 / 51 文件）**：用户裁决字段名有歧义须改。**命名取 `shotRefs` 而非裸 `refs`**——左栏已有 `scopeRefs`（参考素材）在用、CSS `.ref-*` 亦已占用，同名会**语义串台**。范围含：数据字段（`sceneRefs`→`shotRefs` 落盘/TS、`scene_refs`→`shot_refs` 入参）、函数（`resolve_/merge_/dedup_scene_refs` → `resolve_/merge_/dedup_shot_refs`）、前端组件（`SceneRefsChips`→`ShotRefsChips`，**含文件改名**）、store action（`setSceneRefsLocal`→`setShotRefsLocal`、`syncSceneRefsAfterEdit`→`syncShotRefsAfterEdit`）、CSS 类（`.scene-ref*`→`.shot-ref*`，16 处）、**UI 文案**（标签「场景:」→「**引用:**」+ 两处 title 提示）、生成契约。**刻意不动**（含 scene 但与引用无关）：`collect_failure_scene`、`render_scene`、`linkedSceneId`/`linked_scene_id`、`elementType=scene`、`scene_audio`——已用 dry-run 断言**逐条验证不被误伤**。**存量数据不做兼容**（用户裁决：测试项目将删除重跑）。
- **E-1（自查发现的 fail-open：字符串形态 draft 可绕过阶段媒体闸）**：批12 收尾自查「同类缺陷还有没有别处」时发现——工具侧 `ops.coerce_draft_payload` **明确宽容** draft 传成 JSON 字符串（8888 实证：模型高频这么传），`card_media_gate` 却**只给 `create_group` 做了 str 拆包**，`add_draft` 走 `if not isinstance(draft, dict): return None`（**静默放行**）⇒ **模型把 draft 写成字符串即可绕过阶段媒体闸**（工具照常执行，于是「image 卡进故事板设计阶段」这条被禁的事能做成）。**4444 实证**：该子代理 **14 次**把 draft 传成字符串（`create_group` 侧被正常拦下，故模型确实高频这么传；`add_draft` 侧则裸奔）。→ 抽 `_draft_of` 作**取参唯一入口**（字符串自动 `json.loads` 一次），两入口同引之。回归钉 `test_card_media_gate_string_draft_cannot_bypass` 断言**两入口 × 两形态判定完全一致**；**突变验证已做**（回退字符串宽容 → 该钉红）。
- **否决的假设（如实登记，防后人重走）**：自查曾疑 `prompt_gates.validate_prompt_write` 的 `hard` 恒空（`hard.append` 全库 0 命中）为缺陷——**查证为 2026-09-10「阶段规则去代码化批」的既定裁决**（「字数地板退役…`validate_prompt_write` 不再产生硬错误，只留音色参考软提醒」），且该批明写「**保留 A6 sceneRefs**」（即本批 B-1/B-2 修的正是被保留的那条）。**非缺陷，不动**。
- **为何单 commit**：B 组两处修复与 U-1 更名落在**同一批函数**上（`structure_integrity_gate` / `merge_shot_refs` 既改语义又改名），且更名**原子不可分**——`group.get("shotRefs")` 读旧键**不报错、只静默返回空**，拆两个 commit 会让中间态**静默丢引用**。
- **验证**：`acceptance --quick` **15/15 全绿**；`gen_api_types.py` 重生成一致（契约面 `shotRefs`）；后端全量 **2644 passed / 42 failed**（42 条全为债务 D-22 既有红，**新增失败 0**）；前端 **124 文件 / 1041 用例全绿**；`tsc --noEmit` PASS；残留扫描（`git grep`，活代码 `src/tests/scripts/prompts/docs`）`sceneRefs`/`scene_refs`/`SceneRefsChips`/`scene-ref`/`场景引用` **全 0 处**；模型面确认 `storyboard_create_group` 入参键已为 `shot_refs`；**三处突变验证**（B-1 / B-2 / E-1）回退后回归钉如期变红。

### 2026-09-23 · 批11 草稿 mediaType 唯一推导（事故 4444/P1-5，含对批10 报告的勘误）
- **触发**：用户追问「模型为什么想顺手把角色设定图也画了？故事板设计章节里根本没有出图和写提示词的说明」——追问成立，**复核后发现批10 报告在此处结论错误**。
- **事实（逐条取证 `conv-1790159633-e7d76b40`）**：那 5 次被拒的调用**全部是音频卡**（`group_type='audio'`，`audioType` = `bgm`×3 / `voice`×2），**模型从未申请建过任何图像卡**；该子代理全程建卡类型分布 = `audio` + 空值，**`image` 计数 0**（19 张图卡是子代理 5 在 `write_media_prompt` 阶段建的，属**正确阶段**）。被拒真因 = **只填 `audioType`、未填 `mediaType`**（seq108）；补上 `mediaType='audio'` 后同批全部通过（seq118）。
- **批10 报告错在哪（勘误已写入报告原文）**：拒收文案写「收到 `'image'`」，我直接把那个词读成了模型的意图。但 `image` 是**平台自己的默认值**（`DRAFT_DEFAULT_FIELDS["mediaType"]="image"`）——模型压根没发过这个词。**闸机拿平台默认值当模型意图回喂，我则把这个回喂当成了事实**（同 4444/Q2① 的认知偏差形态：把平台自己产生的东西当成模型的意图）。原文「这是三件事打包后才出现的新撞面」结论**作废**——合并前分阶段委派时子代理同样会只填 `audioType`，**与阶段合并无关**。该报告 §P1-2 已加勘误块、总表已订正、并新增 P1-5 条目。
- **真实缺陷（P1-5）**：`mediaType` 与 `audioType` 是**两个维度**，而平台**明明能从 `audioType` 唯一推导 `mediaType`**（`AUDIO_TYPES` 词表 + `key_element_audio` 契约本就在手），却选择回落 `image` ⇒ 落库「音频语义 + 图像类型」自相矛盾卡，在故事板设计阶段被整单拒收。**代价 = 一次纯浪费的往返（5 个调用全废）。**
- **根因**：`mediaType` 的缺省取值在**三处各写一遍 `or "image"`**（`models.build_draft_dict` 写口 / `fc_gates.card_media_gate` 闸机读口 / `prompt_refs.media_of_draft` 引用读口）——同一口径三份抄写，正是漂移温床。
- **修法（单一事实源，非补丁）**：新增 `models.infer_media_type(data)` 作**唯一推导入口**——① 显式 `mediaType` 优先（含显式 `image`，**本层不越权改写入参**）；② 未给但给了 `audioType` ⇒ `audio`（`AUDIO_TYPE_TO_MEDIA`，含未登记种类的保守推导）；③ 都没有 ⇒ `image`（**历史默认，零行为变化**）。三处消费面全部改引该实现；同批导出 `MEDIA_TYPES` 媒体闭集。**闸机与工厂从此同口径**——这正是本次事故的缺口。
- **schema 契约补齐**：`_DRAFT_FIELDS_HINT` 此前只交代了 `audioType`（模型以为声明了种类就够），现补「**`mediaType` 与 `audioType` 配套**：音频卡两个都标；图像卡 `mediaType=image`；分镜视频卡 `mediaType=video`」。
- **回归钉**：新增 `tests/unit/test_media_type_inference.py`（**21 条**，四组：推导规则本身 / 工厂同口径 / **闸机同口径** / `prompt_refs` 同口径 + 源码级防回潮）。**关键钉**是 `test_gate_and_factory_agree`（断言「闸机放行 ⟺ 工厂落库类型在允许集内」——两处各写一遍才会漂移）与 `test_audio_card_without_media_type_passes`（事故原形直钉）。**突变验证已做**：把闸机回退为 `or "image"` 后 **3 条钉立即变红**（非空转）。
- **既有断言订正**：`test_production_prune.py::test_card_media_gate_rejects_image_card_in_storyboard_design` 原文「mediaType 缺省 → 回落 image，故同样拒收」**漏了 audioType 推导这一支**，改写为「缺省且**无 audioType** → 仍拒」，并新增两条「只填 audioType 必须放行」。
- **验证**：`acceptance --quick` **15/15 全绿**；`gen_api_types --check` PASS；后端全量 `2639 passed / 42 failed`（42 条全为债务 D-22 既有红，**新增失败 0**）；端到端复现（真实 `invoke_tool` 链路）：只填 `audioType` 的卡 `success=True` 且落库 `mediaType='audio'`，而真图卡仍被拒。

### 2026-09-23 · UI 目测累积项全部闭合（用户确认「UI 我目测过了，没问题了」）
- **背景**：本仓历年 UI 改动按宪法 §3.1「构建后须经用户目测确认」形成的**待目测累积清单**，自 09-21 一路挂到 09-23 共三批 12 项，均已构建通过但未获用户目测回执。用户本轮目测后明确确认通过，三批一次闭合。
- **闭合范围（逐项）**：
  - **09-21 批B（5555/Q4，4 条）**：暂停卡问句 = 模型实际提的问题（不再回落「本阶段已完成」系统模板）；`header` 短标题显示在问句上方；`detail` 说明显示在问句下方且**不进可选项列表**；旧历史消息（无这两字段）不出现空白行。
  - **09-21 批F（4444/Q2③+Q3，4 条）**：一次问 N 问时**每问各成一块**（各带问句/标题/说明/选项）、底部单一「发送」；多选问题渲染为**复选框**、发送时各占一行；已回应暂停卡回看时选中项**同时显示标题与详细描述**（Q3② 的显示修复）；旧消息（无 `pauseQuestions`）逐字不变。
  - **09-21 批G（4444/Q4，2 条）**：子代理执行中主 Feed 的 actor 卡内可展开看到**子代理思考**（不必等做完）；子代理思考**不进父代理思考面板**（不串台）。
  - **09-21 批K/L（2 条）**：问答回执迁入用户气泡（一问一答逐问呈现，`pauseQaFor` 按问题 id 配对）+ 多问题分页作答与提问回执卡（对齐 dsh `QuestionFlow` / `AskQuestionRow`）。
  - **09-22 批O 批4/批7（2 项）**：actor 卡运行中自动展开 + 耗时角标 + 记录态实时增量；删红框卡（`StageCard` 整卡退场）+ 无选项暂停题面在 `ConfirmActions` 补位。
- **文档收口**：`docs/4444事故修复方案-20260921.md` §八、`docs/5555事故修复方案-20260921.md` §八 各加「已闭合」状态头；**原目测要点清单逐字保留**（作为「当时要求目测什么」的证据，不删不改）。
- **边界（如实登记）**：本次为**用户目测确认**，非机械验证——宪法 §3.1 的口径本就是「UI 变更须构建后经用户目测」，机械测试全绿 ≠ 交付，故本条的完成判据即用户回执本身。**本仓无 e2e 视觉回归基线**，目测仍是一次性人工确认，后续 UI 改动仍须各自过目测，不因本条闭合而免疫。
- **验证**：`npm run build` 通过（首屏 380.23 kB < 400 kB 上限）；`acceptance.py --quick` 全绿；后端全量 `2618 passed / 42 failed`（42 条全为债务 D-22 既有红，与代码无关）。

### 2026-09-23 · 批10 4444 实跑复盘根治（4 项根因，用户裁决「全部修复，不能有尾巴、不能打补丁」）
- **背景**：用户要求查看 4444 项目运行过程的问题。**4444 = 当时活跃项目 `proj-1790159421-bfd25491`**（跑于 09-23 18:30–18:49，5 轮实跑，非 09-21 那次同名事故）。取证报告 = `reports/4444-运行问题取证-20260923.md`（另附两份子查报告）。**本次实跑整体成功**：无 504、无子代理死亡、5 次委派全部收尾，09-21 批E/F/G 三条主修复**全部经实跑验证有效**（`data/sse_capture/` 子代理流式文件 45+ 个 vs 事故时 0；模型一次问 5 问、用户逐问答满；任务书无内部机制词）。查出的问题**均为既有批未覆盖项**，非翻案。
- **用户裁决**：「一次派活派了三件事」（Q5 三阶段合并 = 09-22 批O 批6）**先不动、留到后面讨论**；**其余暴露出来的问题全部修复，不能有尾巴、不能打补丁**。故本批一律取**根因修复**，不加补丁式兜底。
- **P0-A（引用解析链整条事实性死亡，本批最重）**：`resolve_scene_refs`/`resolve_scene_audio_refs` 是**逐字精确比对**（`id != ref and title != ref`），而落盘组标题带容器前缀（`Element_程心`，写口 `normalize_group_title` 幂等补）、`sceneRefs` 存**裸名**（`程心`）⇒ **恒不命中**。实跑复算：4444 22 镜 90 条 sceneRefs → `image_refs` **0**、`audio_refs` **0**；改 canonical 键复算 → **90/90 命中**。**性质**：`dedup_scene_refs` docstring 本就写着「裸名与 `Element_` 前缀算同一引用（去重键 = `strip_type_prefix`）」——**写口用 canonical、读口用逐字**，是口径漂移；`core/prompt_refs.py` 批3 R3 **已修过同一失配**，判词逐字「平台在别处早就做了裸名归一，**唯独本引用链漏了，属口径漂移而非设计**」。→ 新增 `canonical_ref_key` / `build_ref_index` / `find_ref_group`（读口唯一入口），**四处**比对式全部收敛到它：`resolve_scene_refs`、`resolve_scene_audio_refs`、`web/routes/generate_image.py`、`web/multimodal_builder.py`（本次事故正是四处各抄一遍且全部逐字比对）。同批 `resolve_scene_audio_refs` 补 `audioType=='voice'` **优先**（非硬判，存量回落任意音源）。
- **P0-B（下发 schema 悬空 `$ref`，新工具自伤）**：`tools/manager._full_schemas` 只取 `model_json_schema()` 的 `properties`+`required`，**丢弃 `$defs`**；pydantic 对嵌套 BaseModel（`List[TodoItem]`）产出 `items: {"$ref": "#/$defs/TodoItem"}` ⇒ 悬空，**条目字段名一个字节都到不了模型**。实跑取证：`todo_write` 被调 11 次、**失败 7 次**，模型原地盲猜键名 `title`→`text`→`label`→`item` **四种全错**（而状态值每次都填对中文，证明它读懂了描述、只是不知道键叫什么）。全量体检 25 个已注册工具：**只有 `todo_write` 中招**（本仓第一个、也是唯一一个用嵌套 BaseModel 描述条目结构的工具；其余工具子字段写在 description 文本里，天然免疫）。**为何测试全绿**：`test_todo_write.py` 全走 `invoke_tool(name, {...})` **直传 dict**，验的是 pydantic 执行链路（`$defs` 在 pydantic 内部完好），缺陷在**下发链路**——两条路各自都对，交汇处漏了。→ 新增 `inline_json_schema_refs`：`$ref` **就地内联展开**（不补发 `$defs`——本平台经中转调用，下游是否解析 `$ref` **不可控也不可观测**，内联后 schema 自足）；**fail-loud**（解析不到定义即抛错，不回落残缺 schema——悬空引用正是本次事故形态，静默降级等于把同一个坑再挖一遍）；空 `$defs` + 悬空 `$ref` **也走解析**（不能"看起来没事"就放过）。**同批封堵内联引入的新泄漏面**：pydantic 把**类 docstring** 映射成被引用模型的 `description`，内联首次会让它进入模型上下文（`TodoItem` docstring 写着「对齐 dsh」「pydantic extra=forbid」「:83-84 注释逐字」等**实现说明**）——故内联时摘掉被引用模型**根部**的 `description`/`title`，字段级 description（有意写给模型）原样保留。
- **P1-1（无「改分组」工具 ⇒ 删光重建）**：`ops.patch_group` 与 `PATCH /storyboard/groups/{id}`（docstring 自称「用户直接编辑，不经 Planner，<10ms」）**都存在，却从未接线成模型工具**——模型改一个分组的 `sceneRefs` 只能「删除整组 + 重建整组」。实跑取证：子代理为给 9 个 shot 补引用，**删光 22 个组再重建 22 个**（23 删 + 23 建，分 8 轮），耗时 **261.6s**（本次最贵委派），且重建产生**全新 group id**（子代理自己警告「旧 id 已删除，后续阶段勿沿用」；中途任一批失败即留下残缺故事板）。与 09-23 批2 补 `storyboard_delete_draft` 是**同一类缺口**（既有能力未接线）。→ 新增 `storyboard_patch_group`（`PatchGroupInput` + 工具 + 注册，10→11），**白名单外字段原子拒收**、**空 patch 拒收**（防假成功）、not found 三要素、`title` 经 `normalize_group_title` 归一。**不做三源合并**（`[元素名]` 令牌 ∪ 裸名提及是**建组**期语义；patch 重做会让「删引用」不可能——desc 里的裸名会把它加回来）。连带清单同批补齐：`_STAGE_TOOLS`/`MAIN_AGENT_DENY`（**必须同批**，否则 subagent import 期 fail-loud raise）、`stage_probes._PLATFORM_TOOL_STAGE`、`planner._STUDIO_STATE_TOOLS`、`action_descriptions.describe_action`（FC 轨唯一入口，此前表内只有文本轨死文案 `update_group/patch_group`）、`gen_api_types.py` 重生成。
- **P1-3（「已连续失败 N 次」骂错对象）**：计数器按**工具名**累计，而提示语文案是「**同参**重试大概率仍失败」。实跑取证：同批 5 个 shot（内容各不相同）各自失败，从第 2 个起每个都收到「该工具已连续失败 2 次」——对第 5 个纯属冤枉（它才第一次上场，且它的问题与别人不同）。→ 计数键改为**入参指纹**（`_call_fingerprint`，与既有 `_gate_repeat` 的「kind+签名」计数同构；入参不可 JSON 化时回落工具名，**记账不得打断执行路径**），另立 `_tool_fail_totals` 供时间线「累计失败 N 次」展示（Q22 既有断言语义不变）。
- **P1-4（音色卡归属）**：Skill 明文「角色的声音特征…单独登记为 `key_element_audio`，**与角色元素绑定**」，契约 = 挂在角色**自己的 keyElement 组内**（`CATEGORY_MEDIA_MATRIX` keyElement 行「可放音频」、前端 `isVoiceCard`、`CHANGELOG` 09-21 批4 用户裁决、仓库 `scripts/migrate_storyboard_existing.py` 同口径）。实跑取证：4444 建了 6 张 voice 卡**全落 `audioItems`**（独立 `Audio_voice-*` 组），**KE 下 audio 卡 = 0**；且 `prompt_gates.has_voice_reference` **只扫 `audioItems`**（与契约**恰好相反**，契约一旦被遵守该软提醒即静默失效）。→ ①`storyboard_tools` 的 draft 字段契约补**归属句**（模型有 `audioType`、也知道它是音色卡，**却不知道挂进哪个类目**——归属这一级此前缺失）；②`has_voice_reference` 探测源补齐 `keyElements`；③`resolve_scene_audio_refs` voice 优先（见 P0-A）。**三次实跑同向失败**（2222 KE 里落的是 BGM、3333 零 audio 卡、4444 voice 全落 audioItems）⇒ 契约空缺稳定复现。**不动 `data/skills`**（冻结#16）。
- **P2-1（确认卡不列被确认对象）**：实跑取证 `chatMessages[10]` 问「19 张 keyElement 设定图提示词草案是否确认生成？」，卡面**只有一句总数、19 张一张未列**，`detail` 槽**完全没用**——用户被要求批准一堆自己看不到的东西。→ `WorkflowPauseInput.detail` 补契约：**确认批次产出时须逐条列出被确认对象**（或按类目分组计数并点名），只给总数不算交代。
- **P2-2（子代理替用户推翻已定目标）**：实跑取证 `chatMessages[8]` 的 `duration_fix` 问题——「当前 22 镜合计约 257s，未达 5 分钟目标，如何处理？」，其中一选项「接受当前节奏（约 4 分半）」**等于让用户推翻自己 20 分钟前的决定**（用户在 `chatMessages[4]` 明确答过「5 分钟以上」）；且该判断是**子代理自己做出**后塞进 `unfinished` 抛回的。→ `DELEGATION_CONTEXT` 补：**执行既定约束、不重新决策**——规格与用户已确认参数是既定前提，冲突时如实上报**事实与缺口**，不自行发明取舍题、不在 `unfinished` 里提供「放宽既定目标」这类选项。
- **验证**：`--quick` **全绿（15/15 含 tsc）**；后端全量 `2618 passed / 42 failed`，**逐条 diff：新增失败 0 条**（42 条全为既有红 = 债务 D-22 的 `NO_PROXY` 含 `[::1]` 致 httpx 构造抛 `InvalidURL`，命中 `test_openai_compat` 27 / `test_reasoning_passthrough` 7 / `test_adapter_stream_protocol` 4 / `test_cached_tokens_telemetry` 3，+ `test_progressive_disclosure_relocation` 1；清空代理变量复跑结果一致，**与代码无关**）；**全量前端 124 文件 / 1041 用例全绿**；`acceptance.py` 全量 **19/20 PASS**（唯一 FAIL = pytest 即上述 D-22 既有红），GATES 15 项 + RATCHETS 2 项全 PASS。
- **新增回归钉**：`tests/unit/test_batch10_4444_root_fixes.py`（**28 条**，四组）。**关键**：P0-B 的钉子必须打在**下发层**（`_full_schemas` 输出），因为既有 `test_todo_write.py` 走 `invoke_tool` 直传 dict **永远抓不到这一类**；P0-A 的钉子补上「KE 内音色卡 + **裸名** sceneRefs → reference_audio」端到端——**既有两用例恰好只测带前缀写法**（`test_video_multimodal.py` 用 `Element_侦探`、`test_888_fixes.py` 的标题恰为无前缀裸名），**才让这个 bug 绿了整整一个批次**。
- **连带订正（既有断言随结构变更更新，非删除）**：`test_subagent_stage.py`（2 处工具集）、`test_production_prune.py`（1 处工具集）、`test_gate_canaries.py`（重生成产物后自愈）。

### 2026-09-22 · 批O 用户五项体验修复（1111 项目复盘：Q1-Q5，含两项对齐 dsh）
- **背景**：用户复盘 1111 项目（`proj-1790073823-519d1214` / `conv-1790074054-f0e43ab0`）提五项改动 + 一句「Q3/Q4 都看看 dsh 有没有解决方案，如果有就抄」。先出方案汇报、用户逐项拍板（**否掉两项**：Q3 加长度门禁、Q2 存量线程兼容），再动手。分七批、批间独立验收。
- **批1（Q2 子代理名称刷新即丢）**：查得**两处标签不同源**——干活时 actor 卡显示 `STAGE_LABELS[stage]`（如「分镜」，来自 SSE meta），而落地 `scope.label` 存的是**任务文本前 40 字**；刷新后内存清空、只能读 `scope.label`，于是名字退化成任务书（「目标：按所选 Skill 的 storyboard_shots 章节规范，将剧…」）。→ `planner._launch_subagent` 带 stage 时落地**阶段展示名**（与 SSE meta 同一取值），通用委派才回落任务摘要。任务书原文不丢：子级任务已作为隐藏线程首条 `user/message` 落流。
- **批2（Q4.4 打卡后仍被逼着多干一轮，**新查出的硬缺陷**）**：子代理 `structured_output` 打卡成功后仍空转两轮——实跑时间线 `seq=88` 打卡 → `seq=93` 又说 1171 字 → `seq=96` 又说 789 字，白烧 9s 且产出两份重复汇报。根因：K6 批（09-16）只删了 fakestop 的 `subagent_depth` 排除条件、**「子代理收尾改由打卡判定」那半句从未接线**，而代码与注释**说法相反**（`RoundEndContext.subagent_depth` 与 `agent_loop` 两处注释仍称「>0 时不触发续跑」= P1 双份事实源）。→ 加 **打卡感知**（`structured_captured` 经 `fc_extra` → `RoundEndContext`，条件补 `and not ctx.structured_captured`）：已打卡 = 已按契约声明完工，不再判假停；**没打卡的子代理照旧受续跑约束**（不静默欠交付）。两处过期注释同批订正。
- **批3（Q4.3 子代理回摘要近义重复）**：`agent_loop` 把子代理**每一步**的可见正文按序拼接（`f"{result.text}\n\n{visible}"`），实跑回摘要 **2937 字**含 4 段近义汇报。→ 抄 dsh `assistant-output.ts`「select the **last non-empty assistant message**」：子代理（`subagent_depth>0`）只取末条非空正文，主代理拼接行为不动。**实测 2937 → 789 字（27%）**，单一实现 `round_end_policies.accumulate_visible`（FC 轨与轮末策略共用一个口径，防两腿各写一遍）。
- **批4（Q4.1+Q4.2 思考不流式 / 无时间标记）**：四件事叠加——① actor 卡思考**默认折叠**（子代理思考其实一直在逐字推流，被折叠盖住，观感等同「没有流式」；主对话框 `AgentTimeline` 是流式中自动展开，**两边口径不一致**）；② 中间面板记录投影 `project_readable_record` **整体忽略 `assistant/partial`**（实跑 40 条步内增量全丢，只认完整 `assistant/message`）；③ 前端轮询 4s + 后端 5s 落一条增量 = 两级延迟叠加；④ 思考块无任何耗时。→ ①actor 卡运行中自动展开；②投影补**步内增量腿**（同一 step 的完整消息到达即让位 = dsh 瞬态条目被结算原子替换，未结算步落 `streaming=true` 实时条目）；③轮询 4000→1500ms；④新增 `elapsed_ms`（= 本条时刻 − 上一**已结算**事件时刻；**踩坑**：第一版按「上一条事件」推进锚点，紧邻完整消息的最后一条 partial 与之同刻，13 步耗时全被压成 `+0.0s`，改锚点后恢复 2.4s/65.8s/9.4s…）与 actor 卡走秒角标。`sameRecordMsg` 补比 `elapsed_ms/streaming`（漏比则稳定化复用旧引用、Solid 不重渲染，实时增量永远长不出来）。dsh 侧本就是真事件流（`assistant/live-chunk` + animation-frame 合并），本层受现有轮询架构约束取折中。
- **批5（Q3 任务书太长太杂，**第三轮 prose 修复无效后改结构**）**：实跑三张任务书 186/188/229 字，含「已登记的 9 个 keyElement 分组（5 角色/3 场景/1 道具）…制片规格（16:9、约 5 分钟…）请自行读取」——**全是子代理一眼可见的项目状态**（末句还自相矛盾：刚抄完又说「请自行读取」）。批2/批C/批E 三轮都在加「不要复述」，均未治净 → **把劝告下降成结构**：①`RunSubagentInput.task` 由**必填**降为**选填补充**（此前必填 ⇒ 模型必须填坑 ⇒ 复述是结构必然、非违纪）——带 stage 且 task 空时目标由平台生成（`build_subagent_task`：执行所选 Skill 的「X」章节）；②`DELEGATION_CONTEXT` 删「完成后用以下格式汇报：已创建/已修改/已移除/未完成」四行——它与 `structured_output` 打卡四槽（created/modified/removed/unfinished）是**同一契约的第二份事实源**（P1），实跑证明子代理既打卡又在正文复述一遍（图5 重复汇报的来源之一）；平台文本 **786 → 393 字**（对照 dsh 给子代理的平台文本仅 ~348 字、且不做汇报格式要求）。**用户裁决：不加长度门禁**（prose 之外不再新增闸机）。
- **批6（Q5 三阶段派给同一个子代理）**：故事板设计三件事（关键元素+分镜+音频）此前分三趟派人（三张卡、三次等待），而**平台自己的建模早就是一件事**——`stage_probes.CANONICAL_STAGES` 把三者合成一个 `structure` 节点、Skill 的 `<planner>` 也是**一个步骤**管三件事、实跑里子代理本就 ke→shots→audio 连着做完。→ 委派面新增合并阶段 `storyboard_design`（展示名「故事板设计」），`CAPABILITY_TOOL_STAGES` 加 `("storyboard_ke","storyboard_shot","storyboard_audio")`（`section_for` 天生支持多章节拼接，注入侧零改动；实测三章 1784 字一次注入）；`_STAGE_TOOLS` = 三原子集并集；`STAGE_CARD_MEDIA` 键改名且允许集拓为 `{audio, video}`（audio ← 音色卡；video ← 分镜卡，实跑 26 次 `create_group` 全 `shot+video`；**image 仍拒**——用户 09-21 裁决不变：图像卡与提示词归 `write_media_prompt`）。**三个旧名逐字保留在能力面**（还喂着 `available_tools`/`scan_skills` lint/音频闸/`stage_probes`），只从**委派面**退役（模型没有猜错空间，2222/Q3b 教训）。
- **批7（Q1 删红框卡）**：用户截图1 红框卡 = `StageCard`（`阶段完成 · 已执行 2 个操作 · 已回应` + `画幅比例选哪种?`）。根因：**同一句题面被画了两遍**——`TurnLedgerCard` 按 `msg().confirm` 挂 StageCard 画一次，`ConfirmActions` 的 `.confirm-wizard-question` 又画一次；而 StageCard 的判重**只在「active 且带选项」时让位**，answered/expired 一律照画（红框那张正是 answered 态）。→ **整卡删除**（组件+测试+全族 CSS+`--color-stage*` 死 token 一并退场），并**补一处缺口**：无选项暂停（只有「确认，继续」）的题面**只**在 StageCard 里，删卡会丢字 → 在 `ConfirmActions` 该分支补 `.confirm-wizard-question` 行（已加钉）。回看不受损：批K 已把「问题→你的选择」搬进**用户气泡**（`AskQuestionReceipt`/`PauseQaBlock`）。
- **验证**：`--quick` 全绿；**全量前端 1026 用例 / 123 文件全绿**；后端全量 `2533 passed / 42 failed`，对照 `git stash` 后的 HEAD 基线 `2512 passed / 43 failed` —— **逐条 diff 失败清单：新增失败 0 条**（42 条全为既有红：41 条 = 债务 D-22 的 `NO_PROXY` 含 `[::1]` 致 httpx 构造抛 `InvalidURL`，命中 `test_openai_compat`/`test_adapter_stream_protocol`/`test_cached_tokens_telemetry`/`test_reasoning_passthrough` 四个网络文件；1 条 = `test_progressive_disclosure_relocation`，两者均与本批无关），另有 1 条 `test_fakestop_reasoning_passback` 由红转绿（随工作区既有的 `agent_loop` reasoning 回传改动，非本批）。
  **UI 改动须构建后用户目测确认（宪法 §3.1）**：批4（actor 卡自动展开/耗时角标/记录态实时增量）与批7（删卡+题面补位）属 UI 面，测试全绿 ≠ 交付。


- **背景（全库扫描取证，跨全部修复批）**：扫描 `workspace/sessions/*/conv-main.jsonl` 得 **46/46 个项目的主代理开场亲读剧本**（`read_uploaded_doc`，每项目恰 1 次）——从 09-09 直到 09-22 11:23 最新一次，**跨过 09-18「分析不进状态快照」、09-19「主代理纯编排批」、09-20「附件正文预览退役批」、09-21「批M」全部修复批**；其中 8888（`proj-1789839470`）跑于 09-20 01:51，即「附件正文预览退役批」当天，仍照样亲读。
- **动作顺序全库一致**：最近 8 个项目均为「先亲读剧本（seq 6-8）→ 再 `workflow_pause` 提问（seq 8-14）→ 最后才 `run_subagent` 委派（seq 19-25）」——**该干活的子代理排在最后**，正是「编排角色把别的阶段的事提前做了」的形态。6666/8888 开场暂停均问了 4 项（含**剧本形态**），而剧本形态本属 `script_analyze` 章节职责。
- **根因（平台自伤，非 Skill）**：`prompts/planner/protocol.md` L4 渐进式披露总纲原文「…全文**一律**经 read_* 工具按需读取…**不要声称看不到相应内容**」——
  - 「一律」是**催读语气**，与 flova L905/L907 的判据相反；「不要声称看不到」是**说教**（P3 状态即数据），09-20 附件预览退役批已在 `web/attachments.py` 删除同款句，但 **`protocol.md` 这一处未同批清除**（该句 09-04 `ebec655` 物理重组时进来）；
  - 模型侧四条合力构成抢读最优解：状态列出素材 ✅ + 平台说"按需读取" ✅ + `read_uploaded_doc` 在手（`MAIN_AGENT_DENY` 只锁 5 个写工具，读工具不锁）✅ + Skill 要求"识别剧本类型"（不识别就无法推进）✅。
- **flova 对照（转录十 L892-907）**：用户原问「是怎么保证有能力读、而又不读的？是系统内部设定么？」flova 答：「主要依赖系统的**上下文注入与文档访问边界**…**保留了按需读取剧本的能力**…主会话**只有在当前任务确实需要剧本原文时**，才应主动读取或定向传递它」；L907 明写「**这不是说系统能阻止我发起一次读取请求**」。
- **改动（只改第 ② 层措辞，不锁工具）**：`protocol.md` L4 重写为「…正文默认不在场——读取本身没有限制，但**按任务分工决定由谁读**：各专业阶段的原文分析归该阶段执行环节，**你只在当前任务确实需要该原文核对时才读取**…」。
  - 删「**一律**」催读语气；删「**不要声称看不到相应内容**」说教（用户明示删除）；补 flova 两句判据；**保留**「目录与清单注入」契约本身。
  - **不写"不许读"** → 不踩 2026-09-20 双删批（该批删的是「不跨阶段预收」绝对禁令）；**不锁工具** → 不翻案 09-20「能读而又不读」，且与 flova L907「系统不能阻止读取请求」一致。
- **边界**：**仅改平台文件**——`data/skills` 零改动（Skill 是既有输入、非缺陷源，冻结#16）；执行模式档位零改动；无机械闸新增（2026-09-08 裁决）；无 Python 源码改动。
- **回归**：`test_protocol_role_and_spec_boundary.py` 新增 `test_disclosure_clause_routes_reading_by_task_role`（钉两句 flova 判据在场 + 两侧防回潮：「一律」与「不要声称看不到」不得回归）+ 新增 `_disclosure_clause()` 取读助手；既有 27 条**零翻案**（定点 38 passed，含 `test_prompt_relocation_batch3.py` 10 条）。
- **验证**：`acceptance.py --quick` 全绿（GATES 13 + tsc，exit 0）。
- **待实测**：措辞收益无法用代码证明——需实跑同类开场，观察主代理是否仍亲读剧本。**诚实保留**：flova 材料自身在此有不一致（L896 称"不是靠自觉"、L907 给出的机制却只有"默认不注入 + 规范引导"，而规范引导即是自觉）；本项目与 flova 的差异**只在措辞**（flova「只有在任务确实需要时才读」vs 本项目「一律按需读取」），故本批按可对齐的那一层执行，不臆造未找到的"系统机制"。

### 2026-09-21 · 批M iron_rules 阶段锚点换锚：「当前阶段」→「该信息所属的产出阶段」（6666 取证）
- **背景（6666 取证，proj-1790004483-ceefb1a0）**：`iron_rules_header.md` L3【冲突与缺信息处置】原文「信息缺失且**当前阶段** Skill/流程要求询问 → 先问再做」中的「当前阶段」**在平台侧没有任何客观指称**——它既不是 Skill 的章节字段，也不随状态注入，全靠模型自估。
- **实跑失效链（有原文）**：模型 seq 28/39 思考**逐字照抄该句**（"信息缺失且当前阶段 Skill 要求询问 → 先问再做"）→ 自判「当前阶段」= 启动阶段（Skill `<planner>` 里唯一有明确时序的正是「启动协议…按顺序确认后再推进」）→ seq 13 `workflow_pause` 第 2 问把 Skill **明文归分析阶段**的「剧本形态分类」提前问到开场（"这份《三体简短版》是散文体叙事（非标准分镜脚本），如何推进？"）→ 主代理判「散文体」、随后分析子代理独立判「C 类 — 半结构化剧本」，**两结论打架**。
- **改法 = 指称换锚（只换词、不新增条款）**：锚点从模型自估的**时刻**换到 Skill 明写的**信息归属**——Skill L34「若用户上传的是散文体小说…**在分析阶段识别**并告知用户」是白纸黑字的可判定依据；换词后模型不必再自估"现在是哪个阶段"，只需判"这个结论由哪个阶段产出"。
  - **净变化**：`当前阶段` → `该信息所属的产出阶段`（+5 字，**零新增句子、零新增条款**）。
- **边界（防翻案）**：本批**不夹带** flova 转录给出的「主代理以当前项目状态验证条件」那句判据——其自然中文写法必然长成"不在更早阶段索取"，**语义上正是 2026-09-20 双删批删掉的「不跨阶段预收」**（flova 口径本身也含"Skill 应把沟通规则拆成硬性前提/可选提示两类"，而该拆法落在 `data/skills`，属冻结#16 不可改）。用户明示本批**只换词**。
- **改动**：`prompts/shared/iron_rules_header.md` L3（唯一定义层）。**`spec_rules.py` 无需同步**——项目内《执行铁律.md》模板只留「见平台注入的头部声明」指针、不复述条款正文（P1 单源，2026-09-20 K8 批定的口径），存量项目文档亦无需迁移。
- **回归**：`test_prompt_relocation_batch3.py` 新增 `test_iron_rules_header_stage_anchor_is_production_phase`（钉换锚形态 + 两侧防回潮：不得退回无指称「当前阶段」、不得借换词回潮双删批禁令、核心条款不得误删）；既有 `test_iron_rules_header_drops_cross_stage_precollect` **零翻案**（其三条断言逐字未动）。
- **验证**：定点 5 文件 **46 passed**；`acceptance.py --quick` 全绿（GATES 13 + tsc，exit 0）。
- **红线**：`data/skills` 零改动（Skill 是既有输入、非缺陷源）；**执行模式档位零改动**（用户明示该轴为正在进行的实验变量）；无机械闸新增（2026-09-08「不加机械闸」维持）；既无 Python 源码改动、无前端改动。
- **已知无关失败**：全量 pytest 41 failed 全在 httpx 适配器三文件（`InvalidURL: Invalid port: ':1]'`，本机 `no_proxy` 含 `[::1]` + xdist 并行所致；**已用 `git stash` 于干净 HEAD 基线复现同样失败**）。本批所有验收均以 `Remove-Item Env:no_proxy` 后的干净环境执行。
- **待实测**：换词收益无法用代码证明（判据仍归模型）——需在 `ai_decide` 档重跑同类开场，观察「剧本形态」是否仍被列进启动暂停。

### 2026-09-21 · 批L 多问题分页作答 + 提问回执卡（A 批 + R 批，对齐 dsh QuestionFlow / AskQuestionRow）
- **背景**：批F 给暂停卡补了 `questions[]`（一次问 N 问），但**作答面仍是「一屏铺全部问题」**——4444/8888 实证模型一次问 4-5 维时，用户要在一屏里跨维度勾选、无进度感、漏答只能靠发送时统一拒绝。对齐 dsh `ui-user-questions` 的 `QuestionComposer::QuestionFlow`（一页一题 + pager + 跳过）与 `AskQuestionRow`（提问回执折叠卡）。
- **A 批 · 分页作答（新增 `PauseQuestionFlow.tsx`）**：
  - 形态 = 一页一题（header + 问句 + detail + 选项 + 自定义输入）；底部 pager「‹ i / N ›」+「跳过」+ 主按钮（非末题=「下一题」、末题=「发送」）。
  - **单选点选自动翻页**（非末题；末题留在末页）；多选渲染为复选框、**不自动翻页**；草稿（各题所选/自定义/跳过）**随页切换保留**。
  - **发送时整组校验**：缺项 → 跳回缺题 + 提示（不发送）；**跳过 = 显式完成**（登记 `skipped`，发送时记**空答案** `{id, selected: []}`，回执据此显示「未作答」）。
  - 提交仍组装**两份面**：逐行文本（旧消费链 `value`，零改动）+ 问题级 `answers`（批J 口径），与既有回到链路一致。
  - `ConfirmActions` 多问分支由内联块改为挂载 `<PauseQuestionFlow>`；单问/向导分支**逐字不动**（`hasQuestions()` 非空才走分页）。
- **R 批 · 提问回执卡（新增 `AskQuestionReceipt.tsx` + `PauseQaBlock` 排版改版）**：
  - 回执从「裸问答对」升级为**折叠卡**：头部「提问 · N/M 已回答」+ 箭头（默认展开，点头部折叠）。
  - `PauseQaBlock` 排版对齐 dsh `AskQuestionCard` 的**纵向两层**：上行**完整问句**（`question` 优先，旧数据回落 `header`），下行「你的选择」——取代旧的行内「header → 答案」横向结构。
  - **「查看说明」= dsh `row.inspect` 的轻量等价物**：回执主体只显示 label（dsh 口径），**所选选项的 description** 经开关展开；`PauseQaPair.notes`（label → description）由 `turn-groups.pairQuestions` 一次性备齐，**无说明数据时按钮不出现**。
  - **单点呈现（R 批用户裁决）**：回执存在时**隐藏用户气泡内的拼接正文**——那串逐行答案在回执里 100% 复现，不再重复占位。
- **配对单点抽取**：`turn-groups.pauseQaFor` 内联配对逻辑抽为 `pairQuestions`（纯函数，同文件导出面不变），供 `pauseQaFor` 与回执渲染共用；**按问题 id 配对**语义逐字保留（同名选项不互串、跳答显式标注、旧消息逐行回落）。
- **实时路径补齐（`submit-message.ts`）**：暂停回应此前**只走后端落盘**（刷新后才有 `pauseAnswered*`）→ 用户气泡回执**当场失配**、只显示拼接文本。本批在本地同点回填 `pauseAnsweredId/Value/Answers`（与 `conversation_ops` 落盘同形），**实时即可配对**。
- **回归**：`ConfirmActions-multi-question.test.tsx` 重写为 12 条分页面（①一页一题 ②单选自动翻页 ③草稿随页保留 ④多选不翻页 ⑤跳过即发送 ⑥整组校验跳回缺题 ⑦双面提交 ⑧未答禁用主按钮 ⑨header/detail 随页 ⑩无选项兜底 ⑪⑫旧消息零变化）；`turn-groups.test.ts` 扩 3 条（header/question 双字段保留 / notes 提取 / 无 description 省略）；`ChatMessageItem-extra.test.tsx` 扩折叠卡 + 查看说明 + 单点呈现断言。
- **验证**：前端定点 vitest **5 files / 83 passed**；`acceptance.py --quick` 全绿（GATES 13 + tsc，exit 0）；全量 vitest **PASS**、tsc PASS、eslint PASS、cov/fe_cov 双棘轮 PASS；`npm run build` 通过。**已知无关失败**：全量 pytest 41 failed 全在 `test_openai_compat.py` / `test_reasoning_passthrough.py` / `test_adapter_stream_protocol.py`（httpx `InvalidURL: Invalid port: ':1]'`，源于本机 `no_proxy` 含 `[::1]` + xdist 并行；**git stash 后于干净 HEAD 基线复现同样失败**，与本次改动无关，属环境预存问题）。
- **UI 变更**：按宪法 §3.1 须经用户目测——本次即用户点名要求的改动本身。
- **红线**：`data/skills` 零改动；无 Python 源码改动；旧单问/向导分支与 `value` 扁平回携**逐字保持**。

### 2026-09-21 · 批K 问答回执迁入用户气泡：一问一答逐问呈现（用户要求）
- **用户原话**：「要接上。图1这个位置的可以删了。直接在我回复的气泡那边就行，也就是图2的位置。」
- **背景（承接批J 的未闭合项）**：批J 把问题级回答（`answers[]`）**存进了后端**，但**回看界面没读它**——`pauseAnsweredAnswers` 当时只有写入方、**零读取方**，所以肉眼看不到任何变化。本批把最后一步接上，并按要求把回执**从 agent 卡搬到用户气泡**。
- **删除的那块（用户截图图1）**：agent 卡下的「已回应选项对勾区」（`AnsweredOptions`）。**移除理由**：该区把整排选项重画后用**文字**匹配打勾（`turn-groups.answeredValueFor` 按值相等），多问题时全部混在一起、**同名选项会互相串**（匹配只认文字、不认属于第几问）。注：组件与 `answered-options` 样式**保留**（其他消费面/回归仍引用），只是 `TurnLedgerCard` 不再挂载。
- **新形态（用户截图图2 的位置）**：用户自己的气泡内逐问一行「问题 → 你的选择」，跳过的问显示「**未作答**」，自定义文本走独立样式。
  - `turn-groups.pauseQaFor`（纯函数）：把 agent 的 `pauseQuestions` × 用户的 `pauseAnsweredAnswers` **按问题 id 配对**，**彻底摆脱「第几行 = 第几问」的位置约定**——选项文字含换行、某问用自定义文本作答、某问跳答时都不会错位；旧消息（无结构化回答）回落 `pauseAnsweredValue` 逐行按序补齐，保证历史可读。
  - `message-affordances` 增 `pauseQa` 派生（派生层唯一判定处，渲染组件契约不变）；新增 `PauseQaBlock.tsx`；`UserBubble` 两个分支（纯文本/富文本）都挂。
- **受影响测试（4 处，"钉死旧块"，改写非删除）**：`TurnLedgerCard.test.tsx` 3 条改为钉「本卡不再挂 `answered-options`」+ 渲染链由三件变两件；`ChatMessageItem-extra.test.tsx` 1 条改为钉「agent 卡不挂对勾区」并**新增**一条钉用户气泡的问答渲染；两处 affordance 桩补 `pauseQa: []`。
- **新增防回潮钉** = `turn-groups.test.ts` 扩 **9 条**（26 条全绿）：按 id 配对 / **同名选项不互相串**（旧文字匹配的直接病根）/ 跳答显示未作答 / 自定义文本走 custom 槽 / 多选保留全部勾选 / 旧消息逐行回落 / 非问答消息与脏数据不生成无主块 / header 优先显示。
- **验证**：`tests/unit` + `tests/integration` **2547 passed / 0 failed**；vitest **124 files / 1023 passed**；**acceptance 全量 18/18 PASS**；`npm run build` 通过（首屏 379.46 kB）；`data/skills` 零 diff。
- **UI 变更**：按宪法 §3.1 须经用户目测——本次即用户点名要求的改动本身。

### 2026-09-21 · 批J 暂停回答结构化回携 answers[] +「剧本分析」改名「素材分析」（用户两条要求）
- **用户原话**：①「F-②c dsh 式 answers[] 成型回携，要做。」②「中文标签要改成中文翻译，不能叫剧本分析，要叫素材分析，其他也一样。」
- **① F-②c 结构化回携（对齐 dsh `AskUserQuestionAnswerItem`）**：
  - **背景**：批F 给暂停卡补了 `questions[]`（一次问 N 问），但**回答侧仍是扁平的**——前端把各问所选**逐行拼接**成一个 `value`，后端只能靠「第几行 = 第几问」的位置约定反推；问题问句含换行、或某问用自定义文本作答时该约定即错位。
  - **改动**：`ChatRequest.pause_response` 扩为 `Dict[str, Any]` + 新增 `answers=[{id, selected[], custom?}]`；`chat_consume` 新增 `normalize_pause_answers`（纯函数：丢非 dict/无 id/空回答项、`selected` 滤空、`custom` 非空才带；**任何畸形输入回落空列表、绝不抛异常**）；落盘 `pauseAnsweredAnswers`（非空才写）；前端多问题卡 `sendQuestions` 按问题 id 组装 `answers` 一并回携。
  - **兼容红线**：**`value` 扁平字段逐字保持**——旧消费链零改动（对勾匹配 `turn-groups.answeredValueFor` 按值相等、`is_flow_continue_value` 行格式判定都读它）；旧形态标记**不出现** `answers` 键（落盘形态不变）；`custom` 槽承载「其它（自定义输入）」。
  - **回归钉** = `tests/unit/test_pause_answers_structure.py`（18 条：归一清洗/纯函数健壮性/消费透传/旧形态零变化/落盘非空才写）+ 前端 `ConfirmActions-multi-question.test.tsx` 扩 3 条。
- **②「剧本分析」→「素材分析」**（同批直译口径的延续）：
  - **依据**：该阶段收的**不只是剧本**（Skill 支持上传参考图/视频等素材），且前端 `SECTION_META` 与多个 Skill 章节**本就叫「素材分析」**——「剧本分析」是以偏概全的旧叫法。用户裁决对齐。
  - **落点（4 处表 + 4 处用户可见文案，只改表不够）**：`registry.STAGE_LABELS`（`script_analyze` 与 `script_analysis_report` 两键）、`workflow_contract.NODE_TITLES`（`analyze_script`）、`stage_probes.CANONICAL_STAGES`（`analysis`）；另 `event_cards` 事件卡标题与折叠区标题、`fc_feedback.describe_fc_tool` 动作日志、`planner_output` 轮末兜底正文、`chat_service` R9 对话摘要（meta 同步）。
  - **新钉**：`test_analysis_rename_covers_all_user_facing_surfaces` 锁「只改 STAGE_LABELS 会漏」的那些面；`_RETIRED_LABELS` 加「剧本分析」防回潮。
- **执行期踩坑（已修，值得留痕）**：用 PowerShell `Set-Content -Encoding UTF8` 批量替换文本会**注入 BOM**（U+FEFF），导致 `manager.py` 解析失败、`ref_integrity` 门禁 FAIL。已剥离 4 个受影响文件 + 批G 遗留的 1 个测试文件；**其余 6 个 BOM 文件经 git 基线核实为仓库既有**（非本次引入），未动。
- **验证**：`tests/unit` + `tests/integration` **2547 passed / 0 failed**；vitest **124 files / 1022 passed**；**acceptance 全量 18/18 PASS**；`npm run build` 通过（首屏 378.81 kB）；`data/skills` 零 diff。

### 2026-09-21 · 批I 阶段展示标签口径统一：按英文 tag 直译（事故 4444/Q6①，**翻案** 同批方案待决-1 的 H-a）
- **背景（用户两次纠正，均成立）**：①「所有都是一样的字段……本项目每个阶段都是同样的字段啊」——**实测确认**：Skill 用 `<tag>…</tag>` 字段分章节（`web/skill_docs.py:120-128` 正则取），`tool_sections(skill, "storyboard_key_elements")` **16/16 全部命中**，字段名完全一致；注入一直是对的。②「`storyboard_key_elements`，标签是这个，名字直接给中文翻译就行了啊。**『关键元素拆解』只是我平常跟 ai 沟通的术语**，结果就写上去了。」
- **翻案说明**：同批方案 §五 待决-1 原采纳 H-a（不改），理由是「16 个 Skill 对同一阶段叫法各不相同，改了只服务 1/16」——**该前提是误读**：我把「该 tag 下正文的第一行文字」（如「设计 key_element」「全局风格锁定」「如何设计关键元素」）当成了「章节名」。前提推翻后，H-b 的正确形态（**直译**，非"改成某个 Skill 的措辞"）代价小、收益实在，故本批执行；H-c 仍不做（会翻案 2222/Q3b）。
- **改动（四张表统一为英文 tag 直译）**：`registry.STAGE_LABELS`（关键元素拆解→**关键元素**、分镜设计→**分镜**、音频层设计→**音频层**、媒体提示词编写→**提示词编写**、时间线组装→**组装导出**）；`workflow_contract.NODE_TITLES`（同前三键对齐 + assembly）；`stage_probes.CANONICAL_STAGES`（assembly）；`src/web/lib/skill-structure.ts::SECTION_META`（分镜设计→**分镜**）。
- **关键发现**：前端 `SECTION_META` **早就是直译口径**（关键元素/音频层/组装导出），**只有后端是异类**——同一阶段在前端卡片与后端下发上各叫一个名字。本次把后端对齐到前端已有口径。
- **未动（刻意保留）**：`write_spec`/`review_*`/`ke_media`/`shot_media` 等**没有对应 Skill 章节字段**的平台节点保持原措辞（平台动作，直译无从谈起）。
- **性质**：纯文案变更、**零逻辑风险**——标签值只参与显示与下发（`stage_label_for_tool` 仅查表返回），不参与任何判定。
- **防回潮钉** = `tests/unit/test_stage_label_vocabulary.py`（7 条）：不得回潮自造术语 / 前后端对同源 tag 必须同名 / 同名键两条展示链一致 / 核心三键确为直译 / 平台自有节点未被扩大打击面。**突变验证已做**：注入回潮值「关键元素拆解」后 **4 条钉立即失败**（证明非空转测试）。
- **验证**：`tests/unit` + `tests/integration` **2528 passed / 0 failed**（含 7 条新钉）；vitest **124 files / 1019 passed**；**acceptance 全量 18/18 PASS**；`npm run build` 通过（首屏 378.81 kB）；`data/skills` 零 diff。

### 2026-09-21 · 批G 子代理走流式通道 + 思考进 actor 卡（事故 4444/Q4）
- **背景（4444 实跑取证，日志逐行）**：`15:27:59.4` 子代理启动 → `15:28:01.9` step1 成功（读素材 2.5s）→ `15:29:02.0` 504 重试 1/2（距上一步 **60.1s**）→ `15:30:03.1` 504 重试 2/2（**61.1s**）→ `15:31:05.2` `kind=upstream → escalate`、子代理 `turn/end reason=error`。**一张卡未建**——批A3 补的「每批 3~5 个」纪律**根本没轮到使用**，它死在第一次要出产出的那次调用上。
- **根因**：`planner._launch_subagent` **不传 `stream_hook`** → `turn_executor.llm_call` 走 `else` 分支（非流式 `call_llm`）。**三条独立证据**：① 日志是 `[Retry] chat HTTP 504`（`retry.py:79`），而 `with_retry` **只被非流式 `chat()` 调用**（`openai_compat.py:553`），流式路径打的是 `[OpenAICompat] 流式瞬时故障`（`:707`）；② `data/sse_capture/` 在 4444 窗口只有 **5 个文件**，时间戳全对应主代理的流式调用，子代理（`1789975679+`）**零个**（落盘只在 `_stream_once` 内）；③ 子会话 `assistant/partial` **0 条** vs 主会话 **28 条**。
- **后果三项**：无步内增量落盘（8888 事故批建的「大步中断不再全量丢失」对子代理失效）；无「已产出则不重试」保护（`chat_stream` 的 `yielded` 判定只在流式分支）→ 长产出期间遇瞬时故障**只能整轮重来**；无 `reasoning_delta`（同分支内发出）→ 思考不可见。叠加 `runtime_settings.json` 的 `subagent.thinking_level=high`。
- **改动**：`planner._launch_subagent` 传 `stream_hook=_child_stream_sink`（**收口实现**，只触发流式分支、不透传父正文——一次委派不该两处显示同一段话）；`SseReasoningDeltaEvent` 补 `subagent` 标记（**须与前端分流同批**：只开流式而不分流，子代理思考会串台进父代理思考面板）；`sse-events.ts` 带标记 → actor 域、无标记 → 原路径；`subagent-actors` actor 增 `reasoning` 累计 + 上限截断（`SUBAGENT_REASONING_CAP=6000`，超限保留**尾部**）；`SubagentActorCard` 思考折叠区（**执行中即可展开**）。
- **同批暴露的真实缺陷**：`test_subagent_delegation.py::_ScriptedAdapter.chat_stream` 原先把 JSON **字符串**传给 `dict(tool_args=...)` → `ValueError`。该桩此前恒不触发（父子都走非流式），批G 激活后才暴露；已按真实契约修正（`tool_args` 是**已解析的 dict**，解析失败才走 `tool_args_raw`/`tool_args_error` 旁路）。
- **边界（如实登记）**：**不承诺根除 504**（上游网关行为非本项目代码）；批G 修的是「长产出期间无增量保护、无重试豁免、思考不可见」，降低单次失败的全损面。
- **验证**：`tests/unit` + `tests/integration` **2521 passed / 0 failed**；vitest **124 files / 1019 passed**；**acceptance 全量 18/18 PASS**；`npm run build` 通过（首屏 378.81 kB < 400 kB）。

### 2026-09-21 · 批F 暂停卡补 questions 数组层：一次可问 N 问（事故 4444/Q2③+Q3）
- **背景（4444 实跑取证）**：模型有 **5 个维度**要问（画幅/时长/影像风格/角色造型/二向箔显名），手上却只有**一个扁平 `options` + 一个 `multi_select`**——只能自创「套餐」把前四维压成互斥预设、把第五维塞进 `detail`。两处后果：① 为「怎么问这一个问题」花了 **8 段思考/2740 字/34.3s**（conv-main seq31-36），反复自问「multi_select 会不会语义混乱」「group 到底能不能每维选一个」——**它没有任何依据**（`group` 的真实语义在 schema 里没写，只有一句"用于前端归类显示"）；② 第五维塞进的 `detail` **不是可选项** → 用户**结构上无法**对它表态 → 用户只点了套餐 → 模型自判「遵循剧本原文不算擅自补全」→ **写进了既定规格**（「台词处理：遵循剧本原文，"白色薄膜"不显名为"二向箔"」，落盘取证）。正是 `protocol.md` 判据④要防的事——**根因是工具形态让用户答不了，不是模型不守规矩**。
- **dsh 参照**（用户指定要查）：`dsh-tool-ask-user` 的 `ask_user_question` 收 **`questions` 数组**，每项自带 `id`(必填)/`question`(必填)/`header?`/`options?`/`multi_select?`（`dsh-user-questions` types.d.ts:29-44 另有 `detail?`）。
- **改动（扩展现有单问题形态，不废除）**：后端 `pause_composer` 新增 `PauseQuestion` + `normalize_options`（选项面归一**唯一实现**，从 `fc_tool_runner` 内联逻辑收上来）+ `normalize_questions`（缺 `question` 的项**回落模板不丢项**；为空则由扁平字段构造单元素列表）；`WorkflowPauseInput` 增 `questions`，`detail` 描述补「**要用户拍板的事请放进 options**——detail 不是可选项，用户无法对它作答」；贯通链五跳（`fc_response`→`turn_executor`→`agent_loop`→`planner_output`→`planner`）按长度读取/追加 + `SseDonePayload.pause_questions` + 持久化 + web 两路；前端多问题分支（各问各块、底部单一发送、所选**按问题顺序逐行拼接**、未答完不可发送、多选渲染复选框）、`pauseQuestions` 空时**逐字走原分支**。
- **Q3② 修复（同批）**：`AnsweredOptions` 选中项除标题外**同时显示 `description`**（实证：用户选了「电影级写实科幻（推荐）」，落盘只有标签，详细描述虽随 `confirmOptions` 落盘却不渲染，回看时看不出当初选了什么）。发送 payload **不变**（仍回标签，与 dsh `selected` 只回标签一致，且 `turn-groups` 的对勾匹配依赖值相等）——只补**显示**。
- **生成器坑（同批实证）**：`gen_api_types.py` **只渲染 `TS_EVENT_FRAMES` 表内条目**；仅在 `$defs` 里出现的嵌套模型会产出**悬空 TS 引用**（`tsc` 实测 `Cannot find name 'SseDonePauseQuestion'`）。已把 `SseDonePauseQuestion` 显式登记进表。
- **红线保持**：① 不静默丢弃（`questions` 空→扁平→模板，任何组合都至少一问）；② 问即停语义不变；③ 单一活跃暂停槽位/`pause_id` 幂等/三态事务写入不变；④ 旧消息（无 `pauseQuestions`）渲染逐字不变。
- **验证**：`tests/unit` + `tests/integration` **2513 passed / 0 failed**；vitest **123 files / 1011 passed**；`acceptance --quick` 全绿；`npm run build` 通过（首屏 378.32 kB）。

### 2026-09-21 · 批E 任务书去自伤：删反例清单内部词 + 段②判据改锚子代理相关性（事故 4444/Q2①+Q5+Q6②）
- **背景**：批C（5555/Q5）的「去框」**没治净，且自己成了新污染源**——两处实跑取证：① `SUBAGENT_POLICY` 为表达「不要复述什么」，在括注里列了四个**系统内部机制词**（范围几个角色/几个场景、字段怎么写、**要不要建卡**、交不交提示词）；模型抓的正是其中之一：「章节里会说明**是否建卡**等」（conv-main seq25）——而 `建卡` 在 `data/skills/*/SKILL.md` **零命中**，说明是平台自己喂进去的。② 段②判据口径是相对**「规格文档」这一个载体**定义的（「尚未落入规格文档的新决定」），而不是相对**「这个子代理用不用得上」**：4444 派 `script_analyze` 时规格尚未创建，语言偏好按字面**必须**写进任务书（模型思考原文「委派任务书里告诉子代理这个新决定」）——而剧本分析子代理用它不着。
- **改动**（`prompts/planner/subagent.md::SUBAGENT_POLICY` 唯一源）：① 删举例、只留因果（不靠穷举反例表达"别复述"）；② 段②改为「**只有这个子代理用得上、而它自己读不到的东西**」，并明写「**没有就整段不写**——不要写「无新增决定」之类的占位句填坑」（该槽位此前是**必须存在**的，模型只能写占位句，4444/Q6② 实证「本阶段无新增未落盘决定。」）；③ 补：段①不得复述规格参数现值与源文档出处、不得交代章节自带的下游依赖关系（模型两样都写了）；④ `protocol.md:13` 补**落盘时机**（更早阶段确认的决策先记着、到规格阶段一并写入，不必提前创建文档——模型自解了时机，属规则空档）。
- **回归测试**：批C 断言**改写**（非删除）——新增 5 条反向钉（旧口径不得回潮 / 禁止占位句 / 禁复述规格参数与下游 / 反例清单不得含内部词 / 落盘时机）+ 子级任务文本侧的反例短语钉。**边界说明**：子级任务文本的钉只锁父侧反例**短语**（要不要建卡/字段怎么写/交不交提示词），**不锁裸名词**——批A/A3 刻意补的「大批量登记（建组/建卡/写提示词）分批做」是子代理行动指引（5555/Q8 直接修复），删它会回归；两者区别是句式（揣测章节内容的疑问式列举 vs 陈述式子代理行动指引），测试 docstring 已写明。
- **验证**：`tests/unit` + `tests/integration` **2506 passed / 0 failed**。

### 2026-09-21 · 批D 规格写入判据细化：判据②收窄方针级 + 判据③点名清单类（事故 5555/Q7）
- **背景（5555 实跑取证）**：用户「为什么规格文档，还是很多一大坨的东西都往里面塞，一点都不精简。人家 flova 多精简」。落盘 `制片规格.md` **716 字** vs flova `规格文档.md` **460 字**：①「素材来源：…（判定为 C 类半结构化剧本，可直接进入 Storyboard，无需先做短剧化改编）」= 分析阶段结论，不是全局参数（flova 连该字段都没有）；②「**叙事结构**」整节 = 3 场次逐行 + 8 角色逐名 + 道具 8.5×5.2cm + 25–31 镜——按判据③本应整节归故事板；③ flova 的「角色方向」是**一句话方针**、零逐人明细。
- **根因（判据措辞两处）**：①判据②举例含「**叙事驱动、核心视觉母题**」——这两个词本身就是"分析章节名"形态，模型据此把整个分析叙事搬进规格；②判据③只写「逐条细节」——模型**不认为「8 个角色名单」是"逐条细节"**，它读成"范围"，于是照写。
- **改动**（`prompts/planner/protocol.md` 唯一源，非新增条款）：
  - 判据②：删「叙事驱动、核心视觉母题」举例 → 改为「**写成方针级一两句**（如角色方向、视觉风格、叙事驱动），不罗列实体明细」。
  - 判据③：由「只影响某个镜头、某个角色的逐条细节」扩为「**清单与逐条明细一律归故事板元素，不写规格**：场次清单、角色名单、道具清单、镜头数预估、逐人外貌服装、逐场布局、逐镜参数都属此类」。
- **回归测试**：`test_protocol_role_and_spec_boundary.py` 扩到 **22 条**——新增 `test_spec_clause_criterion_two_is_policy_level`（判据②含「方针级」且**不含**「核心视觉母题/叙事结构」，反向钉防回潮）+ `test_spec_clause_criterion_three_names_lists`（逐词钉死四类清单 = 5555/Q7 直接病根）；原四条判据用例按新措辞改写。
- **已知残留（不修，用户 2026-09-21 裁决）**：`SKILL.md:17` 要求把「图像/视频生成渠道与分辨率」写进规格，属系统注入项回流。用户明确「**skill 文档要求的全局设置是正常的，你不要管，不用登记欠账**」——故本批只从判据侧收窄，不改 Skill（冻结#16）、不登记债务。
- **验证**：`tests/unit` + `tests/integration` **2500 passed / 0 failed**；`acceptance --quick` 全绿；`check_prompt_literals` PASS。

### 2026-09-21 · 批C 委派任务书去框：三段改两段（事故 5555/Q5）
- **背景（5555 实跑取证）**：用户「派子代理的任务书还是框的太死了，素材分析章节里面已经有具体目标了，目标就是按章节执行任务就行了。下游用途也不写」。批2（2222/Q5）引入的三段式方向对（禁止复述章节），**但没治好**——任务书原文：`script_analyze` ①目标「…提取角色、场景、关键道具等关键元素，并识别该文本的剧本类型」**就是 `SKILL.md:16` 原文整句**；`storyboard_key_elements` ③「本轮新确认的决策**已全部写入《制片规格.md》**——场景按原著…保持 8 个独立角色不合并…」= 声明"已写入规格"后又把同样内容列一遍（**明知故犯的第二份事实源**）；①还写了「8 名角色、3 个场景、7 项关键道具」= **范围**（策略段明写「一律不写」）。
- **根因（批2 的设计缺陷）**：第②段「**下游用途**（谁会用、用来干什么）」**本身就是一个邀请复述的坑**——既然要交代下游用途，模型自然把章节里的产出清单再抄一遍。而子代理 `history=[]`、阶段章节已由 `planner._launch_subagent` 全量注入，它**真的不需要**知道下游用途。
- **改动**：`prompts/planner/subagent.md::SUBAGENT_POLICY` 三段 → **两段**：①一句目标 ＋ 执行依据＝**执行所选 Skill 的本阶段章节**（章节全文已注入，是产出规范与工作方法的唯一依据，**不要复述章节内容**）；②尚未落入规格文档的新决定。删②下游用途。补因果（「你复述只会和章节打架、并挤占子代理的注意力」「章节里都已经写全」）——**非纯禁令**（G3）。`RunSubagentInput.task` 描述同步两段式（完整表述唯一源仍是 `SUBAGENT_POLICY`，P1）。
- **回归测试**：批2 的 5 条断言**改写**（非删除）为 6 条——新增两条反向钉（`下游用途` 不得回潮、`任务书三段` 不得回潮）+ `test_task_brief_points_at_section_as_the_basis`（钉死"章节即依据"这个删掉复述后的**代替品**）。
- **验证**：`tests/unit` + `tests/integration` **2498 passed / 0 failed**。

### 2026-09-21 · 批B 暂停提问结构对齐 dsh：问句改由模型撰写（翻 2026-08-31 裁决，事故 5555/Q4）
- **裁决（用户，2026-09-21）**：「这个停下来提问的机制**可以照搬 dsh**……人家 dsh 这个结构就非常清晰」。**翻案 2026-08-31 / v2批4「卡问句系统组装」裁决**（原接线：模型只提交审批事实，卡问句系统按阶段组装成固定模板，模型原文一律进正文通道）。
- **翻案依据（5555 落盘实证 `chatMessages[1].confirm`）**：旧模板恒为 `'「本阶段」已完成，请过目以上成果并选择下一步。'`——① 阶段标签回落「本阶段」（批A/A4 已修）；② **问句与本次要问的事完全无关**：那一轮实际在问输出语言/画幅/时长/角色处理，模板却在说"阶段已完成，请过目成果"。
- **现契约**（对齐 `@deepseek-ai/dsh-tool-ask-user` + `dsh-user-questions`）：`question` = 模型撰写的问题正文（取代系统模板）；`header` = 短标题；`detail` = 辅助说明（**渲染时不变成选项标签**）；`multi_select` = 多选标志；回答按 `pause_id` 结构化回携（既有）。
- **两条红线（本批保持）**：① **不静默丢弃**——模型未写 `question` 时**回落系统模板**，绝不留空卡（`fc_tool_runner` 记载 2026-09-12「静默剥离字段造成假成功空提示词卡」事故，红线同样适用）；② **正文通道不没收**——模型 `message` 原文照旧进正文（`pause_overflow`）。
- **改动**：`core/pause_composer.py`（新增 `PauseCard` + `compose_pause_card`；`stage_template_question` 抽出系统模板唯一源；旧签名保留兼容）→ `WorkflowPauseInput` 四字段 → `fc_tool_runner`（`_BatchState` 三字段 + `FCExecuteResult` 尾部三字段，位置解包兼容同 `pause_id` 先例）→ `fc_response` → `turn_executor` → `agent_loop` → `planner_output`（非空才透传，兼容旧测试桩）→ `planner`（`PlannerResponse` + done payload）→ `sse_events::SseDonePayload`；持久化 `conversation_ops` + `state/manager` + `web/chat_service`（流式与非流式两处，`getattr` 取值兼容 `SimpleNamespace` 桩）；`gen_api_types.py` 重生成（**不手改** `api.generated.ts`）；前端 `types/index.ts` / `done-message.ts` / `ConfirmActions.tsx`（`headerBlock` 单组与向导两分支共用）/ `chat-cards.css`。
- **回归测试**：`test_pause_overflow_guard.py` **改写**（契约变更，非删除）7 条——模型 `question` 成卡问句 / **无 `question` 回落不静默丢** / `message` 进正文 / `header-detail-multi_select` 透传 / 缺省不伪造；新增 `ConfirmActions-dsh-pause.test.tsx` 6 条——模型问句直达题面 / `header` 排在题面前 / **`detail` 不进选项区** / 缺省与空白不渲染空行 / 向导分支同构。另修 11 处旧断言：`FCExecuteResult` 扩字段后，位置解包的测试改为**按字段名取用**（该类 docstring 本就写明「字段名即契约，杜绝位置解包」）。
- **验证**：`tests/unit` + `tests/integration` **2497 passed / 0 failed**；vitest **121 files / 1002 passed**；`python scripts/acceptance.py` 全量 **18/18 PASS**；`npm run build` 通过（首屏 377.51 kB < 400 kB 上限）。**UI 变更待用户目测**（宪法 §3.1）。

### 2026-09-21 · 批A 子代理上下文组合修缺（事故 5555/Q3+Q8 与两项取证期追加发现）
- **本批同时闭合用户 8 问中的 Q3/Q8，以及取证期顺带查出的两个同根因族缺陷**（追加-1/追加-2）。
- **Q8（子代理两次 60s 网关 504 阵亡）**：`logs/agent-20260921.log` 逐行——11:10:55 派发 → 11:11:55/11:11:56 两次重试 → 11:12:59 `kind=upstream` escalate → `turn/end reason=error`；11:13:15 重派 → 11:14:15/11:15:16（60s 整）→ 11:16:18 再次阵亡。两个子会话转录形状一致：读素材**成功** → `step/feedback` → 下一次调用**再没回来**（要一次性吐 8 角色+3 场景+7 道具+8 张音色卡，deepseek 上限 8192 tokens）。**唯一能拦住它的《Skill 流程纪律》第 6 条（每批 3~5 个 / 不要一次生成全部 / 思考同样分批）物理到不了子级**——该纪律只随 `_selected_block` 注入，而子级 `skill_name=""`（`planner._launch_subagent`）。
- **追加-2（Q8 的精确根因）**：`protocol.md` **整文件无 depth 门控**注入子级，其中两句是**悬空指针**——「停轮与批次时机见《Skill 流程纪律》第 6 条（本协议不复述）」「防虚报…唯一细则见第 3 条」。即：**子级拿到的是「详见第 6 章」而第 6 章不在书里**，且 `DELEGATION_CONTEXT` 里**没有代替品**。→ **A1**：`_sec_protocol` 加 `subagent_depth≥1` 门控（子级不注入；主代理逐字不变）。理由：该协议自称「制片调度…把各专业阶段委派给对应执行环节」，对**不能委派**的子级语义为反。
- **A3（Q8 闭合）**：`subagent.md::DELEGATION_CONTEXT` 补**分批推进**契约（每批 3~5 个调用 / 思考同样分批 / 后果说明"已落盘的批次仍保留、未落盘的全部丢失"）——非纯禁令（G3），且**自足不指向《Skill 流程纪律》**（A1 后该指针对子级不可达）。
- **追加-1（子级收到循环指令）**：复刻 key_elements 子级 context 实测 `build_state_tail_message` 输出——`以下工具本轮不可用：…, run_subagent, …。替代路由：经委派（run_subagent）执行对应阶段。`**用被禁的工具当被禁工具的替代路由**。根因：`turn_excluded.md` 的替代路由是**面向主代理单场景写死的常量**（`prompt_builder.py` `_excl_route = "经委派（run_subagent）执行对应阶段"`），而 `turn_excluded` 通道**被子级复用**（子级 deny 集整体并入裁剪集，`planner._compute_excluded_tools`）。→ **A2**：`build_state_tail_message` 的 UNAVAILABLE 段加 `subagent_depth≥1` 跳过（子级工具面启动时已固定，逐条列无行动价值；其唯一正确表述「不在本次委派授权面」已由 `DELEGATION_CONTEXT` 承担，再渲染属复述 P1）。主代理侧渲染与文案**逐字不变**。
- **Q3（暂停卡恒显示「本阶段」）**：三跳根因链——父代理暂停轮唯一工具是 `run_subagent`（不在 `registry.STAGE_LABELS` 内）→ `stage_label_for_tool` 返回 `""` → `last_stage_label` 恒空 → 回落模板「本阶段」；子代理内部那次 `script_analysis_report` 跑在**子级自己的 runner 实例**上，父级看不见。→ **A4**：新增 `subagent.stage_display_label(stage)`（唯一源 `STAGE_LABELS`）+ `fc_tool_runner._commit_call` 在 `run_subagent` 成功时从其**入参** `stage` 回填父级阶段标签（阶段事实就在父级自己的调用入参里，无须子级回传）。通用委派（无 stage）**不伪造**标签。
- **回归测试**：新增 `tests/unit/test_subagent_context_composition.py`（**12 条**）——A1/A2 各含**主代理侧防误伤双向钉**（协议段 / UNAVAILABLE 段对主代理逐字不变）、A3 含"自足不指向《Skill 流程纪律》"+端到端可达性、A4 含"委派带 stage → 暂停卡带真实标签"与"通用委派不伪造"。
- **验证**：`tests/unit` **2393 passed** + `tests/integration` **100 passed**（0 failed）；`acceptance --quick` 退出码 0。`data/skills` 一行不改（冻结#16）。
- **未做（属外部因素，不承诺根除）**：供应商 504 本身是外部网关行为；A3 通过**降低单次输出体量**间接降低触发概率。

### 2026-09-21 · 批4 阶段建卡媒体类型限定：key_elements 只能建音色卡（用户裁决）
- **裁决（用户，2026-09-21）**：「key_elements 要建组和卡，因为要在某些 skill 的要求下，要建对应的人物的音频卡，并且在音频卡的草稿里填入音频描述的提示词。本项目关键元素中已经有音频容器了，卡片是其他卡的 0.5 倍，并且卡面只有音频符号不会有文字渲染。**如果音频卡是单独的工具或者字段，就提供给子代理。如果是混在一起，就想办法，让子代理只能建音频卡。**」
- **查证：属"混在一起"**——音频卡**不是独立工具、也不是独立字段**，与图像卡共用 `storyboard_add_draft` / `storyboard_create_group` 内联 `draft` 同一入口，仅靠 `mediaType` 值区分（前端半尺寸图标化判定 = `DraftCard.tsx::isVoiceCard`：`type==='keyElement' && mediaType==='audio'`，与本条描述一致）。故按用户指示"想办法让子代理只能建音频卡"。
- **口径补全（用户同日追认）**：图像卡（含壳）与提示词**全部归 `write_media_prompt` 阶段**——该阶段 `_STAGE_TOOLS` 含 `add_draft`/`patch_draft`，建壳与写词都够用；音色卡由 `add_draft` **一次建好**（含 `timbre`/`desc`），**不放开 `patch_draft`**。
- **改动**（4 处，声明 + 下发 + 判定 + 装配）：
  - `core/subagent.py`：新增 `STAGE_CARD_MEDIA`（**正向允许集**，唯一事实源）= `{storyboard_key_elements: {"audio"}}`；新增 `stage_card_media(stage)` 访问器；新增 `_validate_stage_card_media()` 装载期 fail-loud（键必须是可委派阶段 / 该阶段须真持有建卡工具 / mediaType 须为合法枚举）。
  - `core/fc_gates.py`：新增 `card_media_gate` 并接入闸机链（顺序：暂停纪律 → 工具风险 → 生成确认 → 建组结构 → **建卡媒体** → 提示词结构）；`GateContext` 加 `stage_card_media`/`stage_label`。
  - `core/fc_tool_runner.py`：加 `stage_card_media`/`stage_label` 实例属性并在 `_gate_ctx` 下发（测试桩缺属性回落空集，不误伤存量测试）。
  - `core/planner.py`：`PlannerContext` 加 `subagent_stage`（子级轮记已归一化的委派阶段，`_launch_subagent` 写入）；新增 `_apply_stage_card_media(context)` 按轮下发（同 `turn_excluded` 模式：轮始一次、轮内冻结）。
- **判定口径（防误伤）**：①`mediaType` 缺省时按工具的构建工厂口径回落 `"image"`（`DRAFT_DEFAULT_FIELDS`）——不能因字段缺省就误判为合法；②`create_group` **不带卡时放行**（纯结构动作，元素登记要用它）；③未登记阶段/通用委派 = 空集 ⇒ **不启用限定**（零变化）。
- **⚠️ 与 3333 事故的分界（本批红线）**：限定走**明确拒收 + 回喂"该去哪里做"**，**绝不静默剥离字段**——`fc_tool_runner` 记载 2026-09-12 曾有「无阶段感知静默剥离 `add_draft` 内联 prompt」的闸机，造成**假成功空提示词卡**（3333 项目实证）被用户裁决删除。拒收文案含三要素：原因 + 状态保留声明（"本次调用未执行、工作台保持原样"）+ 去向（"请在委派 `write_media_prompt` 阶段时创建"）。
- **回归测试**：`test_production_prune.py` +4 条（声明表单一事实源 / 拒收图像卡且放行音色卡与不带卡建组 / 未登记阶段不受限 / **管线连通性 end-to-end**——钉死"表改了但没接线" + 链路顺序在建组结构闸之后、提示词闸之前）；`tests/integration/test_subagent_delegation.py` +1 条**真过闸机链**的端到端（子代理建音色卡放行落账、建图像卡被拒且不落账、拒收文案可见去向）。
- **验证**：`tests/unit` + `tests/integration` **2481 passed / 0 failed**；`python scripts/acceptance.py` 全量 18 步全绿（含 cov/fe_cov 地板）。
- **同批**:本批与上一条「批0 回归修复」共同回答了用户关于「音频卡是单独工具还是混在一起」的问题——查证为混在一起，故以限定方式实现。

### 2026-09-21 · 批0 回归修复：key_elements 恢复 add_draft（音色卡是该阶段产出）
- **回归**：批0（`b1f8fc0`）把 `_STAGE_TOOLS` 接进执行路径后，key_elements 阶段的子代理**建不出草稿卡**——该阶段的 `_STAGE_TOOLS` 只声明了 `{create_group, delete_group}`，于是 `add_draft` 被 deny。但**角色音色卡（`key_element_audio`）正是这个阶段的产出**：Skill 明文「角色的声音特征（音色/语气/情绪基调）**单独登记为 key_element_audio**，与角色元素绑定」（`AI-短剧一站式生成/SKILL.md:66`；14 个 Skill 中 **8 个**的 `storyboard_key_elements` 章节含音色/声音/音频字样）。
- **为什么以前没暴露**：`_STAGE_TOOLS` 里 key_elements **自 `d75a374`（铺满批）起就只写了 `create_group`**，`2778117`（R4 批）曾把三阶段整行删掉，`589cad5`（K1 批）恢复为 `{create_group, delete_group}`——**`add_draft` 从未进过这张表**。而该表在批0 之前**零约束力**（`stage_tools()` 无生产消费者，只用于装载期校验），所以这个纸面遗漏从未产生行为后果；**批0 把它变成强制执行后，纸面错误就变成了真回归**。
- **实跑取证**（回归确实影响真实产出）：`proj-1789754393` 的关键元素阶段经 `storyboard_add_draft` 建了 **8 张 `mediaType=audio` 音色卡**（`Audio_程心`/`AA`/`曹彬`/`瓦西里`/`白Ice`/`领航员`/`观测员`/`研究员群像`）。另有 `剧情短片音色参考` 等 Skill 明写「通过 `storyboard_patch_draft` 将音色参考注册并绑定到对应角色的 `key_element_audio`」。
- **裁决（用户，2026-09-21）**：「key_elements 要建组和卡，因为要在某些 skill 的要求下，要建对应的人物的音频卡，并且在音频卡的草稿里填入音频描述的提示词……**如果音频卡是单独的工具或者字段，就提供给子代理**。」
- **改动**：`core/subagent.py::_STAGE_TOOLS["storyboard_key_elements"]` 补 `storyboard_add_draft` → `{create_group, delete_group, add_draft}`。`patch_draft` **仍 deny**（改既有卡字段 = 提示词撰写阶段的活）。
- **修正后的工具面**（各阶段可见的专业写入工具）：
  | 阶段 | 可见 |
  |---|---|
  | `script_analyze` | `script_analysis_report` |
  | `storyboard_key_elements` | `create_group` / `delete_group` / **`add_draft`** |
  | `storyboard_shots` | `create_group` / `delete_group` / `add_draft` / `patch_draft` |
  | `storyboard_audio` | `create_group` / `delete_group` / `add_draft` |
  | `write_media_prompt` | `add_draft` / `patch_draft` |
- **回归测试**：`test_production_prune.py`（`stage_tools` 映射补 `add_draft`、子级面断言改为 `add_draft` **不**在 deny 集且 `patch_draft` 在）+ `test_subagent_stage.py`（同向修正，注明音色卡依据）。
- **验证**：`tests/unit` + `tests/integration` **2475 passed / 0 failed**（`acceptance --quick` 全绿）。
- **未做（登记待裁决）**：用户要求的「想办法让子代理**只能**建音频卡」——即 key_elements 阶段建卡时**只允许 `mediaType=audio`**。经查音频卡**不是独立工具、也不是独立字段**，它与图像卡共用 `add_draft` / `create_group` 内联 `draft` 同一个入口（属用户说的"混在一起"那种），故需另行设计；且**必须避开一處已知前车之鉴**：`fc_tool_runner.py:458-460` 记载 2026-09-12 曾有「无阶段感知的静默剥离 `add_draft` 内联 prompt」的闸机，造成**假成功空提示词卡**（3333 项目实证）而被用户裁决删除——同类"按阶段裁剪入参"的做法有前科，须谨慎。

### 2026-09-21 · 批2+批3 委派任务书契约 + stage 枚举可见（事故 2222/Q5、2222/Q3b）
- **批2 背景（2222 实证）**：`SUBAGENT_POLICY` 原文「任务书**只写一句目标**：范围、源文档、产出规范都不写」方向是对的，但 2222 主代理**违反两次**：`storyboard_key_elements` 任务书写「按制片规格登记本项目的**全部关键元素：8 个角色、3 个场景**、核心道具白色薄膜及辅助道具，**并为每个元素编写设定提示词草稿**」（写了范围 + 交付物）；`storyboard_shots` 任务书写「…**编写含景别/机位/运镜/时长的分镜草稿**」（写了产出规范）。**后果实测**：两个子代理对同一个词「草稿」理解**完全相反**——key_elements 子代理 17/17 张卡全写了 prompt（越界到提示词撰写阶段），storyboard_shots 子代理把它实现成 `group.desc` 文本、**0 张卡**。
- **为什么旧规则拦不住**：①该句在**委派策略段**里，讲的是"怎么委派"而非"任务书写什么"；②它是**纯禁令**（"都不写"），**没给违反的后果、也没说为什么**；③更关键——模型当时**有充分理由写**：它认为自己在做"专业指导"（这正是批1 角色定义病根的行为投射）。
- **批2 改动**（`prompts/planner/subagent.md::SUBAGENT_POLICY`，唯一家）：
  - 由"一句目标"禁令改为**正向三段式契约**（可照抄的形态，比"别写那三样"更易执行）：①一句目标（要产出什么）；②**下游用途**（谁会用、用来干什么）；③**尚未落入规格文档的新决定**（用户在对话中新确认、规格里还没有的参数）。
  - 补**因果关系**：「剧本与规格文档里的既有内容不要复述——**子代理自己读得到**（工作台文档与上传素材都在它的读工具面内）……你**复述只会和章节打架**」。
  - **【用户 #6 修正】**：原方案第③条写的是「复述**已确认的全局约束**（如输出语言/画幅/风格）」——**用户指出"不要框的太死"**。核实：制作设定与剧本子代理本来就自读得到（2222 实证三个子代理都真读了：`read_uploaded_doc` + `read_project_doc` ×2 + `read_state_group`），父代理复述 = 纯冗余 + 双份事实源。故改为只写**子代理读不到**的东西（尚未落盘的新决定）。
  - **【用户 #7 要求】**：末句补「写规格文档时按协议的四条写入判据分档」（引用式指向 `protocol.md` 唯一正文，不复制——P1）——写规格的动作既可能发生在主代理（`document_write`），也可能发生在委派决策时（"哪些该进规格、哪些留给子代理"）。
  - `tools/document_tools.py::RunSubagentInput.task` 描述同步为三段式（只留可照抄的字段用法；完整表述与"为什么"唯一源仍是 `SUBAGENT_POLICY`）。
- **批3 背景（2222 实证）**：`RunSubagentInput.stage` 描述原文刻意**不列名单**（"可委派阶段名单由系统枚举"）。实测模型**必猜错一次**：先填中文「剧本分析」被 fail-loud 拒收 → 改 `script_analyze`，花 **3.5s + 一次失败往返**，且**每个新会话都会重犯**。fail-loud 报错时才列白名单 = "考完试才给答案"。
- **批3 改动**：新增 `_stage_hint()` **运行时动态拼接**可选值 + 中文标签（`script_analyze（剧本分析）、…`），单一事实源仍是 `PIPELINE_STAGE_KINDS` + `STAGE_LABELS`（**只引用不复制**，改枚举必然改描述）。先例 = `storyboard_tools._DRAFT_FIELDS_HINT`（同文件注释明写设计意图「对齐 dsh schema 精确性：模型看得见字段就不用猜」）。对齐 dsh `tools.restrict()` 理念——其报错同样列出 `known global tools`。
  - **保留 fail-loud 校验**（`fc_tool_runner` 不动）：description 是引导、校验是兜底，两层都在；`stage` 仍是宽松 `str`（不改 `Literal`，保住"未知值回落通用形态、不阻断委派"的既有语义）。
  - **门禁适配**：初版用函数内 lazy import 引 `core.subagent`，被 `func_imports` 门禁拒（禁新增方法内 import）；改为顶层 import（该文件本就有 `from src.video_agent.core import ports, prompt_gates`，`core.subagent` 仅依赖 `utils.prompts` + `skill_runtime`，无环）。
- **回归测试**：`tests/unit/test_protocol_role_and_spec_boundary.py` 扩到 **19 条**——批2 加 5 条（三段式齐备 / 第③段是"新决定"且含"子代理自己读得到"、反向钉不含旧表述 / 含因果说明防退化成纯禁令 / 含规格写入原则引用 / task 字段描述与策略段同向）；批3 加 4 条（描述含**每一个**枚举键 / 含中文标签 / 动态拼接非硬编码 / fail-loud 与宽松 str 语义保留）。
- **验证**：`python scripts/acceptance.py --quick` 全绿；`tests/unit`+`tests/integration` **2434 passed**（= 批1 后的 2415 + 本次新增 19，逐一对应）；41 个 adapter/网络类失败 = D-22 本机 `NO_PROXY` 环境缺陷，经 stash 对照确认为改动前既有。
- **未改动**：`data/skills` 一行不改（冻结#16）。

### 2026-09-21 · 批1 主代理角色定义与规格文档边界（事故 2222/Q1+Q4）
- **病根（2222 实跑取证）**：`prompts/planner/protocol.md` **第 1 行**自称「专业的编剧 + 分镜师 + 视觉总监」——该行最后修改于 **2026-09-16**（`f43f6e8`），而「主代理纯编排」裁决是 **2026-09-19**（`589cad5` K1 批）；该批只改了 `subagent.py`/`planner.py`/测试，**没有改 protocol.md**（K3 批 `9921392` 改了 `skill_runtime.md`+`subagent.md`，protocol 仍不在其中）。于是模型同时收到两句互相打架的自我定位：`protocol.md:1`（system 段 **order 10**、位置最靠前、**无条件注入**）说「你是编剧/分镜师/视觉总监」；`skill_runtime.md` 纪律 5 说「主代理是纯编排角色」（**只在选中 Skill 时才注入**，位置更靠后）。2222 的每一处越界都符合前者：抢读剧本（编剧当然读剧本）、把 8 角色/3 场景/道具写进规格（那是它的"专业产出"）、给子代理写超长任务书（分镜师在"指导创作"而非"派活"）。
- **第二处病根（规格边界）**：`protocol.md:13` 原文「规格文档**只**承载全局决策参数（画幅/时长/风格/声音与语言），渠道/分辨率/分镜上限由全局设置注入，实体细节归元素与故事板工件」有四处缺陷：①**P1 违规**——把 Skill 的四项要求复述成平台规则（四项唯一源 = `SKILL.md:17`，用户 #9）；②**「只承载」把地板读成天花板**——flova 明说「不是系统强制只有四项」「可以按项目需要扩展」，Skill 说"至少写这四项"，平台读成"只准写这四项"，恰好堵死扩展（这正是 2222 把实体细节塞进规格的推力之一）；③**第二份事实源**——`prompts/shared/global_settings.md` 已无条件注入渠道/分辨率/分镜上限，且 `prompt_builder.py` 注释明写「渠道唯一事实源为顶部全局设置」，散文复述零行为价值（用户 #11）；④**缺四档写入判据**——只说了"不该写什么"，没说"已确认的全局决策与分析得来的全局事实该写"、也没说"未确认的不得写成既定规格"。
- **裁决（用户，2026-09-21）**：用户 #9「是 skill 里明文要求的，**不是系统**」；用户 #11「这个已经是本项目系统写死了的，就**不用出现在任何散文描述**里面了」；用户 #12「**这肯定要落盘了呀。留在对话中子代理怎么使用呢**」。
- **改动**：
  - `protocol.md:1`：角色定义改为**制片调度**（对齐 flova 的调度层定位——flova 从不自称编剧/分镜师/视觉总监，只说自己是调度层）：「理解需求、维护项目文档、判断流程与暂停时机、把各专业阶段委派给对应执行环节。各阶段的专业创作（剧本分析、故事板设计、提示词撰写等）由对应执行环节完成，**你不亲做**。」动作通道唯一 = FC 那句原样保留。
  - `protocol.md:13` 重写：①「最小集由所选 Skill 声明」（**不复述**四项，P1 归位）；②四条写入判据（已确认全局决策 / 分析得来的全局稳定约束含**角色方向** / 逐条细节归故事板 / 未确认不得写成既定规格）；③「规格维度**不设固定条数**，可按项目需要扩展」（把地板还原成地板）；④**渠道/分辨率/分镜上限整句删除**（系统注入项不进散文）；⑤「用户已确认的角色/场景等设定**必须落盘**（规格「角色方向」字段或故事板元素）——**子代理不继承本次对话**，只能读工作台文档与素材；未落盘的细节对下游不可见。」
- **机制依据（可验证，非说服性 prose）**：「子代理不继承本次对话」是机制事实——`core/planner.py::_launch_subagent` 构造子级上下文时 `history=[]`，子代理拿不到父对话历史，只能经 `read_project_doc`/`read_uploaded_doc` 读工作台文档与素材。2222 实证：关键元素子代理正是靠 `read_project_doc(制片规格.md)` 拿到「程心：东方年轻女性，温婉而坚毅」等 8 个角色设定（剧本里只有名字、没有外貌）。**G3 自检**：这不是"写一句话让模型配合机制"，是告诉模型一个它必须知道的机制事实，否则它会把信息丢在只有自己能看见的地方。
- **落盘分层（对齐 flova 实际切分）**：方针级 → 规格（flova `06 flova/规格文档.md` **有「角色方向」字段**、零逐人明细；`05 flova/规格文档.md` 的叙事驱动点名程心/AA 但仍是方针级）；逐条明细 → 故事板元素。2222 的错不是"落盘"，而是把 8 人逐条明细写成了规格正文——**粒度错，不是位置错**。
- **同批修正**：`tools/document_tools.py` 一处注释仍在复述旧措辞（「规格只承载全局决策参数，实体细节归元素/故事板」），改为指针式引用（写入判据与落盘分层唯一源 = protocol.md），消除第二份表述源。
- **回归测试**：新增 `tests/unit/test_protocol_role_and_spec_boundary.py`（10 条断言，事故编号 2222/Q1+Q4）——①首句不含「编剧/分镜师/视觉总监」；②首句含「制片调度」+「不亲做」；③动作通道句不被捎带删掉；④四条判据齐备；⑤判据②举例含「角色方向」；⑥含「不设固定条数」且不含「只承载」；⑦**不复述** Skill 四项（逐词反向钉）；⑧**不含**渠道/分辨率/分镜上限；⑨含「必须落盘」+「子代理不继承本次对话」且**不含**「留在对话中即可/无需落盘」（直接否决上一版方案稿的错误表述）；⑩含落盘分层。
- **未改动**：`data/skills` 一行不改（冻结#16）；`skill_runtime.md` 纪律 5 的「纯编排」表述保留（两处现已同向，不构成矛盾）。
- **验证**：`python scripts/acceptance.py --quick` 全绿；`tests/unit` 2326 passed（41 个 adapter/网络类失败 = D-22 本机 `NO_PROXY` 环境缺陷，经 stash 对照确认为改动前既有、与本批无关）。

### 2026-09-21 · 批0 子代理工具面按阶段收口（事故 2222/Q5：散文宣称了阶段授权、代码没实施）
- **事故（2222 实跑取证）**：`storyboard_key_elements` 子代理的推理有 ~21.5% 花在「用 add_draft 算不算越权」的反复摇摆上，最终**越界**写了 17 张提示词卡。取证结论：**不是模型多疑**——平台同时给了它两套互相矛盾的信息：①注入章节 + 任务书散文说「你是 key_elements 阶段，只登记元素」；②**工具面**里 `storyboard_add_draft`/`patch_draft`/`document_write` **真真切切在手**（实测可见 **18/23** 个工具）。散文与工具面投票 1:2，模型按「任务书要求 + 工具在手」越了界。
- **代码根因**：`_STAGE_TOOLS`（`subagent.py:95-107`）**从未接进执行路径**。`child_deny_set()` 只返回 `SUBAGENT_TOOL_DENY`（与阶段无关的四条硬约束）∪ `STAGE_TOOL_DENY_EXTRA`（仅 `read_skill`）；`stage_tools()` 在生产运行时**零消费者**（全仓仅定义处 + 测试引用），该表只用于装载期 fail-loud 校验与 `MAIN_AGENT_DENY` 子集校验。即：**声明性表格表达了设计意图，但没有约束任何人**。
- **裁决（用户，2026-09-21）**：同意批0，且置于四批之首——它是本次唯一「消除病根」项，其余为文案对齐。「工具都是子代理该用的工具，为什么子代理会有纠结算不算越权呢？是什么限制了子代理，让它有这样的想法？」（用户 #8）
- **改动**：
  - `core/subagent.py::child_deny_set`：带 stage 时并入 **`MAIN_AGENT_DENY − stage_tools(stage)`**（第三项）。原理（one visibility = one permission）：`MAIN_AGENT_DENY` 里的工具主代理结构性不可见、只存在于委派路径上，故**只有在自己 `_STAGE_TOOLS` 里声明它的那个阶段拿得到**，其余阶段物理不可达。通用委派（无 stage）**不并入**（无阶段即无阶段边界，全现状不动）。
  - `STAGE_TOOL_DENY_EXTRA` 扩充：`read_skill` + `storyboard_confirm_draft` + `storyboard_media_to_chat`（后两者是**面向用户的交互动作**：标记「已确认」= 用户裁决、媒体插入用户输入框 = 给用户过目，无任何可委派阶段认领）。
  - 新增装载期 fail-loud：若某工具同时进了 `_STAGE_TOOLS` 与 `STAGE_TOOL_DENY_EXTRA`（自相矛盾：阶段声明了却拿不到），import 期即报错，逼改动者显式取舍——**不靠注释承诺**（G3）。
- **效果（实跑前后对比）**：
  | 阶段 | 改前可见 | 改后可见 | 越出声明的工具 |
  |---|---|---|---|
  | `script_analyze` | 18/23 | **12/23** | 无 |
  | `storyboard_key_elements` | 18/23 | **13/23** | 无 |
  | `storyboard_shots` | 18/23 | **15/23** | 无 |
  | `storyboard_audio` | 18/23 | **14/23** | 无 |
  | `write_media_prompt` | 18/23 | **13/23** | 无 |
- **回归测试**：`test_production_prune.py::test_stage_child_face_equals_declared_tools`（各阶段可见面 ∩ `MAIN_AGENT_DENY` ≡ `stage_tools(stage)` ∩ `MAIN_AGENT_DENY`，事故编号 2222/Q5）+ `test_stage_deny_never_starves_declared_tools`（反向钉：**防收得过头**——任何阶段自己声明的工具不得进自己的 deny 集，否则断链；1111 批 `script_analysis_report` 未授予即为前例）+ `test_subagent_stage.py::test_stage_deny_drops_read_skill_only` 更新。集成测试 `test_stage_delegation_injects_only_stage_section` 随语义修正：`write_media_prompt` 不建组（该阶段 `_STAGE_TOOLS` = add/patch_draft），改为预置分镜结构 + `add_draft` 落卡（与 2222 真实顺序一致）。
- **性质**：这是**约束下沉**（`docs/GOVERNANCE.md` P2「能被代码机械校验的一律实现为代码校验」），排查的是**散文与工具面不一致**，**不是**新增一句「子代理不要越权」的散文禁令。
- **未改动**：`document_write` / `script_analysis_report` 等非故事板工具**不收**（2222 实证越界恰好发生在故事板写入面；避免误伤未来阶段的落文档需求）；`data/skills` 一行不改（冻结#16）。
- **验证**：`python scripts/acceptance.py --quick` 全绿；`tests/unit` + `tests/integration` 中受本批影响的 56 个用例全绿（41 个 adapter/网络类失败经 stash 对照确认为**改动前既有**、与本批无关）。

### 2026-09-20 · 仓库卫生批（AI 工具目录一致化 + docs/architecture 不入库 + IDE 缓存 worktree 全回收、清偿 D-13）
- **裁决（用户，2026-09-20）**：AI 工具目录「全部删除、只留 qoder」；docs/architecture「留着但不 git」；「工作树可以删了」。
- **改动**：
  - `.gitignore`：「系统与编辑器」组补 `.workbuddy/.trae/.zcode`（此前 `.codebuddy/.qoder/.claude` 已忽略，三处漏网致工具目录处理不一致）；加 `docs/architecture/`（架构可视化插件派生的 .structurizr/.dot 图，README 自述「以宪法为准、可再生」，本地保留不入库，同 `scripts/skill_scan_report.md` 运行产物口径）。
  - 移出误提交：`git rm --cached` `.trae/documents`、`.zcode/plans`（AI 工具自动生成的 session plan、非项目文档、无引用）；本地删 `.codebuddy/.workbuddy/.trae/.zcode` 四目录（文件枚举确认为旧架构/工具残留，`.claude` 本就不存在，`.qoder` 保留）。
  - **worktree 回收**：`git worktree list` 7 个 detached-HEAD 缓存工作树（`.codex/` ×1 + `.qoder-cn/` ×6）全部 `git worktree remove`。删前体检：两 HEAD（`6af2b21`/`8f3bda3`，08-05/06 旧提交）均可从 main 到达（无独有提交丢失）、无一被锁（无在跑会话占用）；git 报「含 modified/untracked」者为旧架构已退役文件的过期 diff + node_modules/dist 等工具残留，经用户授权 `--force` 清除。清理后 `git worktree list` 只剩主工作树。
- **清偿**：`docs/未清偿债务清单.md` D-13（IDE 缓存 worktree 未回收）清偿要件达成、整条删除；本文件 §三 R-14 落点指针同步改指本条。
- **红线**：仅动仓外 IDE 缓存 worktree 与被忽略的工具目录，不碰主工作树源码；**分支未动**（用户未点；D-13 曾列保留的 `backup/pre-repair-0812`/`backup/pre-skillcontext-20260813` 与有 3 独有提交的 `rescue/deepseek-v2-0806` 均原样保留）。
- **验证**：纯 git/文档卫生，无 Python/前端源码改动（pre-commit 钩子 skip）；`git worktree list` 只剩主工作树。

### 2026-09-20 · 混乱2 双删批（8888 Q3 病根：iron_rules「不跨阶段预收」 ⟂ 冻结#16「缺项合并一次问询」矛盾两边双删）
- **背景（审计报告 `docs/指令混乱审计报告-20260920.md` §三混乱2）**：8888 Q3 取证（trace `11f56fcab5ff` step 2）证明模型开场把画幅/时长/风格打包进第一次暂停，不是散文歧义、也不是模型不听话——是平台同时喂它两条互相打架的指令：① `iron_rules_header.md` L3「不跨阶段预收」（禁合并）；② 冻结#16（2026-09-08）「平台侧以缺项合并一次问询收口」（许合并）。模型逐字引用两条后自行裁决「为了效率」选了合并（「为了效率」非任何提示词写死，全库 grep 确认）。flova L987 权威口径：不依赖剧本的全局参数启动可问、依赖剧本的细节分析后问——本就不靠平台级禁令。
- **裁决（用户，2026-09-20）**：两条都删——「平台侧以缺项合并一次问询收口，这条直接删了呀」「不跨阶段预收，这个否定也删了呀」。矛盾两边一起拿掉，平台不再就「要不要合并问」下发元指令，交回 Skill 流程散文唯一管。用户已接受代价：平台对「提前打包问后阶段参数」不再有任何拦截/禁令，纯靠 Skill 散文自律（flova 同款）。
- **改动**：① `prompts/shared/iron_rules_header.md` L3 删「、不跨阶段预收」（保留「先问再做、不擅自补全」防幻觉补全核心）；② `docs/冻结与暂缓清单.md` #16 **部分翻案**——删「平台侧以缺项合并一次问询收口」句（#16 其余「data/skills 一行不改 / 装载期校验记长期规划」维持冻结），条目内标注翻案日期与 CHANGELOG 指针。
- **混乱4 自动消解（无需改动）**：删「不跨阶段预收」后，「该不该停/合并问」轴上只剩 `skill_runtime.md` DISCIPLINE #1「按流程散文自主推进」一个口径；`subagent.md`「连续推进、不权衡」属委派轴（要不要连续委派子代理），与「合并问用户」不同轴、且同偏模型自主，不再打架。
- **回归**：`test_prompt_relocation_batch3.py` 新增 `test_iron_rules_header_drops_cross_stage_precollect`（断言 iron_rules_header 不含「不跨阶段预收」防回潮 + 钉死「先问再做/不擅自补全」核心条款未被误删）。
- **验证**：定点 pytest 39 绿（test_prompt_relocation_batch3 / test_trace_sse_consistency / test_iron_rules_migration / test_industry_baseline_fixes）；全量 unit 2355 绿；`acceptance.py --quick` 全绿（GATES 14 + tsc，exit 0）。
- **红线**：Skill 零改动（#16 主旨仍冻结）；不加机械闸（不选审计报告选项 C，09-08「不加机械闸」维持）；只删不增说服性 prose（合 P2/G3）。

### 2026-09-20 · Q3② 规格收集向导残留清退批（8888 指令混乱审计：消「收集=一次收齐」退役前提）
- **背景（审计报告 `docs/指令混乱审计报告-20260920.md`）**：8888 Q3 取证发现已退役的「规格收集向导」残骸仍在架构层把「规格收集」定义为「一次性多维度收齐」，与 iron_rules「不跨阶段预收」正面对立。退役史：2026-08-31 向导机械落盘管线退役（D-08）、2026-09-12 `skill_runtime` DISCIPLINE #3「一次性分组收集」整条退役（裁决明写 group 分页交互唯一家 = `workflow_pause` options 参数描述）。
- **裁决（用户，2026-09-20）**：「Q3 的 ②，既然是残留，就彻底清理」。
- **改动（真残留 R1-R5）**：① `core/workflow_contract.py` 删 `NODE_TITLES["collect_spec"]`「制片规格收集」；② `core/workflow_runtime.py` 删 `collect_spec` 探针映射 + `_FLAT_NODES` 条目 + 同证同源注释（`collect_spec` 与 `write_spec` 同挂 "spec" 探针、功能重复；删后扫描序 `analyze_script→write_spec→review_spec`，对齐 flova「无独立收集阶段、直接写规格」）；③ **整模块删除** `core/option_groups.py`（`fill_option_groups`/`classify_option` 运行时零消费者、仅测试调用；docstring「规格收集恒为多维度×候选≥5」为退役前提）+ 删 `tests/unit/test_option_groups.py` + `test_task_transport_robustness.py::TestNewWizardDimensions` 死测试类 + `scripts/check_prompt_literals.py` 3 条陈旧维度登记；④ `skill_runtime/manifest_schema.py` docstring 删 `spec_wizard/spec_gate/script_required` 死形状声明（校验器实际不检查、data/skills 零声明）；⑤ `scripts/check_legacy_orchestration.py` 陈旧豁免注记改为退役注记。
- **改动（陈旧注释/framing C1-C9 + 混乱6）**：`planner.py`（advance_signal "wizard" 分句，该值从未被赋值）、`routes/agent.py`、`agent_loop.py`、`history_compact.py`、`fc_tool_runner.py`、`stage_probes.py`、前端 `chat-cards.css`「多维度一次性收集」/`ConfirmPicker.tsx`「规格向导」framing 中性化、`test_888_fixes.py` 退役注释更新；`prompts/gates/messages.md` TOOL_RISK_BLOCKED_OTHER 删「与制片规格写入」陈旧表述（document_write 2026-09-07 降 medium、§2.7 明写历史条款；copy ⊆ 章程仍成立，consent_copy 门禁绿）。
- **存活机制明确不删（防误伤）**：`workflow_pause` options 的 `group` 字段 + 前端 `confirm-wizard` 分页组件（09-12 裁决指定唯一家，通用分组能力，与退役规格向导无关）；`read_uploaded_doc` 读能力（flova「能读而又不读」）。
- **未动（待用户拍板）**：审计报告 §五 混乱 2（iron_rules「不跨阶段预收」⟂ 冻结#16「缺项合并一次问询」⟂ flova L987 三源口径统一）与混乱 4（裁量/硬规则/连续推进口吻收敛）触及冻结#16，本批不擅动。
- **回归**：`test_workflow_v2_contract.py` 新增 `test_spec_collect_wizard_residual_retired`（断言 collect_spec 不在 NODE_TITLES/_FLAT_NODES/_NODE_PROBE_KEYS、write_spec 仍承载 spec 探针、option_groups 模块 ImportError 防复活）；`test_stage_gate.py`/`test_workflow_v2_contract.py` 的 collect_spec 断言同步改 write_spec（语义不变）。
- **验证**：定点 pytest 118 绿；全量 unit 2354 绿；前端 vitest 996 绿；`acceptance.py --quick` 全绿（GATES 14 + tsc，exit 0）。
- **红线**：Skill 零改动（G1/冻结#16）；未加说服性 prose（P2/G3）；CONSENT_CHARTER spec_write 条目按 §2.7 用户裁决保留不动。
- **清偿**：附件正文预览退役批（本日）§二「待办：Q3 规格收集向导残留」本批清偿。

### 2026-09-20 · 附件正文预览退役批（8888 Q1：对齐 flova「剧本正文不因上传自动进主会话」）
- **背景（8888 取证 trace `11f56fcab5ff`）**：主代理开场亲读剧本全文、抢跑启动协议。根因 = `web/attachments.py::attachment_context` 向主会话首条消息注入剧本 **200 字预览** + 催读文案（“需要全文时调用 read_uploaded_doc…不要声称看不到该文档”），与 09-19 纯编排批「分析委派子代理」相反。flova 转录十 L900-907 实证：主会话只得知文档**存在/标识**，正文不因上传自动进主会话（“能读而又不读”）。
- **裁决（用户，2026-09-20）**：附件说明改为“只报存在、正文靠委派”（flova 同款）；**读能力完整保留**（非剥夺）。
- **改动**：`web/attachments.py`（删 `_DOC_PREVIEW_CHARS` 与 200 字预览注入 + 删“不要声称看不到”说教（P3 状态即数据）；文本附件只注入名称+字数+中性按需读取声明）；`tests/unit/test_attachments.py`（新增回归：正文/预览均不进主会话——断言剧本正文字串不在 ctx）。
- **“能读而又不读”机制保留（三重硬保证，本批未触）**：① `read_uploaded_doc` 仍常驻、`risk=low`、**不在 `MAIN_AGENT_DENY`**（只锁写入类），主代理任意轮可自取；② `store_uploaded_docs` 仍将全文持久化入 `state.uploadedDocs`（只删预览注入、不删存储）；③ 注入文案仍声明“正文未注入上下文，需要原文时经 read_uploaded_doc 按需读取”（防“我看不到”幻觉）。“不读”= 移除预览+催读后主会话无正文、无可抢跑对象，纯编排委派分析成自然路径。
- **验证**：定点 pytest 32 绿（test_attachments 9 + test_chat_multimodal/test_video_multimodal 23）；`acceptance.py --quick` 全绿（GATES 14 + tsc）。
- **红线**：`read_uploaded_doc` 不锁不删（能读而又不读）；Skill 零改动；非 Skill 自由对话同样按需读、行为不退化（flova 不区分场景，本批也不加技能门控分支）。
- **待办（同批取证、未动）**：Q3 规格收集向导残留（`workflow_contract.collect_spec` “制片规格收集”节点 / `option_groups` “规格收集恒为多维度一次性收齐”前提 / 前端分页向导）与 iron_rules “不跨阶段预收” 互相打架，待用户裁决是否整体清退。

### 2026-09-20 · K8 规格骨架退役批（8888 取证：规格文档臃肿根因；对齐 flova 精简散文）
- **背景（8888 取证 proj-1789839470，Skill「AI-短剧一站式生成」+《三体简短版.md》）**：用户诉「全局设定的规格文档有剧本分析的一大坨，flova 很精简」。取证 `制片规格.md`（1084 字）= K8 骨架占位节（`## 一、全局制作参数（待用户补充）`…从未被替换）+ 模型 `## 剧本结构` 剧本分析 + 两次写入重复堆积 + `。## 全局参数` 同行拼接。复现（`_merge_sections`+`_load_spec_scaffold`）钉死三 bug：①骨架编号节名与模型自由标题（`## 全局参数`）精确匹配不上 → 占位符永不替换、每次写入追加（540→1084 字）；②`_load_spec_scaffold` `.strip()` 去尾换行 + `_merge_sections` `"".join()` → 末节与首节同行粘连（粘连后不再被当标题解析）；③骨架含 `## 二、关键元素要点`/`## 三、分镜要点` 招灰节，诱导模型把剧本分析写进规格——**直接违背 `protocol.md` L13「规格只承载全局决策参数，实体细节归元素/故事板」与 09-16 R1「flova 不用结构化字段、全为自由散文」**。trace `1bb459eb6430` 实证：模型见占位 preview 困惑「也许系统自动生成了模板？」→ 重写 → 二次合并 → 臃肿翻倍。flova 对照：规格文档（20 行）= 仅全局参数 + 高层分集结构，剧本分析在独立「原始回执」，无骨架。
- **裁决（用户，2026-09-20）**：删 `spec_scaffold.md` + `_load_spec_scaffold` + `document_write` 骨架分支；规格文档回归 `protocol.md` L13 的模型自由散文（对齐 flova）；`_merge_sections` 只留 R14「保护用户手改节」用途。K8 骨架（2026-09-16「对齐 flova」）实为背离 flova，本批翻案退役。
- **改动**：删 `prompts/shared/spec_scaffold.md`；`tools/document_tools.py`（删 `_load_spec_scaffold` + 收窄 prompts 导入为 `render_prompt_section`（`load_prompt`/`load_prompt_section` 已无消费方）+ `DocumentWriteTool.aexecute` 去骨架注入/新建分支，规格新建=模型正文原样、存量仍走 R14 节级合并）；删 `tests/unit/test_spec_scaffold.py`、新增 `tests/unit/test_spec_doc_write.py`（5 例：正文原样落盘 / 8888 回归无占位无拼接无招灰节 / R14 保护用户手改节 / 非规格整篇覆盖 / 规格写入补铁律）。
- **验证**：定点 pytest 74 绿（test_spec_doc_write 5 + test_skill_flow_batch1 7 + test_hybrid_boundaries/test_skill_smoke_harness/test_subagent_stage/test_subagent_delegation 62）；`acceptance.py --quick` 全绿（GATES 14 + tsc）。
- **同批取证（未改代码，待裁决）**：8888 的 Q1（开场主代理亲读剧本、抢跑启动协议）与 Q3（首次暂停把阶段2规格参数并进启动确认）根因 = 默认 `ai_decide` 档不注入执行模式、无机械阶段闸，`skill_runtime.md` DISCIPLINE #1「顺序由你按流程散文自主推进」授予模型裁量；trace `11f56fcab5ff` 实证模型**读懂流程后仍「为了效率」主动抢跑/合并**（非散文歧义，推翻 09-08「散文歧义」定性）。flova 主代理同样持读工具但不主动读、启动暂停只问输出语言。修复方向待用户裁决，本批不动。
- **红线**：Skill 文件零改动；`_merge_sections` R14 语义不变；protocol.md L13 为规格内容唯一表述源（本批只删与之矛盾的骨架，未新增表述源）。

### 2026-09-19 · 主代理纯编排批（翻案 R4 +「工具要给全」；A' 退役）
- **裁决（用户，2026-09-19）**：①主代理改为纯编排角色——**结构性**缺少各执行阶段专业写入工具（`subagent.MAIN_AGENT_DENY` = 素材分析产出 `script_analysis_report` + 故事板结构写入 `storyboard_create_group`/`storyboard_delete_group` + 提示词草稿 `storyboard_add_draft`/`storyboard_patch_draft`），只能经 `run_subagent(stage=…)` 委派触达（`planner._compute_excluded_tools` 在 depth==0 且有 Skill 且非微调子对话时并入；one visibility = one permission）；②翻案 R4（2026-09-16「故事板翻回主代理直做」）——委派集恢复故事板三阶段（key_elements/shots/audio），并翻案「工具要给全」（2026-09-18）的执行工具部分（读工具/媒体生成仍全保留）；③**媒体生成（`image_generate`/`generate_video`）作为唯一例外留主代理、不锁不委派**——花钱生成确认卡只能主线程发行（子代理 `subagent_no_confirm`+`workflow_pause` deny 无法发卡）；④**提示词撰写与媒体生成是两个独立顺序阶段**（先撰写→再生成，非包含关系），故提示词撰写属委派集；⑤**子代理 read_skill 保持 deny**（`STAGE_TOOL_DENY_EXTRA` 不动）——子代理只能用注入的对应 Skill 分区 + 共享项目状态 + 明确传递的资源，不能自由读其他章节（规则按职责隔离、项目状态按需共享）；⑥放弃引入 dsh agent-teams（横向对等协作框架、工具面统一，与「主代理结构性缺工具」相反）；⑦时间线组装（video_assembler）本项目暂无对应工具，延后到工具落地同批登记（fail-loud 要求 _STAGE_TOOLS 非空）。
- **RC1 修复方式修正**：R4 曾以「主代理亲做 + 解禁 read_skill」修 4444 取证的分镜规则不可达（RC1）。本批改由「按正确 stage 粒度委派 + 精准章节注入 + 跨阶段数据经共享项目状态可见」化解（分镜子代理注入 storyboard_shot 章节、KE 数据在共享 StateManager），**不靠解禁 read_skill**。
- **A' 退役**：故事板委派后主代理不再亲做故事板，`core/stage_section_tail.py`（每步章节注入）+ `workflow_runtime.in_storyboard_window`/`_STORYBOARD_DESIGN_NODES` 失去消费方，删除并入 `check_legacy_orchestration` FORBIDDEN 防复活；子代理章节注入由 `_launch_subagent` 的 `tool_sections` 承接。同批退役 A' 的分析摘要常驻注入——**对齐 flova「分析一次性使用 + 历史衰减」**（此前每步常驻注入是已知 flova 分歧）：`state.analysis` 仍作探针/事件卡/前端数据源，下游阶段经共享项目状态（规格文档/故事板）+ 读工具（剧本/规格原文）按需获取。
- **改动范围（K1-K4，各自单 commit）**：K1 `subagent.py`（MAIN_AGENT_DENY + PIPELINE_STAGE_KINDS 五阶段 + _STAGE_TOOLS 补三阶段 + deny⊆stage-tools fail-loud 校验）+ `planner.py`（_compute_excluded_tools 并入 deny，skill 门控 + adjust_scope 豁免）+ 测试翻案（test_production_prune/test_subagent_stage/test_hybrid_boundaries）；K2 退役 A'（`agent_loop.py` 删尾构造与已死的 extra_messages 参数、`workflow_runtime.py`、删 `stage_section_tail.py`+`test_stage_section_tail.py`、`test_fc_leak_fakestop` 去 monkeypatch、防复活、陈旧注释更新 analysis_tools/context_builder/prompt_builder/test_skill_flow_batch1）；K3 提示词（subagent.md 注记 + DELEGATION_CONTEXT 去硬编码工具列举/明确阶段子代理读注入章节不读其他、skill_runtime.md DISCIPLINE #5/#7 删「主代理亲做故事板+A' 每步注入」）；K4 集成测试（新增 `test_stage_delegation_storyboard_shots` 端到端：主代理缺工具 + 子代理注入分镜章节 + 跨阶段隔离）+ 本条留痕。
- **验证**：全量 pytest tests/unit 2370 绿（删 test_stage_section_tail 15 例）、集成 test_subagent_delegation 4 绿；三批各自 pre-commit 受影响子集全绿（K1 664 / K2 680 / K3 6）；check_legacy_orchestration PASS。**待用户实测**（宪法 §3.1 之外的行为验证）：跑一次完整拆解，确认主代理直调 storyboard_create_group 被拒并引导委派、分镜由带 stage 子代理产出、媒体生成仍主代理带确认卡。
- **红线**：Skill 文件零改动；subagent.md L24-27 汇报格式逐字锁、protocol.md 零触碰；媒体生成/读工具/文档/确认/编排工具不锁；每批单 commit 可独立 revert。

### 2026-09-19 · D2 批（前端停滞根治 + 会话投影）与流式二期（子代理 actor 归组）
- **背景（3333 取证 proj-1789706227，2026-09-18 12:40–12:44）**：服务端 turn 3 步连续、turn/end reason=done、暂停三态落账正常，前端却整屏冻死（用户按停止+继续才救回）。核对代码后定性：「死屏」= **前端 SSE 静默死连接**——replay 首帧 / event_seq 去重 / 15s 注释心跳后端早已存在，缺客户端字节级活感与服务端连接级取证；另一路缺口 = done 帧丢失时确认卡永不出现（无账本兜底腿）。同批并入用户 2026-09-18 批准解冻的流式二期（子代理活动 actor 归组，冻结清单 #17）。
- **裁决（用户，2026-09-19）**：认可「专家绑定」方向与 dsh **state/view 分离**（session-projection 蓝图）；否决编译表+硬闸 / manifest 机器字段 / roster 覆盖闸（均为复活已退役物，撞 ADR-0004/#36B5/ADR-0007/冻结 #16 #18）；批准项 1/2/3（D2 批）+ 项 4（二期具名卡）先写计划书→审→开工（计划书已审）。红线不变：#12 ref_integrity 不扩面、#16 skill 一行不改、#18 KE 覆盖闸不加。
- **改动（六个独立 commit）**：
  - commit1 `a90dee0`：`web/sse_conn_diag.py`（SseConnDiag 连接级诊断：frames/heartbeats/last_seq/_close 首因留痕）+ routes/agent.py 接线。
  - commit2 `fadb029`：`core/session_projection.py`（四单元 interaction_pause/subagent_catalog/storyboard_progress/chat_tail，init/apply/view 三纯函数 + fold/snapshot 一致切 + 双跑 `[ProjDiff]` 对拍；只读不写，Rule 3 不动）+ `GET /api/conversations/{cid}/projection`。
  - 遗留修补 `ca70078`：commit2 的两处方法内 import 撞宪法第六章（func_imports 闸红）→ 顶层化；计划书补**实现期修正④**（不设投影变更推送帧：done 帧已携暂停/决策表单，无消费方不私设通道；前端只留 pull 腿）并据实现口径校正 §四.1/§四.2/§六。
  - commit3 `236df09`：`lib/sse-events.ts` parseSseStream +onChunk（字节级活感钩子，注释心跳帧零事件也算活）；`lib/sse-connection.ts` 看门狗（静默满 45s = 3× 心跳跳闸）+ event_seq 断口跳闸，catch 侧把 trip 消费为可重连（区别于用户取消）；`stores/chat/projection.ts` + `api/conversations.getConversationProjection` + `messageActions.applyPauseFallback`（末条 agent 消息无载体才挂暂停卡，幂等不双挂、不跨用户消息复活、选项面缺 label 归一丢弃），resume/focusConversation 接兜底腿。
  - commit4 `d810dda`：`core/planner._launch_subagent` 包 tagger（子循环每帧加 `subagent={cid,stage,label,depth}`；只加字段不改原 type/payload，一期消费方零感知；on_event 空不包装；降级 cid="" 仍打标）+ `core/sse_events.SseSubagentMeta` 与三帧可选字段 + `scripts/gen_api_types.py` 重生成（未手改生成物）。
  - commit5 `1fb7fd7`：`stores/chat/subagent-actors.ts`（一子一卡：三态/步数/子工具名单 + 账本 name=subagent_actor 槽位，不入 countableItems 防一次委派算两次）+ `lib/sse-events` 分流（带标记的 tool 帧不落普通工具卡；actions_applied 保留故事板腿另计步；父 run_subagent 起止交 actor 域按锚点 id 认领收尾）+ `SubagentActorCard.tsx` + AgentTimeline 槽位行 + SubagentRail 消费打开请求 + `web/chat_service.py` 重建 actions_applied 帧时保留 subagent 打标。
  - commit6（本条）：`docs/前端体验规范.md` §二补「子代理 actor 卡」「SSE 断流自愈」两条 + §四台账 #22/#23；`docs/未清偿债务清单.md` 登记 **D-21**（投影消费方未切换、旧折叠未删——删旧前提 = 双跑 `[ProjDiff]` 干净，而 snapshot 端点尚无实跑取证，故本批**不删**）。
- **验证**：各 commit 过 pre-commit 受影响子集；新增前端单测 4 文件（活感/断口 14 例、投影兜底 12 例、actor 域 13 例、actor 卡组件 7 例）+ 后端二期打标 5 例；`npm run build` 绿（首屏关键路径 374.68 kB ≤ 400 kB 上限）；批末 `python scripts/acceptance.py` **全量三阶段全绿**（GATES 13 + SUITES 4 + RATCHETS 2，退出码 0）。**UI 变更待用户目测**（宪法 §3.1）：actor 卡观感 / 重连文案 / 暂停卡兜底。

### 2026-09-19 · D2 批续批（actor 卡重载重建 + 双跑对拍留痕；用户实跑反馈驱动）
- **背景（用户实跑 5555/6666 两项目反馈）**：actor 卡执行中可见、切走切回/刷新后消失。取证（logs/agent-20260919.log + [SseDiag]）：两项目任务均 `close=terminal:done`（自然收尾，非停止路径）；6666 自然收尾后卡仍在（收尾路径无缺陷），5555 的消失与期间多次项目/对话切换吻合（消息从服务端重拉即不带前端账本）——根因 = 卡槽位只活在前端内存账本。
- **改动**：①同页面会话内重建——done 收尾把 actor 绑 turn_id（`bindTurn`），`loadMessages` 重拉后按 turnId 把槽位插回对应消息的 settled 账本（锚定父委派行之后；未绑轮次不挂防跨轮误挂），步数/子工具名单全保真；②页面刷新后重建——拉 `GET /conversations/subagents` 造 static actor（步数/状态取服务端口径），按子会话 id 内嵌创建时刻落到首个 ts≥创建时刻 的轮次，子工具名单展开时懒加载只读记录（`loadTools` 幂等）；重建腿失败静默不影响历史主链；③`session_projection.snapshot` 每次对拍打一条 INFO 留痕（`[ProjDiff] 对拍 cid/auth/proj/match`）——D-21 的「干净」自此可计数，零调用不再被误当干净。
- **D-21 结论（用户问「能不能删旧码」）**：**本批不删**。两条理由：对拍样本量尚小（个位数调用，未覆盖暂停被消费等状态翻转）；四个消费方目前都不能直接切（投影单元缺字段：subagent_catalog 无 cid/steps，切 SubagentRail 会丢「点进只读记录」能力）。清偿要件已更新为：补投影单元字段 → 实跑覆盖状态翻转且 match 全真 → 逐个切消费方 → 删旧码。
- **验证**：vitest 全量 993 绿（新增 7 例：切回挂回/防跨轮误挂/刷新重建/懒加载幂等/settled 不闪失）、tsc/eslint 绿、`npm run build` 绿、pre-commit 子集 229 绿、tests/unit/test_session_projection.py 6 绿。**UI 待用户复测**：切走切回与刷新后卡是否在原轮次原位重建。

### 2026-09-18 · 3333 取证续批（D1 续跑现场轮末门控 + D3 A' 窗口恢复计划书语义）
- **背景（3333 实跑取证 proj-1789706227）**：①续跑前置块把已完成轮误标「中途中断」（chat_retry_context 把 trace 内任何失败动作当失败轮/中断点；3333 含轮内 sceneRefs 拒收的完成轮被误标，续跑恢复轮被污染）；②A' 注入窗口开窗条件被批 B 实现收窄为「KE 非空」（计划书 §五原语义 = 节点当前 OR 已完成但 review 未过），第一批 KE 组落笔的几步章节缺席（3333 模型 read_skill 自救，与 DISCIPLINE #7 相悖）。
- **裁决（用户，2026-09-18）**：D1 续跑现场只在「上一轮真未正常收尾」（turn/end reason ≠ done 或无轮闭合）时组装，轮内已恢复拒收不算中断点；Q1 启动顺序问题否决提示层禁令补丁（架构级正向修复原则，待多轮沟通）；D2 前端停滞=取证优先（复现 + 客户端日志），子代理进度事件列下一批。
- **改动**：`web/chat_retry_context.py`（+_last_turn_end_reason 轮末门控；failed_at 跳过被后续同名成功恢复的拒收）；`core/workflow_runtime.py`（+current_node_probe 只读探针、_completed_nodes 单一源 sync_run 共用、in_storyboard_window 按计划书语义重写、_node_objectively_done 评审分支只读快路防 EventLedger setdefault 突变）；回归钉 test_chat_retry_context +3 / test_stage_section_tail +1。
- **验证**：定点 pytest 76 绿；acceptance --quick 绿。待办：D2（前端停滞复现取证 + 子代理进度状态事件）、Q1/Q2①②③/Q4a 待多轮沟通。

### 2026-09-18 · 分镜章节注入与工具面修复批（2222 分镜劣化根因；对齐 flova「平台保证章节写时在场」；Skill 零改动）
- **背景（2222 实测 + trace 66aad3bc782e）**：主代理亲做故事板时 skill 章节 STEP1 读过、写 shot 时已被 3-4 万 token 稀释（15 镜单运镜、0 内切、台词脱离描述）；read_uploaded_doc 被 PRODUCTION_MAIN_PRUNE 裁掉，台词只能靠分析报告还原。根因 = 写时章节/剧本原文不在场，非模型档位（high 经 chat_models_meta 回落一直生效、档位非变量）。
- **裁决（用户，2026-09-18）**：①主代理工具面全还（退役 PRODUCTION_MAIN_PRUNE 六件；structured_output 打卡仍子代理专属；委派改协议引导非结构性强制）；②A' 阶段键控临时尾：故事板窗口（KE 起至 review_storyboard 过）每步注入 skill 故事板三章原文，经 agent_loop extra_messages 拼消息最末、不落事件流、纯函数回放自证、章节近生成端（近因效应）；③analysis 挪出模型状态快照、改走 A' 同窗口（章节前），恢复裁决③「故事板阶段注入分析、其他阶段不需要」且防双付；④write_media_prompt/script_analyze 保持委派（PIPELINE_STAGE_KINDS 不变）；⑤desc/summary 键序写闸（shot 建组 model_validator 验原始 JSON desc 先于 summary，倒序整单拒收）；⑥删冻结 #18（模型档位 UI）——R6 翻案，依据 high 一直生效、档位非变量；⑦红线：Skill 零改动、闸机/工具不写死格式、不给卡面正例、散文不检查。
- **改动**：`core/subagent.py`（退役 PRODUCTION_MAIN_PRUNE/_MAIN_READBACK_DENY，保留 _STAGE_TOOLS/PIPELINE_STAGE_KINDS）、`core/planner.py`（_compute_excluded_tools 删生产轮裁剪块）、`core/fc_tool_runner.py`（拒收路由去「经委派」分支）、`core/workflow_runtime.py`（+in_storyboard_window 只读窗口判定）、`core/stage_section_tail.py`（新增：A' 尾构造 = analysis 段 + 故事板三章原文，纯函数）、`core/agent_loop.py`（每步构造 A' 尾经 extra_messages 注入、不落库）、`state/context_builder.py`（模型/降级快照摘除 analysis、删 _build_analysis）、`core/state_delta.py`（_NON_GROUP_KEYS 去 analysis）、`tools/storyboard_tools.py`（CreateGroupInput +_desc_before_summary validator）、`prompts/planner/skill_runtime.md`（纪律5/7：read_skill 降级为查阅非当前阶段/其他 Skill）、`core/prompt_builder.py`（stage_note 退役注释澄清非复活）；前端徽标（批 D：GroupCard 徽标移右上角 + 删「分镜」角标）。
- **验证**：全量 pytest tests/unit 2366 绿、acceptance --quick 全绿（GATES 14 + tsc）；回归钉 test_stage_section_tail（窗口门控/纯函数确定性/不突变 state/零产出引导/analysis 段在章节前）、test_create_group_key_order（键序正序通过/倒序拒收/非 shot 不校验）；批 A 同步更新 test_production_prune 等 5 测试文件（工具面反转断言）。批 D 前端 build 通过；用户目测（宪法 §3.1）2026-09-18 通过（分镜卡：右上「分镜」角标已删、summary 徽标移右上角）。批 B 章节注入的运行时人工实测（跑故事板核对每步章节在场）由用户后续自测。

### 2026-09-17 · flova 对齐批：shot 摘要徽标字段 + 标题契约 + sceneRefs canonical 去重（7777 分镜对齐驱动；Skill 零改动裁决）
- **背景（7777 实测 + flova 九图取证）**：7777 新跑分镜形态（单【镜头设计】+裸名引用+编号标题+sceneRefs 双份 chips）与 flova  diverge。trace 三跑（1c5dde11/2db11f68/194a1f53）对照证明形态由写入侧契约决定而非 Skill 文本（同 Skill 四跑四形态）；flova 机制 = 两通用载体（desc 自由文本 + 模型填写落库的 summary 徽标字段，编辑 desc 不重算）+ 平台标题契约（Shot_+描述、无编号）+ UI 只渲染。
- **裁决（用户，2026-09-17）**：①新增 shot summary 字段（建组必填、缺失整单打回重填=写闸；标题旁徽标位渲染、双击可编辑；desc 编辑不重算；空回落 duration=D2）；②平台层标题约定（一句话描述、平台补 Shot_、禁镜号/场号）+ 显示层剥存量 leading 编号令牌（D1=标题保持双击可改）；③sceneRefs 三源合并 canonical 去重（键=strip_type_prefix）+ 显示层兜底去重（存量不做 sqlite 手术）；④场景 chips 行保留（Skill 要求裁决）、元素引用裸名显示（K7 维持）；⑤**Skill 零改动且禁提改 Skill 方案**；⑥Audio_ chips 不纳本批。
- **改动**：`tools/storyboard_tools.py`（CreateGroupInput.summary + 写闸 + 标题约定描述 + 三源合并去重）；`state/storyboard_ops.py`（ALLOWED_GROUP_FIELDS +summary、dedup_scene_refs、patch 同口径）；`state/context_builder.py`（summary 入状态）；前端 `types/index.ts`、`GroupCard.tsx`（徽标位=summary||duration 回落 + 编辑接线）、`GroupHeader.tsx`（sb-duration 双击编辑 summary + normalizeDisplayGroupTitle）、`SceneRefsChips.tsx`（显示去重）、`desc-ref-utils.ts`（normalizeDisplayGroupTitle：剥容器前缀+迭代剥镜号/场号令牌，守卫「二维空间平面」类数字开头名）、`left-panel.css`（.sb-duration-input）。
- **验证**：定点 pytest 152 绿、定点 vitest 48 绿、npm run build + size gate 绿、批末 acceptance 三阶段全绿（GATES 13 + pytest/vitest/tsc/eslint + cov/fe_cov 地板）。回归钉：写闸拒收不建组 / summary 落库 / canonical 去重 / patch 白名单 / 徽标回落与双击编辑 / 标题归一守卫 / chips 显示去重。待办：用户 7777 重跑实测；分镜卡目测（宪法 §3.1）已随 2026-09-18 批 D 目测一并通过。

### 2026-09-17 · badgeLabel 类别标识全链退役批（用户裁决：卡片右上标识直接删除）
- **裁决（用户，2026-09-17）**：keyElement 组右上类别标识（badgeLabel）全链退役——不修锚点表、不开模型自填通道（6666 调研修复候选点 #3/#4/#5 作废）；存量数据只读透传不显示。
- **改动范围**：前端 GroupCard keyElement badge 恒空 + GroupHeader saveBadge 摘 badgeLabel 分支 + board-edit/types 摘字段（上一会话工作区改动承接）；后端 storyboard_tools 建组推导调用点删除、storyboard_ops 退役 normalize_badge_label/_BADGE_ANCHORS、ALLOWED_GROUP_FIELDS 关写口；test_create_group_badge.py 删除、GroupCard-badge.test.tsx keyElement 断言翻为「无徽标 + 存量 badgeLabel 不显示」；docs/前端体验规范.md §二分组卡条款 + 台账 #10 同步翻案。
- **保留**：分镜固定「分镜」角标、音频时段徽标及其编辑面不动（本裁决退役范围仅 keyElement 类别标识）。
- **裁决（用户，2026-09-17 续）·标题容器 ID 约定**：组标题 = 类型前缀+裸名（Element_/Shot_/Audio_，前缀=平台容器 ID 约定，名字=模型写）；写口归一（后端建组 normalize_group_title(title, cat_key) 先剥旧前缀再补类型前缀，含 6666 实证连字符支缺口修复；前端改名 renameGroupLocal 同契约 canonicalGroupTitle）；**显示层只显示裸名**（normalizeDisplayTitle 剥容器/中文类别前缀含连字符式）；存量数据不迁移（显示层读时剥离兼容）；状态注入标题保持存储原样（防存量引用口径分叉）。
- **裁决（用户，2026-09-17 续）·标题机制收敛纯结构性（对齐 flova，废词表）**：上条写口「先剥旧前缀」的词表映射退役——normalize_group_title 改为幂等补类型前缀、名字原样照搬（模型写什么名字就是什么名字）；显示/引用匹配只剥三个结构性类型前缀（strip_type_prefix / 前端 stripTypePrefix，退役 b6011a5 去下划线口径）；约定承载点 = 建组 schema title 字段正向契约（flova 式平台侧约定）；存量数据原样不映射。
- **裁决（用户，2026-09-17 续）·desc 平台零约束**：desc 全散文、不限字数、模型自由发挥、格式归 Skill；K3 批 context_builder 单 shot ≤200 字注入截断退役（A 档全文注入；B 档 _compact_snapshot 超预算压缩句柄保留）；不加任何 KE desc 注记；三类组一律。
- **裁决（用户，2026-09-17 续）·desc 零引导**：平台措辞不得含产出形态引导——skill_runtime.md DISCIPLINE #7 「消化进产出散文/不得照抄章节小标题」引导子句退役（保留先读章节+防臆写）；subagent.md DELEGATION_CONTEXT 同种子句退役（保留「方法参考」定位）；P1-D 部分翻案（仅翻引导子句，定位语与 L24-27 逐字锁不动）；产出形态唯一表述源 = Skill 章节。续裁：否定式元陈述（「平台不加引导」类）也不加，只陈述事实。

### 2026-09-16 · P2-J 修订裁决 R1-R6 留痕批（R4 故事板翻回主代理；#1 结构化字段废弃）
- **裁决（用户，2026-09-16）**：R1 废弃 P2-J #1「结构化字段」路线（flova 不用结构化字段，分镜全为模型按 skill 自由发挥的散文；方案必须 skill 无关，核心=让模型遵守 skill 要求）；R2 #3 改「给子代理工作台状态、默认不裁剪」（flova 实证不裁剪）；R3 #5 维持裸名 auto-binding（对齐 flova 渲染期 chip 绑定）；R4 故事板设计从委派子代理翻回**主代理直做**（flova 唯一重大不一致=故事板设计在主代理，7 份转录一致）；R5 #2/#4/#7 维持原口径；R6 模型档位 UI（#6）不做、冻结。
- **RC1 根因证据（4444 项目 proj-1789551900-6edffa00 取证）**：委派轨迹 f5aa924e9f93 step2 仅带 stage=storyboard_key_elements，系统只注入 `<storyboard_key_elements>` 章节（SKILL.md:60-67）；承载 shot 规则的 `<storyboard_shots>` 章节（SKILL.md:69-112：空间锚点卡/分镜语法三件套/内切镜/自检清单）**从未注入**，且 stage 模式 deny read_skill → 子代理物理读不到 shot 规则，只能回落委派任务文本的有损摘要（「含景别/运镜/时长」）产出 32 条「单行内联标签 blob」desc（零锚点卡、缺机位、无内切镜分段、尾部方括号令牌与 KE 标题失配）。根因性质=结构不可达而非缺字段 → 修复方向=执行主体与上下文连续性（主代理亲做 + read_skill 解禁 + desc 接地），非加 schema。
- **改动范围（K1-K8 批，计划书见 .qoder/specs）**：K1 路由翻转（subagent.py 委派集=script_analyze/write_media_prompt；_MAIN_READBACK_DENY 去 read_skill；planner 退役 _ANALYSIS_INJECT_STAGES）；K2 skill_runtime.md DISCIPLINE 增通用纪律条；K3 context_builder CAT_SHOTS 补注 desc（≤200 字/shot）；K4 裸名 auto-binding；K5 child_ctx state_builder 通道（不建裁剪表）；K6 structured_output 打卡 + R6 豁免退役；K7 标题收敛；K8 规格脚手架。
- **红线**：Skill 文件零改动；旧数据不迁移（读时兼容）；subagent.md/protocol.md 逐字锁零触碰；每批单 commit 可独立 revert。

### 2026-09-15 · 8888 委派失踪批（子代理线程落盘 + 委派失败可见性）
- **背景（8888 项目 proj-1789413853-5c6e867f 实测）**：用户报「子代理直接没派出去」，左栏「还没有子任务」。四路交叉取证（traces / logs / sqlite / 隐藏线程事件流）定案：**子代理确实派出去了**——主 trace `a672dce96031` step4 reasoning 明写「委派分镜拆解给子代理」，子 trace `ce3beb8da396`（parent=主 trace）事件流 `conv-1789414081-48c32230.jsonl` 27,952 字节 / 19 事件，子代理干完两步（读原著 + 10 组设定全文），死于上游 504。四项缺陷 + 一项非缺陷：
  - **A（状态层）**：`create_scoped_conversation` 忽略 `save()` 返回值 → 版本闸命中时线程元信息只活内存（log 03:28:01.717「磁盘账本 35 新于本实例已知 34」），盘上 `conversations` 只剩 `conv-main` → `GET /conversations/subagents` 返空 → 左栏空。
  - **B（状态层）**：`save()` 成功仅 DEBUG、冲突不报写入方身份 → 两次版号递增在 INFO 级日志零痕迹，事后无法指名对手方实例。
  - **C（core 层）**：`run_subagent` 派发不兜异常 → 委派中断在 trace 零留痕（主 trace step4 只有 `model_reasoning`，无 `run_subagent` action）。
  - **D（core + 前端）**：`agent_loop` finally 的 `append_turn_end` 不传 reason → 恒 `"done"`；`thread_status`「有 turn/end 即 completed」→ 子代理崩死仍显示「已完成」。
  - **E（非缺陷，不改码）**：三次尝试各约 60s 整 = 上游 ALB 网关 60s 掐断（低于本项目 `llm_timeout=120`/`llm_stream_timeout=180`），属「首字节 >60s」型。
- **改动（5 批独立 commit，全落平台层，不改 Skill、不改 `prompts/`、不新增门禁）**：
  - 批 A `state/conversation_ops.py`：落 `_persist_new_conversation` 单点（`create_conversation` / `create_scoped_conversation` 同策略，G4）——追加前 `flush_save` 冲刷在途增量；`save()` 被拒则 `_replay_conversation` 以磁盘为基、按 id 幂等并入 `conversations`（append-only 注册表，语义可交换）再写一次为限（防活锁）；仍失败抛 `StateConflictError`。调用点既有语义不变（`planner._launch_subagent` `except Exception` 降级不落流、`routes/conversations.py` 微调线程走 409）。**否决**内存整板覆盖（抹对手方新内容）与直接再 save（`save()` 拒绝时已同步 `_known_version`，二次必放行 = 调用方全赢、回退用户 1 秒前整板编辑）。
  - 批 B `state/manager.py` + `state/save_ops.py`：`_instance_tag`（global / `task:<pid>`），`save()` 拒绝 WARNING 追加「本实例=」、成功 DEBUG 升 INFO（项目 id / 版号 / 标签）；不改返回值契约。
  - 批 C `core/fc_tool_runner.py`：`_record_interrupted_call`（与 `_record_cancelled_call` 同形）——独占派发段 `except GenerationCancelled` 后加 `except Exception`、并行桶 `_first_exc` 成员，非取消异常先记 SSE/trace（ok=False）后**原样上抛**（不吞为 `ToolResult(success=False)`，GOVERNANCE §五「错误信封必须抛错」+ `kind=upstream` escalate 不变）。
  - 批 D `core/agent_loop.py` + `core/session_log.py` + 前端：轮内 `_turn_end_reason`（done/stopped/cancelled/error 四出口真值）随 finally 落 `turn/end`；`thread_status` 看最后一条 reason≠done → `failed`；前端 `SubagentThread.status` 补 `'failed'`、`SubagentRail` 文案「已中断」、`middle-panel.css` 用 `--color-danger` 语义色。
  - 批 E：本条留痕 + 债务登记 **D-20**（同项目双 StateManager 实例并发整板写：批 A 只保 conversations 注册表、批 B 补取证，`documents`/`interaction`/`flowEvents` 等无合并语义的整板并发覆盖根治待写权/合并专项）。
- **上游 504 不改码裁决（E-1）**：既有机制已覆盖——`adapters/retry.with_retry` 2 次指数退避 + `notify_stream` 前端可视 + `agent_loop` escalate + SSE 错误信封；可用杠杆是既有配置而非代码：`model_policy` 的 `subagent` 档可换到无 60s 网关限制的供应商（`planner._launch_subagent` 已支持按档接管子级模型/思考档）。单次委派范围切批（按场）归 Skill/委派策略层引导，不硬编码进代码/工具描述（G1：不以降低 Skill 要求迁就系统缺陷）。
- **验证**：新增 test_conversation_registry_persist（批 A 5 契约）+ test_subagent_run_subagent 委派降级 / test_save_conflict_forensics（批 B）/ test_fc_interrupted_trace（批 C 独占+并行）/ test_agent_loop_turn_end_reason（批 D 四出口）+ test_session_log thread_status + SubagentRail.test.tsx failed 渲染；批末全量 `acceptance.py` 三阶段绿；UI 变更 `npm run build` 干净（首屏 361.97 kB < 400 kB），待用户目测确认（宪法 §3.1）。
- **假设**：8888 现场不再复现（服务 03:36:46 重启后无新请求）；对手方写入者定性为「全局单例路径并发整板写」，但批 B 前无法从 INFO 级日志指名具体路由——批 B 即消除该取证盲区，本批不据未证实假设改写权模型。

### 2026-09-15 · 分镜 roughDesc 双通道退役批：分镜正文唯一载体 = desc（6666 实测「分镜设计不完整」驱动）
- **触发（6666 项目 proj-1789396735 实测）**：阶段子代理批实测「重新拆解分镜」后用户报「分镜设计不完整」。dump 建组入参 + trace 铁证（ts=1789407494「重新拆解分镜」，35 actions / 9 llm_calls）：主会话先 delete_group×17 再 create_group shot×16，**16 张全部 `desc_len=0 / rough_desc_len≈314`**——完整分镜内容全落进 roughDesc、desc 空；而前端展示唯一认 desc（上一批已移除 roughDesc 简介行），内容落进盲区 → 用户看到 16 张空壳卡。
- **根因**：`CreateGroupInput` 有 `rough_desc`（"粗略描述 shot 用"）+ `desc` 双写口，建组落库 `new_group["roughDesc"]=params.rough_desc or params.desc` 而 `desc` 恒取 `params.desc`；skill_docs 默认 Skill 又写矛盾句「shot 只写 title+sceneRefs+roughDesc+duration，完整镜头格式写在 desc」——既点名 roughDesc 又说完整格式写 desc，模型把全文塞进 rough_desc。与 write_media_prompt 跨阶段污染（阶段子代理批）不同源，是 desc/roughDesc 双通道歧义。
- **改动（做减法，Skill 零改动）**：`tools/storyboard_tools.py`（CreateGroupInput 删 rough_desc 入参、删 roughDesc 落库写口、[元素名] 令牌解析只扫 desc、desc 字段描述点明「shot 完整镜头设计唯一载体」、工具描述去 roughDesc）；`state/storyboard_ops.py`（ALLOWED_GROUP_FIELDS patch 白名单删 roughDesc 写口）；`web/skill_docs.py`（默认 Skill 建组指令删矛盾句 roughDesc）；`web/stores/studio/board-edit.ts`（**前端漏网写口**：renameGroupLocal 对 shot 的 patch.desc 原写 roughDesc，改写 desc——ShotDescEditor 编辑的正是 desc，否则用户手动编辑分镜正文丢失）。存量 roughDesc 数据只读保留（context_builder 照常注入、models/routes fossil 字段不动）。
- **存量双坑发现（待用户裁决）**：6666 现存 16 张卡的 roughDesc 内容不仅落错字段，且被 write_media_prompt 模板污染（16/16 命中 No subtitles / 【禁止】 / tone / <音效>，三件套/景别/内切镜 0 命中）。且该次真实拆解**未走 stage 子代理委派**（主会话直接建组、本轮无 read_skill），污染来自主会话更早轮预读的常驻上下文——stage 结构隔离只在模型带 stage 委派时生效，主会话直干活仍靠纪律第 5 条软约束。故简单 roughDesc→desc 迁移会把污染内容搬进 desc；建议重拆（现 rough_desc 已拒收，内容必落 desc）。
- **验证**：test_create_group_badge 加「拒收 rough_desc」钉 + 新建卡不产 roughDesc 断言（修正原 `[0]` 抓 demo 预置卡侥幸通过 → `[-1]` 抓新建卡）；board-edit 加 renameGroupLocal shot→desc 回归钉（studio-domains）。全量 pytest 2360 绿、全量 vitest 115 文件 919 绿、tsc/build 干净、acceptance --quick 13 GATES 全 PASS。**7777 实测通过（2026-09-15）**：新跑《太阳系二维化.md》拆解，分镜 desc 全满（280~396 字）、`roughDesc=0`、零空壳（trace 建组入参 `rough=-`）；desc 为干净 storyboard_shots 格式（空间锚点卡分行 + 动作对白带具体台词 + 「内切安排」多内切镜），污染探针（No subtitles/【禁止】/tone/slow/lingering）全 0。

### 2026-09-15 · 阶段子代理执行器试点批：run_subagent 加 stage，章节精准注入（对齐 Flova 章节隔离；部分翻案 2026-09-11 批③A）
- **触发（6666 项目实证）**：分镜 desc 被套用 write_media_prompt「单 shot 视频提示词模板」（【禁止】No subtitles / slow→lingering / (with X tone) / <音效> / 【时长】）——会话记录铁证：模型建组前 read_skill 序列一次性预读到 write_media_prompt（script_analyze→ke→shots→audio→image_generate→write_media_prompt→建组），提示词模板抢了分镜设计的方向盘。Flova 同 Skill 无恙因其运行时把各章节分别注入对应阶段子执行器（结构隔离）；本项目单一编排模型共享上下文，预读即常驻。平台侧引导源两处：ReadSkillInput.section 示例词「提示词写法」+ 纪律第 5 条倒序示例（写提示词/设计故事板）。
- **用户裁决（2026-09-15）**：①走路线 A（Flova 式阶段子代理，非路线 B 单模型章节生命周期）——核心诉求是子代理分摊长剧本上下文（主会话防爆）+ 章节隔离防污染；②主会话/普通子代理/read_skill 三样现状能力全保留（并存格局）；③试点先行：只开 script_analyze / storyboard_shots 两个最吃上下文的阶段，铺开批照模子加其余五个。
- **翻案登记**：2026-09-11 批③A「具名类型退役→通用单一子代理（对齐 dsh）」部分翻案——生产阶段委派恢复具名 stage（对齐 Flova）。与已退役被 FORBIDDEN 锁死的「机械执行器」本质不同：发起方=模型经 FC 自主委派、复用同一 run_agent_loop + guard 闸机链、无 exec_*/drive_turn 符号（check_legacy_orchestration PASS 自证）。不做机械强制（架构红线：不加 Flova 没有的闸）：模型仍可不带 stage 自己干，采用率靠结构甜头（章节自动全文注入省往返）+ 文案引导。
- **改动**：`core/subagent.py`（PIPELINE_STAGE_KINDS 试点枚举 / resolve_stage 未知回落通用不阻断 / STAGE_TOOL_WHITELIST = 通用面 − read_skill 断跨阶段预读 / build_subagent_task 阶段标注行取 STAGE_LABELS）；`core/planner.py::_launch_subagent`（带 stage → registry.tool_sections 精准注入该阶段章节全文替代 8000 字全文截断，章节缺失回落截断路径；不带 stage 现状零改动；子会话 meta 记 stage:名）；`core/fc_tool_runner.py`（launcher 透传 stage）；`tools/document_tools.py`（RunSubagentInput.stage 正面契约描述 + 工具描述补 stage 甜头；ReadSkillInput.section 删「提示词写法」示例词）；`prompts/planner/subagent.md`（SUBAGENT_POLICY 阶段委派引导 + DELEGATION_CONTEXT 按注入章节执行 + ③A 翻案登记）；`prompts/planner/skill_runtime.md` 纪律第 5 条（删倒序示例词 + 补「只读即将执行的当前阶段章节、禁预读后续阶段」边界——主会话直干活同受约束）。
- **顺带收益已核实**：假停机械续跑的 ctx.skill 从项目 usedSkills 解析（父子共享 StateManager），子级天然生效无需接线。
- **验证**：新建 test_subagent_stage 6 例（stage 归一/白名单收紧/精准注入不走截断/回落路径/通用形态防回归钉/meta 记阶段）+ 集成 stage 端到端 1 例（真实 Skill 文本切割：分镜子代理含「分镜语法三件套」探针、零含 "No subtitles"）+ 契约 launcher 扩参；定点 35 绿、全量 pytest 2359 绿、check_legacy_orchestration PASS、acceptance --quick 全绿；run_subagent FC schema 实证含 stage；前端零消费 subagent_kind（纯后端批）。**7777 实测通过（2026-09-15）**：trace 铁证模型对分镜拆解委派带 `stage='storyboard_shots'`（ts=1789411437，task=《太阳系入画》），子级仅注入该章节、read_skill 已摘 → 产出干净 desc；与 6666 旧跑（主会话直干、desc 空+write_media_prompt 污染）构成正反样本。存量 6666 已由用户删除、重建 7777 重跑，处置问题自然消解。

### 2026-09-14 · 假停机械续跑批：词表整体退役 → 结构性判定 + 契约收拢（1111 实证驱动；翻案 2026-09-10「模型自决收尾即收尾」）
- **触发（1111 项目 proj-1789356570 实证）**：单会话 6 次假停（主会话 4 + 子代理 1 + 尾轮 1）签名完全一致——前几轮全部 `finish=tool_calls` 健康执行，收尾轮必 `finish=stop applied=0`，全部死在批边界「汇报行」之后；词表对实测 5 种句式（接着落/继续登记/先读取已落盘/派给子代理/继续场二中段）**全部不命中**，开关默认关连按钮兜底都不触发。根因三层：契约多出口（纪律 6 的「一轮一批」被模型读成「一回合一批」）× 汇报行 EOS 着弹点 × 中转对话档模型 stop 校准松；coding agent（Claude Code Stop hook / Codex v0.124 Stop 事件 / dsh）机制同源而假停不显，差在契约唯一出口 + 无汇报行 + 模型档位。
- **用户裁决（2026-09-14，全部同意一起办）**：①词表判定无维护价值，整体退役；②机械注入续跑改为结构性判定并加开关（对齐 dsh Stop hook）；③契约收拢（停轮唯一出口 + 工具间汇报行禁令）；④翻案 2026-09-10「零工具纯口头完成轮不驳回续跑」——纯文本收尾轮在 Skill 流程中不再被无条件信任。
- **结构性机械续跑（dsh Stop hook decision:block + reason 注入同款）**：判定 = Skill 进行中 + 不含工具调用的纯文本收尾轮（`text_round_streak==0`）+ 开关开 + 未达上限；连续第 1 轮 → `continue_turn` 机械续跑（注入模型原文 + FAKESTOP_RESUME_NOTE「已完成请再总结，否则继续下一批」）；连续第 2 轮（streak≥1）→ 真完成放行；工具轮归零 streak；cap = `FAKESTOP_AUTO_RESUME_MAX=2`/回合封死「文本↔工具」交替拉锯。**「继续」按钮兜底随词表一并退役**（suggested_actions 仅存 retry 语义）；开关默认 **True**（关 = 不做任何检测，dsh 默认不配 hook 的放手形态）。文件：round_end_policies.py（`text_round_streak` 一等字段 + requires 重登记）、agent_loop.py（streak 跟踪 + 工具轮归零）、config.py、runtime_settings 路由、GlobalSettingsView（开关改名「假停机械续跑」+ 删词表 textarea）、api.generated/sse.schema 重生成。
- **词表整体退役**：`fakestop_promise_patterns` 从 config/settings 路由/前端/数据文件全链删除（`split_promise_patterns`/`_promise_hit` 无存留）；PUT 旧键按未知键静默忽略（接口面契约测试钉死）。
- **契约收拢（纪律 6 重写，prompts/planner/skill_runtime.md）**：「一轮一批」歧义措辞改「一次响应一批」；停轮契约唯一出口 = 不含工具调用的纯文本收尾轮只允许整个请求全部完成时出现，中途暂停必须 workflow_pause 工具；禁止批间纯文本汇报轮（进度由系统事件卡承担，说明须与下一批工具调用同一响应发出）；思考分批保留。subagent.md DELEGATION_CONTEXT 同步（子代理同假停病，1111 子代理 brief 明令反停仍早退实证）。
- **同批顺带**：max_steps 残留尸检全清（签名死参数 ×2 / 注释枚举 ×2 / 测试调用点 20 处 / `data/runtime_settings.json` stale key / 冻结清单第 11 条陈旧论据，循环本体 `while True` 早已无上限）；8888 忙闲闸 `list_running` 测试桩补齐（`_StubTM` 滞后于 chat_service 预检接线）。
- **验证**：全量单测 2253 passed（含端到端：续跑→重申完成放行 / 工具轮归零 streak / cap 封顶放行 / 开关关无检测 / 词表键退役契约）；acceptance --quick EXIT=0。

### 2026-09-13 · 9999 假停取证批 + 假停自动续跑上线（dsh Stop hook 同款门禁，清偿 2222 批待办）
- **触发（9999 项目 proj-1789295844 实证）**：18:39:47 中转断连（peer closed connection，custom-api-4/deepseek-v4-flash-0731）后 18:40-18:42 三连假停（reasoning 完整 + 一句正文 + 干净 finish=stop + 零工具调用，~5s/轮），假停兜底按钮未触发的措辞缺口再实证（「继续第二批：」「第二批到来：」「继续：」均不在 `_CONTINUATION_PROMISE_RE`）。SSE_CAPTURE 抓包 9 调用 + 原始流重放与解析器产出逐项比对 = 本地解析零丢失；34 次探针（真实 29 工具 schema + 失败任务形态「批量建组带英文 draft prompt」，含精确模型+thinking high 12 次）全部健康复刻失败——上游瞬时故障窗口为最合理解释（同中转实测掉线 1 次 + 探针中 180s 超时 1 次）。模型归属勘误：假停轮=deepseek-v4-flash-0731（用户截图实证），18:41:11 glm-5.3 TokenBudget 警告系旧标签页 context-usage 轮询（前端 agentModel() 信号跨标签页不同步）；后端聊天路径零模型 fallback 三处核实（chat_service 不换厂商 / model_fallback SSE 帧发射端退役 / tracer.record_fallback 零调用）。
- **取证批（先行落地）**：`agent_loop` 每步 LLM 响应事实日志行（`step/model/finish/fc_calls/applied/confirm/content_chars`——纯文本假停轮此前零日志，模型名全程不可查）+ `openai_compat` 抓包 footer 增 `skipped_non_data`/`skipped_bad_json` 计数（封「非 data 行/解析失败行静默跳过」盲区，34 流全 0 实证）。
- **用户裁决（本轮）**：①装 dsh 同款假停自动续跑门禁，开关放全局设置、默认关；②触发条件=话里有继续意向（扩充词表，非无条件）；③每回合上限 2 次（dsh 自身 TODO 未加上限，本实现补上），耗尽回落「继续」按钮兜底。
- **改动**：`config.fakestop_auto_resume_enabled`（默认 False，agent 组）；`round_end_policies._CONTINUATION_PROMISE_RE` 扩三族（继续[第X批][：:] / 第X批(到来|落账|开始) / 执行N个(操作|工具)，裸「继续」不匹配防误伤）+ `FAKESTOP_AUTO_RESUME_MAX=2` + `RoundEndContext.resumes_used` 输入字段（I-1.4 登记 requires）+ 策略 apply 分支（开关开未达上限置 `continue_turn`，否则按钮现状）；`agent_loop` 纯文本收尾分支读回 `continue_turn` 机械续跑（status 事件 agent.fakestopResume + assistant 原文与 FAKESTOP_RESUME_NOTE 机械提醒回喂进 messages + end_step finish=fakestop_resume + 计数 continue；物理位于确认/hard_break break 之后，确认卡优先）；`prompts/planner/feedback.md` 新 FAKESTOP_RESUME_NOTE 节；runtime_settings 四点一线（_BOOL_KEYS/Update/Read/_current_dict）；前端 `GlobalSettingsView` 新「假停自动续跑」开关节；`gen_api_types.py` 重生成。
- **清偿**：2222 批 §二「待办：假停自动续跑升级」本批清偿（实现形态差异：上限 2 次非 1 次、词表按 9999 实测漏网句式扩充非「我先把/随后开始」、问句豁免未做——策略条件已有 confirmation/wants_continue 豁免，纯问句无承诺措辞本就不触发）。
- **词表前端化（同日追加裁决）**：用户裁决词表全部由前端操作改动——`settings.fakestop_promise_patterns`（一行一条正则，出厂预填内置表）为唯一事实源，`_CONTINUATION_PROMISE_RE` 内置正则删除改 `split_promise_patterns`（拆行编译唯一实现）+ `_promise_hit`（删光 = 系统无词表，策略整体静默含按钮，无隐藏回落）；唯一护栏 = PUT 逐行编译校验非法整单 400 拒收带行号（路由内自捕获 VideoAgentError 转 ErrorPayload，照 agent 路由先例；不静默跳过对齐「数据不静默丢」铁律），启动加载遇非法整键跳过（手改文件防御）；前端 GlobalSettingsView 开关下加正则文本域（gs-textarea 样式新增）+ 行号报错提示。runtime_settings/agent_loop 改动同批，测试 61 条全绿。
- **验证**：定点 61 条全绿（test_fc_leak_fakestop 18 / test_runtime_settings_fakestop_resume 10 / test_round_end_policies / test_agent_loop）；tsc 0 error；`acceptance.py --quick` EXIT=0。UI 开关与词表文本域变更待用户目测确认（宪法 §3.1）。

### 2026-09-12 · 2222 项目诊断批：skill_runtime 纪律3（规格收集一次性分组收集）退役
- **触发（2222 项目 proj-1789205871 实证）**：规格向导答毕后模型口播「先写规格+读章节+建组」却零工具调用假停收场（模型仅生成 ~1.1K tokens：思考收尾「好，写。」+一句宣告，即在工具调用发射边界 EOS、finish=stop；初判「1.8 万巨量思考」系误读——中转把 usage.completion 报成总 tokens，深挖批已纠正）。可见思考层实录多处规则拉扯，其一即纪律3「一次性分组收集」与 Skill 章节正文「未描述外貌一律主动询问」的向导粒度冲突（模型三轮反复）。假停未触发「继续」按钮的措辞缺口（`_CONTINUATION_PROMISE_RE` 不认「我先把/随后开始」）同步登记。
- **深挖批（同日）**：假停为慢性跨模型族问题——全量 trace 25 例（09-06 → 09-12），横跨 agnes-2.x-flash / glm-5.3-flash / deepseek-v4-flash 三个模型族与多个中转，签名一致（思考尾部=批量调用宣告 → 零工具调用 → EOS，生成量仅 100~2600 tokens，无隐藏内容无被丢调用）；09-10 连续 4 次假停逼用户连说「继续/没出来呀」。高发于宣告「批量 3-5 个大参数调用」的轮。根因层（模型 chat 模板 vs 采样/中转转换）需抓原始 SSE 才能钉死；无论根因在哪层，平台侧假停自动续跑都是正确且必要的防御。
- **用户裁决**：①纪律3 整条退役——分页向导/group/一次性发回的交互契约唯一家 = `workflow_pause` options 参数描述（既有），纪律 4-7 重编号为 3-6；②dsh 对照结论采纳为方向：外部标杆对假停零检测（零工具调用即 completed），goal 会话靠 driver 注入合成用户消息续跑——本项目的假停续跑升级沿 2026-09-09 裁决仍待开工；冲突裁决学 dsh 注入层总纲（「guidance 不覆盖直接用户指令、具体优先于宽泛」），skill 文件不再内嵌优先级复述；③protocol.md 语言规则删「用户在《制片规格》显式声明提示词语言时以规格为准」复述句——优先级链唯一家 = 铁律头部，模型可见层不再复述覆盖规则（对齐 2026-08-31「语言归文档层」裁决的落地句一并瘦身）；④假停深挖结论确认后，**本批只加原始 SSE 落盘观测点，假停自动续跑等其他修复一律不动**（用户裁决原文：其他都不动）。
- **改动**：`skill_runtime.md` DISCIPLINE 删第 3 条并重编号；`protocol.md` 防虚报指针「第 4 条」→「第 3 条」+ 语言规则删规格覆盖复述句；test_iron_rules_migration / test_prompt_relocation_batch3 快照锁随钉更新（retired 增「一次性分组收集」）；④`config.sse_capture`（env `SSE_CAPTURE`，默认关）+ `openai_compat._SSECapture`（流式路径逐 `data:` 行原样落盘 `data/sse_capture/*.jsonl`，头/尾元数据行，500 个滚动清理，异常静默降级不阻断主流程）+ test_openai_compat 三钉（默认零落盘/开启全量落盘/异常路径仍有 footer）。
- **验证**：受影响单测 39 + 192 条全绿。
- **待办（未开工）**：假停自动续跑升级（含问句豁免 + 词表补「我先把/随后开始」+ 每 turn 限 1 次回落按钮）；新轮缓存 byte-0 失配排查（T1 内 85% → 新轮 0%）；SKILL「AI-短剧一站式生成」L12 语言矛盾句改写待用户裁决（frozen 文件）；（可选）`thinking_level` 配置为成本/速度优化，与假停根治无关。

### 2026-09-12 · 3333 项目事故批：结构纯净闸退役 + 工具说明 dsh 化 + 静默降级清偿
- **触发（3333 项目 proj-1789193562 实证）**：提示词编写轮 9 次 `storyboard_add_draft` 全部 ok=True 但落库 `prompt` 恒空——`strip_structure_prompt`（2026-08-06 ec7a617 引入，防提示词闸被内联绕过 + 固定五步时代的"步骤3只建骨架"假设）无阶段感知静默剥离内联 prompt，且调用点自始丢弃返回值、承诺的"回喂说明"从未发生；模型全程不知情并宣称「9 个提示词已全部写入」。同源死代码孪生 `skill_runtime/guard.py`（零消费者）。
- **用户裁决**：①剥离闸删除——数据绝不静默丢，要么拒收+回喂要么保留；②工具说明全量对齐 dsh 风格：只写正面契约（是什么/何时用/参数怎么传/返回什么），禁令句、流程纪律、恐吓性负面清单一律清除（承接方 = system 段 SUBAGENT_POLICY、Skill planner 散文、结构性保证）；③"3~5 分批"保留（上下文消耗与整批写几乎相同，真实理由是流式响应与中断安全，非上下文）；④子代理不委派 = 接受模型方差（dsh 无提醒机制），对齐后不加机制；⑤create_group/patch_draft 双路 = 增改分工（CRUD 常态），删闸后等价，无需归一。
- **改动**：`fc_gates.strip_structure_prompt` + 调用点 + 测试删除；`skill_runtime/guard.py` 整文件删除（strip_draft_prompt/strip_structure_actions/validate_prompt_hard 均死代码）+ prompt_builder 无用 import；15 个工具 description 重写（run_subagent 删「不要用于」吓退句、read_skill 删阶段→工具映射表（Skill planner 段已自带）、workflow_pause/image_generate/generate_video 等删禁令与流程句，保留"收尾批可合并"等事实）；`storyboard_create_group` 未命中 [元素名] 令牌补回喂（detail→模型 + warnings→用户可见）；`storyboard_media_to_chat` 非法 media_type 由静默归空改显式拒收。守护测试随钉更新：test_prompt_relocation_batch3 / test_industry_baseline_fixes / test_progressive_disclosure_relocation 钉子改指新正面事实句；test_capability_word_alignment 退役（对照段唯一展示层副本删除，registry 侧 PIPELINE_CAPABILITY_TOOLS 由 scan_skills 消费不受影响）。
- **上下文面板口径修复（同批前端）**：圆环/标题/各行分母统一为"单次真实请求规模 = messages 总量 + system（含 Skill）+ tools"（旧口径分母只算 messages，各行加和 130.3%，3333 实测）；「状态」遗留行退役（G3 后状态注入走轮首 source=state 事件计入消息，state_tail 恒 0）。
- **保留待裁决**：`structure_integrity_gate`（建组必须带标题 + 分镜 sceneRefs 非空且覆盖标题点名元素）——拒收型有回喂、编码真实产品依赖（跨镜一致性），建议保留，用户未否决。
- **验证**：受影响单测 181 条全绿；`acceptance.py` 全量通过；UI 变更待用户目测确认（宪法 §3.1）。

### 2026-09-12 · 事故修复：模型编辑面板 1M 挡保存从未生效（三轮闭环）
- **现象**：胶囊编辑面板选 1M 上下文不生效，重开仍显示 200K，用量圆环恒 /200K。
- **第一轮（`603c2e2`）**：context-usage 端点补 provider 查询参数（此前 window_tokens 永远查不到 chat_models_meta）；设置页 saveAll 白名单补 chat_models_meta 透传；saveChatModelMeta 失败静默改 toast；后端 providers 保存加 meta 条数日志锚点（`07ad2ea`）。缓解但未中靶。
- **第二轮**：后端日志锚点实证 PUT body 恒全 0；设置页本地快照与胶囊侧 studio store 双通道割裂——设置页 saveAll 按陈旧快照组装保存体会把 meta 洗回空。修复：saveAll 组装 chat_models_meta 以 studio store 为权威源，快照仅作兜底。
- **真凶（vitest 复现实证,`providers-meta-save.test.ts`）**：saveChatModelMeta 用 `p.chat_models_meta = list` 对 **Solid store 元素直接赋值新属性——set trap 静默丢弃**，PUT 发出的 body 从来没有 meta；自 9-08 面板批上线起保存链从未生效（后端测试 monkeypatch 绕过前端、前端无该链测试,双向盲区；日志 `[0×12]` 与 UI 乐观勾选假象叠加误导向设置页）。**修复**：改 `setState('apiProviders', 函数式 map 替换整条记录)`。辅助取证：curl 模拟前端 PUT → meta 正常落盘、context-usage 返回 window_tokens=1000000,后端全链路排除。
- **验证**：providers-meta-save.test 3 passed（PUT 携带 meta / stringify 不丢 / patch 合并不整体覆盖）；tsc/eslint 0 error；`acceptance.py --quick` 全绿（EXIT=0）。前端已重新构建,待用户强刷浏览器重选 1M 并目测圆环（宪法 §3.1）。

### 2026-09-12 · 指令体量治理批（规则按所有权归一，对齐 dsh；起因 = 1111 会话边界轮规则仲裁税 + run_subagent 零调用）
- **触发与依据**：1111 会话（proj-1789128804-70253439）实测边界轮 20–53s 的"规则仲裁税"（模型手工对账多份规则源）与委派/批次双规打架；dsh-latest 源码对照（第一方身份一句、规则按所有权分布在工具描述、无消息字数上限、Skill 摘要 500 字符截断）。计划书经用户逐条裁决（计划书文件执行后删除，本条为唯一留痕）。
- **用户裁决**：纪律2"只在暂停点停/中途一律不停"删除；"≤120字问句"双写清理由 message 实况取代；纪律6"系统附挂继续选项"随退役机制删除；protocol 暂停段/生图渠道段/能力词对照/画布规则/编号语义/开场盘点/拆解建组条款全部迁出；"3~5个"唯一家 = 纪律；回复输出纪律压缩三行（大搬）；委派仲裁句归 subagent 单一家；摘要截断 500 字符；压缩模板留一份；优先级链只在《执行铁律》文档出现（模型可见层不携带）；protocol L32 拆解建组条款直接删除；Skill 文件零改动（冻结清单 #16 重申）。
- **A 双写归一（`b998fff`）**：skill_runtime 纪律 10→7 条重编号（2/4/6 退役）；protocol.md 64→18 行；暂停契约（真停语义/调用时机/收尾批合并/同批冻结/回应三态/message 两通道实况）唯一家 = `workflow_pause` 工具描述；能力词对照迁 `read_skill` 描述；渠道优先级迁 `image_generate`/`generate_video` 描述；`consent_copy` 闸 protocol 项改迁出端防回潮。
- **B 所有权搬家（`6cff41b`）**：委派 vs 主对话批次节奏仲裁句入 SUBAGENT_POLICY（禁用场景唯一家 = 工具描述）；画布操作规则迁 `canvas_*` 描述。
- **C 摘要预算与压缩归一（`488a279`）**：Skill 清单单条摘要 500 字符展示层截断（原文唯一事实源不变）；压缩指令唯一家 = `feedback.md::COMPACTION_INSTRUCTION`（四段式交接语义并入），`compaction.md` 死模板删除。
- **缓存注记**：protocol 位于 system 前缀头部，本批使其变短——旧会话前缀一次性失效属预期，新会话不受影响；稳态命中率考核以 `scripts/cache_hit_report.py` 为准。

### 2026-09-10 · 阶段规则去代码化与流程简化批（对标 flova：代码只做安全保护 + 数据一致性，不判流程完成）
- **计划书**：`.qoder/specs/阶段去除与流程简化_task-d47.md`（用户审定，A–F 六组五批）。总原则：步数不限、不留续跑预算、不留假停检测、不留完成盖章；保留用户设计的机械停（`key_steps_confirm` 6 步 / `pause_all`）。
- **A 核心循环 + bug**：`fc_tool_runner` 成功分支补 `call_id`（成功工具结果缺 id → 虚假「未执行」占位回喂）；`agent_loop` 删步数上限全链（`max_steps`/`current_max_steps()`/`MAX_STEPS_RANGE`/步数告警/「继续完成」按钮）与 `productive_reject`/`unstamped_stop` 续跑预算、全拒收轮续跑豁免（流程推进归模型自觉）；`config` 删 `max_steps`/`subagent_max_steps`/`completion_stamp_enabled`，保留 `llm_max_tokens`；`planner` 删 `completion_stamp_enabled` 引用与子级 `max_steps` 传参。
- **B 闸机去硬编码**：`fc_gates` 删 `STAGE_ALLOWED_GROUP_KINDS`、阶段类别边界闸、单图配额（`gen_image_calls`）、`Tuple` 导入；`prompt_gates` 删 `_SHOT_PROMPT_MIN_CHARS`/`_ELEMENT_PROMPT_MIN_CHARS` 字数地板（`validate_prompt_write` 不再产生硬错误，只留音色参考软提醒）。保留 A6 sceneRefs、轮内暂停纪律、`tool_risk_gate`/`gen_confirm_gate`。
- **C 阶段判据 + workflow 契约**：`stage_probes.stage_done` 删 `structure`/`ke_media` 判据（恒 False，模型自决）；`workflow_contract` 删 `WorkflowDefinition`/`WorkflowNode`/`default_v2_workflow`/16 节点 DAG（改留 6 步评审清单 `DEFAULT_V2_REVIEW_NODES` + 平铺节点标题表 `NODE_TITLES`，机械停卡文案用）；`workflow_runtime.compile_definition` 恒 None，`sync_run` **无 DAG 退化**（按平铺节点清单 `_FLAT_NODES` 跑客观探针重算 `completed_nodes`/`current_node`，不置 `failure_state`），`ensure_run` 不再按 `definition_hash` 比对。
- **承重 bug 修复（本批自查发现）**：原 C3 只把 `compile_definition` 改为恒 None，未同步 `sync_run`/`ensure_run` —— 前者给「无 DAG」置 `INVALID_SKILL` 并返回无 `run_id` 的 run，`start_run` 随即 `KeyError`，导致 `planner.run_sync` 每轮记承重接线降级遥测、且 6 步机械停与 `pause_all` **彻底失效**（`current_node` 恒空 ⇒ 闸判据永不触发）。修法 = 无 DAG 退化 + 平铺清单重算：机械停恢复工作（`test_stage_gate` 8 例全绿），阶段闸标题走 `NODE_TITLES`（不再把裸 node_id 显示给用户）。
- **D 完成盖章退役**：`task_complete` 工具整链删除（工具本体 + 子级白名单出口 `SUBAGENT_STAMP_TOOL` + `turn_executor` 章萃取 + 审计事件 `EV_TURN_STAMP`/`append_turn_stamp` + 投影分支 + `outstanding_stages`/`_cat_counts`/`_outstanding_titles` + `recovery_policy` 两键 + `feedback.md` 四节 STAMP_* 文案 + `subagent.md`/`skill_runtime.md` 盖章措辞 + 前端盖章条 types/CSS）；依据 = 总原则「不留完成盖章」+ 组 D 标题，且核实零活消费者（D2 已先删盖章回执与冻结，工具本体只剩空返回 + 已失真的描述）。
- **E 前端**：全局设置「Agent 循环上限」→「输出 Token 上限」（`llm_max_tokens`，钳制 1024–1048576，后端 schema + 前端 + `gen_api_types` 重生成）；`SubagentRail` 轮询改**增量更新**（内容一致复用旧引用 ⇒ Solid `<For>` 不重建该条 DOM ⇒ 记录滚动不跳；新增「轮询增量更新（引用稳定化）」3 例）；「第 N/M 轮」进度段整链退役（status 参数 `max`、`chatState.roundStep/roundMax`、`parseRoundParams`/`roundPercent`、scope `round` 事件、locale 键、进度条轮次段与 CSS）；`pause_composer.normalize_option_surface` 的 `boundary_hit` 分支与 `gates_cards.system_continue_option` 退役（阶段边界系统派生「继续」项）。
- **宪法同步**：`ARCHITECTURE_RULES.md` Rule 2 两处退役表述修订（`MAX_STEPS` 读 settings → 不设步数上限；`WorkflowDefinition` 编译 → 不再编译节点 DAG）；`skill_runtime/manifest_schema.py` 的 `stages` 数组形态描述同步。
- **验证**：`acceptance.py` **全量 18/18 全绿**（GATES 12 + pytest 38.6s 2307 例 + vitest 19.9s 112 文件/891 例 + tsc + eslint + 双覆盖率 ratchet 输出新鲜产物）。注：pytest/vitest 两条首轮报 FAIL 系本机 safe-delete 钩子阻塞（见 `handover.md` 环境说明），清空 pytest 临时根 `%TEMP%\pytest-of-<user>` 后即全绿，与代码无关。
- **口径变化（需知）**：① 全拒收轮 / 产出类被拒混合轮 + `finish=stop` + 可见正文 → **不再强制续轮**（拒因已在 messages 回喂，模型自决）；② 短提示词不再被平台拒收（字数地板退役）；③ `stage_probes.current_stage` 不再越过 `structure`（结构判据退役 ⇒ 状态焦点/进度提示停留在结构档）；④ `task_complete` 工具从工具表消失（模型侧工具数 10→9）。

### 2026-09-10 · 子任务面板迁入中间面板（顶栏「子任务」入口；左栏任意点击回预览）
- **交付（用户裁决的交互改版）**：左栏第 3 Tab「子任务」取消，入口迁至顶栏「API 配置」右侧。点击入口 = 中间面板整幅切为子任务面板（列表态 ⇄ 点卡片看只读执行记录；子任务视图内点卡片不再落入预览框）；点左栏任意处（卡片 / 分组 / 空白 / Tab 按钮）或顶栏「影视工作台」= 中间面板切回预览框。
- **实现**：新增 `MiddleView = 'preview' | 'subagents'` 状态（studio store，默认 preview ⇒ 不点入口时行为与改版前完全一致）+ `setMiddleView` action；`SubagentRail.tsx` 由 `left-panel/` 迁至 `middle-panel/`（渲染归属变为中间面板）、`LeftTab` 收窄为两值；`LeftPanel` 根容器挂 onClick 回预览；`Header` 导航组新增「子任务」入口（激活高亮与「影视工作台」互斥，非工作台路由点击先回工作台）；`subagent-*` 样式块迁至 `middle-panel.css`（`.subagent-center` 全幅容器 + 宽栏内容收束 860px）。窄窗下中间栏被响应式收起时点入口不自动展开（用户裁决不做）。
- **验证**：新增 `LeftPanel.test.tsx`(3) / `MiddlePanel.test.tsx`(2) / `Header.test.tsx`(3，钉死两入口切换与互斥高亮)，`SubagentRail.test.tsx`(5) 路径同步；全量 vitest 112 文件 / 895 用例通过；`acceptance --quick`（GATES+tsc）绿；`npm run build` 成功（首屏 361.41 kB ≤ 400）。宽屏真机复测：两入口切换与互斥高亮逐项通过（窄窗下顶栏按键拥挤属既有响应式边界，非本批引入）。待用户目测反馈。

### 2026-09-10 · 正宗子代理 run_subagent 批 B1（模型 FC 发起、复用 run_agent_loop 的隔离子级；对齐 flova/dsh，非机械执行器）
- **背景**：8888 复盘——主线程单上下文既规划又逐字写内容 → 思考重、跨轮缓存断（前端均值 63.7%）。正向解法 = 把「拆解/写提示词」重活交给**模型经 FC 发起、在隔离上下文里复用同一 `run_agent_loop`、走同一 `guard_pipeline`、只回摘要**的一次性子代理（对齐 Claude Code/qoder/dsh `packages/subagent`）。计划书：`docs/会话交接-20260910-run_subagent子代理执行.md`。
- **宪法边界（澄清，非改宪）**：本批与 0818/任务#36 B5 退役的**机械执行器**（运行时替模型直跑阶段 + 绕闸 + 非-FC 通道，符号已入 `check_legacy_orchestration` 永久禁）是两类东西。run_subagent 三条全不犯：发起方=模型（FC 工具）、复用唯一循环、走同一闸机链，「模型永远唯一行动主体」仍成立；`check_legacy_orchestration` FORBIDDEN 无 `run_subagent/subagent`，扫描不命中。执行模式保持 `ai_decide`、思考照常展示、不改 SKILL.md 均不受影响。
- **落点**：`run_subagent` 属控制流伪工具（同 `workflow_pause`），schema 注册于 `tools/document_tools.py`，执行在 `core/fc_tool_runner._dispatch_tool` 按名拦截、经 **planner 轮始注入的 `subagent_launcher`**（依赖注入，fc_tool_runner 不 import planner，不成环）回调 `planner._launch_subagent`；子级用独立 `Planner`（自带独立 FCToolRunner/TurnExecutor，仅共享 StateManager），落 `create_scoped_conversation` 隐藏子会话（携 parent/kind=subagent 血缘），主线程不被灌中间步。
- **子级契约（dsh 对齐）**：工具白名单（剔花钱生成与 run_subagent ⇒ 结构防递归）+ 委派深度 `child=parent+1` 单调、上限 1、恢复态不归零 + 审批=never（`subagent_no_confirm` 复用 `_scope_auto_pause`，不发确认卡=不中断）+ 固定权限范围声明外置 `prompts/planner/subagent.md`（撞闸不重试、只回报）+ provider/model 继承父档（B1 跟随主模型）+ 结果 append-only 摘要回父（不打碎父前缀）。步数 `subagent_max_steps`（env/config 默认，**不进前端**）；总开关 `subagent_enabled`。
- **范围**：仅批 B1（无 UI 纵向切片）。B2（model_policy `executor`→`subagent` 改名）/B3（左栏子任务卡+只读记录）/B4（账本合流回归）待后续批。
- **验证**：新增 `tests/unit/test_subagent_run_subagent.py`（8）；全量 unit 2209 + integration 93 通过；`acceptance --quick`（GATES+tsc）全绿；`check_legacy_orchestration`/`check_layer_imports`/`check_fc_tool_name_literals` PASS；`gen_api_types` 同步 tool tier sidecar 新增 run_subagent 条目。

### 2026-09-10 · 正宗子代理 run_subagent 批 B2（model_policy 死角色 `executor`→`subagent` 改名 + 子代理档成活配置）
- **背景**：`model_policy` 四角色行的「执行器机械」（key=`executor`）自 任务#36 B5 机械执行器退役后无任何活跃消费者（仅 `summary` 行被 `history_compact`/`chat_opening` 读），属改了也没反应的历史残留。用户裁决：既然子代理要接管这段批量重活，直接改名「子代理」并给它真消费者，不留旧名。
- **改名与迁移**：`core/model_policy.py` ROLES `executor`→`subagent`、`DEFAULT_POLICY` 剔除该行降档默认（子代理缺省跟随主模型含思考，与「思考必须展示」一致，不再硬编 low）；新增 `migrate_legacy_roles`，`normalize_policy` 前置迁移 + `web/routes/runtime_settings.py` 启动加载将旧持久化 `executor` 行与 `executor_thinking_level` 遗值一次性归入 `subagent` 行（新键已配则旧键让位，不丢用户值）。`ModelPolicySection.tsx` 标签/提示「执行器机械」→「子代理」（**不动前端新增控件**，仅重命名现有行）。config 残留 env 字段 `executor_fast_model`/`executor_thinking_level` 不在本批范围（env 契约变更，且无消费者，留待后续）。
- **成活配置（正向设计，非死行）**：`Planner.__init__` 新增 `chat_adapter_factory` 可选注入（web 装配点传 `_create_chat_adapter`，core 不 import adapters/web）；`_launch_subagent` 接 `resolve_role("subagent")`：非空则接管子级 provider/model，空则完全继承父 adapter（跟随主模型）；思考档 `thinking_for("subagent")` 非空才覆盖，否则继承父思考。解析失败静默回落父档。
- **验证**：`test_model_policy`（含 `test_migrate_legacy_roles` + 子代理缺省跟随断言）+ `test_subagent_run_subagent`（新增两例：缺省继承 / 显式接管）全绿；tsc PASS；GlobalSettingsView vitest 8 pass；三静态门 PASS；`gen_api_types` 无 diff（model_policy 为 `Record<string,PolicyRow>` 角色无关）。
- **范围**：B1+B2 已完成；B3（左栏子任务卡+只读记录）/B4（账本合流回归）待后续批。

### 2026-09-10 · 正宗子代理 run_subagent 批 B3-后端地基（子任务线程清单 + 事件流只读记录；UI 待下轮目测）
- **背景**：B3 拆为后端地基（本轮，非 UI 可测）+ 前端 UI（下轮，需用户目测）。摸底发现：子代理在 core 内联跑、不经 web/chat_service，故其过程只进 append-only 事件流（落隐藏子会话 jsonl），而 `GET /conversations/{id}/messages` 读的是 chatMessages 列表（子线程为空）。用户选定：**只读记录从事件流派生（单一事实源）**，不双写 chatMessages。
- **补齐子级任务落流**：`planner._launch_subagent` 创建子会话后显式 `session_log.append_user_message(child_cid, task, source=user)`——使隐藏线程事件流自描述（否则只读记录缺首行任务）。
- **事件流→只读投影（core/session_log，纯函数可测）**：`project_readable_record`（取真人任务 + assistant 正文/思考 + 工具活动名单，跳过 state/feedback/media/checkpoint/turn/compaction 噪声；形状兼容 chatMessages entry）；`thread_status`（turn/end 存在=completed 否则 running，附 steps）。
- **线程清单（state 层无 core 依赖）**：`conversation_ops.subagent_threads`（筛 scope.kind=='subagent'）+ `get_conversation_scope`；`StateManager` 同名委托。事件读取（session_log）不滞进 state 层（避 state↔core 环）。
- **只读 API（web/routes/conversations.py）**：`GET /conversations/subagents`（元信息 + 经 session_log 补运行态/步数）；`GET /conversations/subagents/{cid}/record`（事件投影，非 subagent 线程 404 不暴露任意会话）。
- **未做（下一轮 B3-前端）**：主 SSE 转发轻量子任务状态事件（running 实时态）、`SubagentRail.tsx` + `LeftPanel` 第 3 Tab + 只读 `ChatFeed`（需构建后用户目测）。
- **验证**：新增 4 例（清单/scope、只读投影+状态、子级任务落流）；全量 `tests/` 2308 通过；`acceptance --quick`（GATES+tsc）绿；gen 无 diff（新路由返 plain dict）。

### 2026-09-10 · 正宗子代理 run_subagent 批 B4（账本合流回归断言；结论：无需子代理专用接线）
- **结论（核源）**：`workflow_runtime.commit_turn` 落账后走 `sync_run(state, skill)` **全量重算**，`completed_nodes` 只认客观 stage_done 探针与账本 DecisionResolved 事件（「账本无自报」）；而子代理与父**共享同一 StateManager**，其真实写工具改的就是 `sync_run` 所读的同一 `state_dict`。⇒ 子级产物天然入账、不虚报，**无需任何新接线，亦无时序缺口**（子级在父本轮内同步跑完，`commit_turn` 在其后）。本批只加回归钉死该不变式。
- **新增断言**：`test_launch_subagent_shares_parent_state_manager`（子 Planner 复用父 StateManager 对象）+ `test_external_writer_is_accounted_objectively`（外部写者落 keyElements → sync_run 认账；未在场→不虚报）。
- **范围**：B1–B4 后端全部完成。仅剩 B3-前端（SSE 实时状态事件 + SubagentRail + 只读 ChatFeed，需构建后用户目测）。

### 2026-09-10 · 正宗子代理 run_subagent 批 B3-前端（左栏「子任务」Tab + 只读执行记录）
- **交付**：`LeftPanel` 第 3 Tab（`LeftTab` 加 `'subagents'`）+ 新组件 `SubagentRail.tsx`（卡片清单态 ⇄ 只读记录态两视图，Tab 打开期 4s 轮询、卸载即 `onCleanup` 清定时器）；API 客户端 `getSubagentThreads/getSubagentRecord` 接 B3-后端只读端点；样式全语义 token（过 `semantic_colors` 门）。
- **口径**：运行态实时性由**轮询**承接（子级在父本轮内联同步跑完，父阻塞期无独立 SSE 帧可推），故本批**不新增主 SSE 状态事件**（不为拿不到的信息先建通道）。`ChatMessageItem` 与全局 chat store 深耦合（编辑/重跑/分支 affordance 必填），只读面板不复用它，另以轻量渲染 + 复用 `MarkdownBubble`。
- **验证**：`SubagentRail.test.tsx`(4) + `api-modules.test.ts`(+2)；`npm run build` 成功、bundle 360kB≤400；tsc/eslint PASS；批末 `acceptance`（GATES+SUITES+RATCHETS 18 步）全绿。

### 2026-09-10 · 完成盖章批 G（照 dsh A2 治谎报：完成必须显式盖章 + 未盖章不放行 + 按证据汇报）
- **背景（2222 现场核因）**：T4/T5/T6 三轮日志里**没有任何 `AgentLoop step=`**——模型零 `tool_calls`、`finish=stop`，而 `agent_loop` 纯文本分支把“只回一段文字”当最终答复直接收尾，于是“嘴上说建好 S9-S12 / 我重新提交 / 先把提示词写好”就什么都没发生就停了。现有防虚报是 A1 窄词表（`_PRODUCT_AUDIT` 只盯结构/规格两类产物，`_FUTURE_MARKER_RE` 豁免将来时措辞）+ 只警告不拦人，三个空子全被钻。
- **标杆结论（源码/二进制实证，非推断）**：dsh **只做 A2**（`packages/goal`：完成须经 goal 工具显式盖章 + `authority.ts` 只校验盖章资格 + 未盖章由 round-driver 续跑 + `wrapup.ts` 要求按证据汇报），**没有任何程序化产物对账**；因此本批不再往窄词表加东西（A1 保留为警告层），而是把机制换成 A2。
- **G1 盖章（不判真假、不 trap 用户）**：新控制流伪工具 `task_complete`（risk=low / detail_tier=output / 非产出类不入产出对账）；`fc_tool_runner._commit_call` 发行时将回喂数据换为**客观账本快照**（`stage_probes.stamp_receipt`：阶段完成度 + 三类草稿计数 + 规格/分析在场与否，文案单家 `feedback.md :: STAMP_RECEIPT`）并**冻结本批**（同暂停即冻结，两种控制流出口互斥）；`turn_executor` 认数据不认工具名（与 image_urls/chat_inserts 同消费口径）上抛 `completion_stamp`；`agent_loop` 据此收轮（finish=stamped，不多烧一步）并落 `turn/stamp` log-only 审计事件（使“谁在何时声称完成”成为可审计事实）。
- **G2 未盖章不放行（有界续跑）**：轮末新增两条声明式策略——`completion_stamp_gate`(110)：Skill 激活 && 本轮 applied==0 && 未盖章 && 未暂停 && `stage_probes.outstanding_stages` 非空 && 预算有余 ⇒ 不受理纯口头收尾（`continue_turn` + `UNSTAMPED_STOP_NUDGE` 事实回喂）；`unstamped_stop_notice`(115)：预算耗尽仍未盖章 ⇒ 不拦人，只入用户可见事实警告（`UNSTAMPED_STOP_WARNING`）。循环侧新增 `stamped`/`stamp_budget_left` 一等字段与 `unstamped_rounds` 计数（预算 = `recovery_policy` 新键 `unstamped_stop.max_retries=1`，与批 12 `productive_reject` 同构防打转）；续跑时回喂同为 `user/message`(source=state) 事件，保证回放字节 = 请求字节。
- **G3 接地提示（prose 单家）**：`skill_runtime.md` DISCIPLINE 第 7 条改写为「防虚报与完成盖章」（保留原「必须真的调用…才可声称完成」「状态对账」锁定措词，新增“结束本轮三个合法出口”与“只写文字不是合法收尾”）；`protocol.md` 只保留引用式短述不动（P1 双源禁绝，`test_f2_prompt_dual_source_merge` 仍绿）。**未改 SKILL.md、未改执行模式（`ai_decide` 不变）、思考照旧展示**。
- **宪法自证**：模型仍是唯一行动主体——本批只“拒接口头收尾并回喂事实”，运行时不发起任何行动（与批 9 全拒收轮续轮、批 12 产出被拒续轮同族先例）；新闸机 `completion_stamp_gate` 经用户审定本计划书时裁决设立（完整清单以 `scripts/acceptance.py` 两表为准，本轮未新增静态闸）；`check_legacy_orchestration` 符号扫不命中（新符号 task_complete/completion_stamp_gate/stamped）。
- **代价（诚实声明）**：激活 Skill 且阶段未完时，若模型发一轮零工具纯文本，会多烧一步（它下次改为直接盖章后零代价）；换到的是 2222 那类空转轮不再能静默结束。总开关 `COMPLETION_STAMP_ENABLED`（默认开，关 = 不下发工具且两条轮末策略失效，一键回滚）。
- **验证**：新增 `tests/unit/test_completion_stamp.py`（14：客观回执/冻结与回喂数据/四种不命中分支/预算耗尽警告/开关失效/循环端到端“驳一次就收”）；`test_round_end_policies` 策略表 2→4 同步；`test_recovery_policy` 键集 +`unstamped_stop`；`test_fc_leak_fakestop` 纯文本收尾断言按新语义改为“续跑一次后收尾、两步正文累计”；全量 `tests/` **2324 通过**；`acceptance --quick`（GATES 12 + tsc）全绿；`gen_api_types` 同步 tool tier sidecar 新增 task_complete。

### 2026-09-10 · 稳定委派批 D（照 qoder B1+B2：具名子代理花名册 + 有界主动委派偏置）
- **背景与翻案（实证驱动）**：2222 全程 `run_subagent` **0 次被调用**（拆解/建 11 个关键元素/建分镜全由主模型 inline 干完），证实“只靠工具描述单触发”不够。本机 qoder 二进制字符串核查确认它是 **B1+B2 一起用**：除工具描述里的“何时用”，还有一张具名子代理花名册（`GeneralPurpose`/`CodeReview`/`plan-agent`…）与“匹配到/能并行就主动派、派出去就别自己再干”的写死偏置。用户据此裁决改走 B1+B2（上轮“就要 qoder 式只留 description”的口径作废；`SKILL.md` 仍不碰，不做 flova 式逐 Skill 点名）。
- **D1 具名类型（B2）**：`core/subagent.py` 的单一全集白名单→ `SUBAGENT_KINDS`（类型 → {工具白名单, 职责块分节}）：`storyboard_split`（拆关键元素/分镜，只建结构骨架）、`media_prompt_write`（逐条写提示词，新增 `view_storyboard_media`/`read_draft` 可见，先看图再写）、`general`（兜底）；旧名 `SUBAGENT_TOOL_WHITELIST` 改为缺省类型的别名（不留第二事实源）。未知/缺省类型回落 general（类型只是能力面预设，不因拼写丢掉整轮委派）；每类职责块与花名册 prose 单家 = `prompts/planner/subagent.md`（`KIND_*` / `KIND_ROSTER`），`build_subagent_task(task, kind)` 把职责块前置进子级任务（子级看不到主对话，开局就知道自己哪类、验收标准）；工具描述拼入花名册，单测钩住“类型集与 roster 不漂移”。子级仍**不给** `task_complete`/`workflow_pause`（不提前盖章收尾、不发起确认），深度 1、审批=never、步数走 env 均不变。
- **D2 有界偏置（B1）**：`protocol.md`《Tool 优先协议》新增【批量重活优先委派】一条：自包含、一次产出很多内容的批量工作（拆结构 / 逐条写提示词）优先经 `run_subagent` 委派而非 inline 逐字写；可分次委派（先拆后写）；委派后等摘要再汇报、**不得重复做已派出去的同一批**；需逐条确认的分步推进与花钱生成不委派。与原有「多步任务小步分批」条同位，不新增第二表述源。
- **附带修复（集成测试抓出的 B1 真 bug）**：`run_subagent` 的回喂不带 `detail` 字段，而 `fc_feedback.format_tool_results` 对非 read_* 工具只转发 `data["detail"]` ⇒ **子代理的摘要全丢，父只看到“run_subagent：执行成功”一句话**（委派信息链断）。修复：`_dispatch_tool` 回传数据同时填 `detail`（走既有声明通道，不另开机制）。
- **验证**：`test_subagent_run_subagent` 新增 6 例类型用例（不变式逐类成立且白名单工具均真实在册/职责块互异/未知回落/roster 不漂移/按类型裁剪），共 20；新增 `tests/integration/test_subagent_delegation.py` 3 例端到端（scripted 模型：父委派→子真建组落账→只回摘要且子的中间步不进父上下文→子线程自描述落流 / 零动作谎报被驳一次后事实警告收尾 / 盖章一步即收）；两个测试文件的 `ToolManager.reset()` 跨文件污染按同族口径改为显式重注册全套；全量 `tests/` **2333 通过**；`acceptance --quick` 全绿。

### 2026-09-10 · 完成盖章批 G-补（计划书逐条自查补漏：只读记录展示「本轮宣告完成」+ 子级盖章出口）
- **缺口（逐条比对计划书 G1 发现）**：原文要求 `turn/stamp` 事件「供审计 **+ B3 只读记录展示本轮宣告完成**」，而 `session_log.project_readable_record` 把 `turn/*` 一律当噪声跳过 ⇒ 章落了流但用户永远看不到；且子级白名单不含 `task_complete`，子级无合法盖章出口（暂停在子级被自动放行），该展示项在子线程里永远不可能出现。
- **修法**：① 投影新增 `EV_TURN_STAMP` 分支 → `sender="system"` + `stamp=True` + 当时客观账本回执（其他 `turn/start|end` 仍不入，不往只读面刷噪声）；② `SubagentRecordMessage.sender` 联合类型加 `'system'`，`SubagentRail` 以虚线盖章条渲染（全语义 token，过 `semantic_colors`）；③ `core/subagent.py` 每个类型白名单统一含 `task_complete`（`_whitelist()` 单一拼接点，不逐类复述），仍不含 `workflow_pause`/花钱生成/`run_subagent`；`DELEGATION_CONTEXT` 同步告知子级“三个合法出口 + 先盖章再交摘要”（子级不注《Skill 流程纪律》，协议里的引用对它为空指，故出口清单必须住在子级看得到的文案里）。
- **验证**：`test_project_readable_record_and_status` 断 system 条目、类型不变式改钉“子级必有盖章出口”；`SubagentRail.test.tsx` +1（5 例）；全量 `tests/` 与 vitest 全绿、`acceptance --with-eval` 20 步全绿。
- **B3-前端真机自查补漏（左栏 Tab 裁字）**：真机看一眼即暴露——第三个 Tab「子任务」加入后三标签实宽 381px > 窄左栏可用 305px，被父容器 `overflow:hidden` 裁掉标签文字。`.left-tabs` 改 `overflow-x:auto` + `scrollbar-width:thin`（`.left-tab-btn` 早前的 `white-space/flex-shrink` 防堆叠条款保留），超宽时横向滚动而非裁字；纯 CSS、全语义 token，`acceptance --quick`（GATES+tsc）绿、`npm run build` 成功（首屏 360.89 kB ≤ 400）。

### 2026-09-09 · 会话层 append-only 二期批（状态注入事件化 + A-E 缺陷修复，G1-G4 全落地）
- **背景**：一期（E1-E3）审查发现六项问题：B（rewind × 压缩检查点交互静默丢全史，正确性）、C（压缩轮每步重复烧摘要调用，成本/延迟）、A（状态尾每步全量重发 + 步数计数器 → 命中率天花板 75-85%，与 1111 实测 74-81% 吻合，**剩余缺口全在此**）、D（检查点永不合并逐次堆积）、E（图片/多模态消息不入流 → 回放字节不等 + vision token 膨胀）；F（未知工具解析层归位）经复核一期已落地（审查误报）。方案 = `docs/会话层append-only二期细案.md`（v2 送审稿，用户批准「A-F 都要做」；A 的初版「快照落账本」补丁方案被用户否决，重写为「注入即事件」正向设计——dsh session 源码实证：一切注入皆 `user/message` 事件（带 source 区分真人/inject/续跑），系统提示词也是 surface 0 号节点，**不存在「每请求重建的注入」**，快照补丁的病根 = 保留了每请求重建结构再往日志塞第二份拷贝）。
- **G1（source 字段 + B + C）**：user/message 事件加 `source` 标签（user/state/checkpoint/media；`_ev_source` 单一判定源，老事件无 source 按 replaces_seqs 推断向后兼容）。B 修复二件套：rewind 定位按 source 跳过检查点/状态/媒体事件；`_fold_surface` 改两遍 fold（第一遍收集每条 rewind 的丢弃区间 `(to_seq, 标记seq]`——标记后新历史保留，嵌套自然叠加；第二遍命中区间即跳过——检查点被 rewind 丢弃时连同 shadowed 一起从未进 fold，原事件自然恢复）。C 修复二件套：`compact_pass` 加 `mirror` 参数同步 splice agent_loop 的 messages（下步重组自然含检查点，与日志 fold 对齐）；摘要指纹缓存回归（`_span_fingerprint` md5 → `_COMPACT_CACHE` 上限 64，同 span 零模型调用）；检查点事件带 source=checkpoint。turn_executor 四个调用点（两通道 + 溢出恢复）传 mirror。
- **G2（D 检查点合并）**：`_is_span_anchor` 统一判定（真实用户消息或检查点）——压缩范围/保留尾轮组锚均纳入检查点（`_is_checkpoint_msg` 按 COMPACTION_PREAMBLE 前缀判定，与构造读同一分节）；COMPACTION_INSTRUCTION 补 prior-checkpoint 合并条款（dsh 原文意译：不逐字照抄、保留仍属实、合并为单一摘要）。
- **G3（A 状态注入事件化——主刀）**：`planner._build_and_log_state_event` 轮始单一落点（handle_message 统一入口，流式/非流式/scope 三路径同口径）：轮首构建状态正文（build_state_tail_message 全家：状态 JSON + 降级引导 + 偏好/模式 note + 进度 + 草稿指针）落 **source=state 事件**，存 PlannerContext.state_event_content；`run_agent_loop` 组装 messages 时追加在 user 消息之后（与日志 seq 同序 user → state → steps，**回放 = 请求逐字节，跨轮缓存命中至上一轮最后一字节**——每轮全价仅上轮回复+新消息+新状态事件，理论下限）。**退役**：turn_executor `_state_tail_message`/`_degrade_state_tail`（每步尾部装配与每步降级链）、`PlannerContext.step_info` 步数行（每步必变 = 强制前缀失效源；STEP_FEEDBACK 已带「第 N 轮」）；STEP_FEEDBACK 文案改（尾指针「见对话末尾状态 JSON」失效 →「如需最新工作台全量状态，可调用 read_state_group 按组读取」——拉模式指引，外部标杆转录同形态）。预算保险：A/B 档降级（build_agent_context 内）不变，第二层超预算降级退役归 truncate_messages 兜底；状态事件 = 普通轮组锚消息随老轮组被压缩收编（不膨胀）。
- **G4（E 图片/多模态入流）**：①事件 content 支持 parts 原样落盘（append_user_message 透传 list；fold 透传）；chat_service 两通道多模态轮落 `llm_user_content` parts（回放=请求逐字节）；②图片回喂消息镜像落流（agent_loop `_mirror_fc_feedback` 对 pending 中 list content 的 user 消息落 **source=media** 事件——rewind 定位不受干扰）；③装载层图片剥离 `strip_prior_images_loaded`（load_history 回放后仅保留最后一条图片消息，更早图片 parts 移除 + 首条附 FEEDBACK_IMAGES_STRIPPED 说明，与内存 strip 同文两口径；跨轮 vision token 治理归装载口径，日志原文永在）。
- **缓存结构（G3 正向推得）**：下一轮请求 = [system] + 回放（…上轮 user + 状态事件① + 步 1..N + 回复 + 本轮 user + 状态事件②）；轮内每步全价仅增量 ~1-3K → 稳态预期 95-97%，长会话末段 ≥98%（vs 现状 74-81% 实测天花板）。
- **测试**：test_session_log.py 扩至 36 例（G1：rewind source 定位/两遍 fold 恢复语义/嵌套叠加/mirror 同步 splice/指纹缓存；G2：检查点纳入 shadowed/合并指令；G4：parts 往返/media 跳 rewind/装载剥离三例）；test_state_tail_injection.py 按 G3 语义重写（状态事件构建+落流/run_agent_loop 组装追加在 user 后/零注入/每轮刷新/构建失败回落；system 稳定断言保留；降级保险丝三例随机制退役）。fixture 清 _COMPACT_CACHE（同 span 跨用例隔离）。
- **验证**：pytest 全量 2293 passed / `acceptance.py` 全量（GATES+pytest+vitest+tsc+eslint+双覆盖率地板）全绿。
- **终验待实跑（§九口径，需 deepseek 通道真实 Skill 跑批）**：①`scripts/cache_hit_report.py` 稳态 ≥95%、长会话末段 ≥98%；②trace 抽查无同章节二次全文回喂；③context-usage 增长曲线平滑；④G3 行为观测：read_state_group 调用率与错误率（模型不主动读而凭记忆断言组状态 = 回滚信号，两处开关回今天行为）；⑤断轮恢复实测。

### 2026-09-09 · 会话层 append-only 化批（v4 方案主刀，E1/E2/E3 全落地）
- **背景**：v4 复测实证 70K tokens 中 ~40K 是轮内回喂累积（Skill 章节跨轮重读 2-4K/轮 + 建组 desc 重复回喂 1-2K/步）；历史非 append-only（轮内 assistant(tool_calls)+tool 结果只存单请求内存列表，轮末蒸发）是结构性根源——读过的全文每轮蒸发、重读与去重指针双双失效、模型跨轮「反推式梳理」。方案定稿 = `docs/复测六问调研与方案.md`（v4），细案 = `docs/会话层append-only化细案.md`（用户已批）。单一主抄源 = dsh（deepseek-harness，MIT）；Claude Code microcompact 属 API 私有特性不可抄。
- **批 E1（事件流骨架，上会话落地）**：新增 `core/session_log.py`——事件词汇表（surface 三事件 user/assistant/tool-result + log-only step-feedback/rewind/imported）、逐事件一行 JSONL append 即 flush（`workspace/sessions/<pid>/<cid>.jsonl`）、`derive_messages` 全量回放推导（rewind 截面 / pruned_from 就地替换 / replaces_seqs 压缩折叠 / 悬挂 tool_calls 补位 TOOL_RESULT_SUSPENDED）、chatMessages 名义消息一次性幂等迁移（`log/imported` 判重）、D4 失败回落（任何异常 record_degradation + 回落 chatMessages 装载，fail-open）。装载链路切换：`chat_service` 流式/非流式两通道 `load_history` 优先事件流；轮内三处镜像（assistant=turn_executor.llm_call 单点、tool 结果+步回喂=agent_loop `_mirror_fc_feedback` 全出口覆盖）；截断重答 = `rewind_last_turn` 标记制（chat.py 路由同点）。工具全量常驻下 tool_calls 内嵌 assistant 事件（细案 D1，与 C2 派发结构同构）。
- **批 E2（修剪器，上会话落地）**：`session_log.prune_pass`（dsh compaction-tool-result-pruner 参数原样：8192/4096/1024 码点、`[... tool result middle pruned ...]` 标注、零模型调用）——压力命中（≥0.8×窗口）双面修剪：内存面就地改写（本轮后续请求立即收益）+ 日志面 `pruned_from` 替换事件（原文永留日志，下轮回放直接见修剪版）；低于压力零动作。接线 turn_executor 两通道（digest 之后、压缩之前，dsh 顺序）。
- **批 E3（阈值压缩 + 退役，本会话落地）**：
  - **compaction-basic**（`session_log.compact_pass`，dsh 参数原样：thresholdRatio 0.8 / retainRatio 0.16（分母=已路由上下文窗口）/ maxTokens 8192 / compactionRetries 1 / maxOverflowRetries 1）：触发 ≥ floor(窗口×0.8)；保留尾最近 floor(窗口×0.16) tokens 逐字（轮组原子，`_is_real_user_msg` 边界）；范围 = 首个真实用户消息到保留尾起点（孤立单条不压）；替换 = `compaction/start → summary(shadowed_seqs) → 检查点 user/message(replaces_seqs) → end` 括号事务先落日志再动内存（崩溃=可检孤儿括号），检查点 = COMPACTION_PREAMBLE + `<compacted-summary>` 包裹；摘要请求复用热前缀（[system] + 区间消息逐字节 + 末尾 COMPACTION_INSTRUCTION 一条 user，tools schema 照带）；内存/日志双面替换靠 `_match_surface_seqs` 严格对齐（错位=回落装载/digest 漂移时仅内存面替换，fail-open）；摘要失败/撞帽（finish_reason=length）fail-closed 不入检查点。
  - **turn 事件**：turn/start（chat_service 两通道落 user/message 前 + 截断重答 rewind 后）/ turn/end（agent_loop finally 统一出口）log-only，derive 跳过。
  - **溢出恢复**：`exceptions.KIND_CONTEXT_OVERFLOW` + `is_context_overflow_error`（常量归 exceptions 保依赖方向，分类在 adapters/errors `build_status_error` 文案识别：context_length_exceeded/prompt is too long/上下文超长等保守表）；turn_executor `_chat_with_overflow_recovery`（非流式）+ 流式未产出内容分支——溢出确认 → `compact_pass(force=True)`（绕过阈值与保留策略，仅保最近一个轮组的一次最大平衡缩减）→ 重试一次。
  - **退役**：`round_compact.py` 整模块删除（compact_oldest_round 职责并入 compact_pass，调用点两通道替换）；`fc_feedback.should_compress_feedback/compress_prior_feedback` + `FEEDBACK_COMPRESSED` 常量与分节删除（对象只剩旧格式 user 伪装消息，tool role 化后无存续面；修剪器+压缩覆盖其职责）；`config.feedback_compress_ratio` 设置项删除（热重载 context 组同步）；`docs/五项修法执行计划.md` 退役指针加删除线。`truncate_history` 暂留（细案 §二：批 E3 实测后裁决，实测归下批验收 §九）。
- **测试**：test_session_log.py 扩至 23 例（E1 回放/推导/迁移/回落 + E2 码点预算/双面改写/低压力零动作 + E3 触发/保留尾轮组原子/检查点替换与回放闭环/事务括号闭合/摘要失败 fail-open/撞帽 fail-closed/错位仅内存面/force 溢出口径/孤立轮不压/turn 事件）；退役清理：test_round_compact_overflow.py、test_compact_truncation_failclosed.py 删除，test_audit_fixes/test_quality_guardrails/test_prompt_protocol_wiring/test_view_storyboard_media 相关用例退役留注释。
- **验证**：定点 pytest（session_log 23 + 关联模块 58+122+11+58）全绿；`acceptance.py --quick` 退出码 0（func_imports 方法内 import 顶层化、ref_integrity 退役指针修复后）。
- **遗留（§九全量验收，需实跑）**：① 长 Skill 跑批 trace 抽查——同章节 read_skill 二次起指针化、建组 desc 不再逐步重复回喂；② `cache_hit_report.py` 稳态命中率实测 ≥95%（剔除首调与预热口径）；③ context-usage est_tokens 增长曲线平滑（修剪/压缩仅阈值步发生）；④ 杀进程断轮恢复实测（日志回放含已执行步工具结果）；⑤ `truncate_history` 退役裁决（E3 实测后）。

### 2026-09-09 · 品牌字样清扫批 + 指令收拢与缓存稳定批（正向设计）
- **复测补丁（同日，1111 复测五问题实证）**：①A4 暂停点探针误报——「节点翻转完成」≠「Skill 声明的暂停点」（规格写入完成后被谎报到点，模型被逼发卡、同批建组调用全冻结，即用户所见「故事板设计突然停了」）→ STEP_FEEDBACK_AT_PAUSE 与探针整体退役，回喂纯事实化（去掉「请继续完成任务」方向性），停/继续判定唯一归纪律第 2 条判定式；②故事板客观进度 ✓/✗ 有「已完整」歧义引发纠结 → 改计数（「关键元素：已建 N 组」，全空不注入）；③未注册工具拒因分流——模型拼错 storybook_create_group 被「高风险确认闸」话术误导成要走确认（deny 范围逐字节不变，仅被拦且未注册时话术换「工具不存在（疑似拼写错误）」，ToolManager.has_tool 分流）；④开场盘点问询收口强化——启动问询卡必须一次性覆盖 Skill 全部规格维度（不先问一部分、写入规格时再补卡）；⑤缓存复测：新代码已生效（tools_fp 五步稳定，轮内命中 74~81% vs 基线 20.9%），95% 未达，剩余大头 = 每步 tool 回喂增量（read_skill 全文重复读等），列入下轮调优。教训：早期早退分支放在判定链前改变了 deny 语义致 26 测试连锁失败，已改到判定命中后仅分流话术。
- **背景**：1111 项目复盘三问题——①模型思考内容出现外部产品品牌字样（实测来源 = 运行时注入层：protocol「开场盘点（原品牌）同款」/skill_runtime「（原品牌）节奏」/execution_preference/工具 description「建组规范（原品牌）形态」，trace 原文引用实证）；②第一轮思考「纠结打架」（停/问/继续三类判定散布 5 处、防虚报 4 处、裁决留痕泄漏进运行时文本、Skill 内矛盾靠模型脑内调和）；③正文质量差（回复输出纪律全是抑制性条款、多步过渡语拼盘、机械占位文案入历史成 few-shot 污染）；④缓存基线 20.9%（三层击穿：前端 10 条窗口+truncate_history 位置相关截断；阶段工具裁剪每步重算+global_settings 条件段翻转；状态尾部每步重建）。
- **外部调研**（正向设计依据，均一手开源）：Codex 官方 gpt_5_1_prompt.md（定义+边界+正反例、三段式输出契约）；Claude Code 系统提示词（6 层优先级+静态/动态缓存边界标记）；DeepSeek Harness（开源 MIT）官方架构笔记「每条事实有且只有一个所有者」与 PromptAssembly{sections, tools} 单一组装瀑布——与本批治则同构。
- **用户裁决**：①外部品牌字样（Flova/flovaN/flvoa 变体）全仓清除——运行时 prompt 措辞自然化、注释/文档统一替换（品牌词→外部标杆、转录编号 flovaN→转录N）、标识符改名（_FLOVA_CORE_PARTS→_COMPOSITION_CORE_PARTS 等 8 处）、历史 trace 同步清除（judge_replay 会重放），新词规范=外部标杆/转录N；②Skill 包（data/skills）一行不改、Skill 装载期所有权校验不做（记长期规划，冻结清单 §16）；③工具全量常驻（裁剪退役，正确性归闸机+工具校验）；④缓存命中稳态 ≥95% 验收目标。
- **改动（计划书 docs/指令收拢与缓存稳定执行计划.md，批 A-D 全落地）**：批 A 指令所有权收拢——skill_runtime 纪律 2 重写为唯一停机判定式（其余时刻一律不停）、纪律 10 删与判定式重叠句、纪律 1/protocol 删「机械越阶拦截已退役」「不设平台拦截」裁决留痕；protocol 开场盘点补「缺项合并为一次问询」；回复输出纪律重写为正向三段式契约（过渡语=正文声明+中间更新 1~2 句例句+收尾 recap+全文归属）；iron_rules_header 补【冲突与缺信息处置】（唯一表述源），spec_rules 默认模板删第 1 条同义复述；新增 STEP_FEEDBACK_AT_PAUSE——agent_loop 每步回喂经既有客观探针（workflow_runtime.node_objectively_done 只读壳，与轮末阶段闸同源）判暂停点换模板。批 B 工具常驻+组装单一化——prompt_gates.stage_tool_restrictions/STORYBOARD_STAGE_TOOLS/GENERATION_STAGE_TOOLS 退役；_compute_excluded_tools 删阶段裁剪分支且计算移至轮始一次（轮内冻结）；global_settings 段无条件注入；selected_draft 指针自 system order 75 移入状态尾部（P3 归位）；planner.tools_schema() 唯一取件点（turn_executor 两通道消费，dsh 组装单一化形态）。批 C 历史前缀稳定——主路径/非流式路径 history 改服务端线程装载（_main_history_from_thread，与 scope 子对话同源；body.messages 退役为兼容字段，前端窗口 slice 退役）；truncate_history 位置无关化（统一 2000 上限=头 1800+尾 200，删「最新/更早」双档位）；机械占位正文落 kind="mechanical"（text_source 全链路：AgentLoopResult→PlannerResponse→done payload→chat_service 持久化），线程装载时压成固定短句（文案外置 feedback.md::MECHANICAL_HISTORY_PLACEHOLDER，Rule 6）；会话级 LLM 摘要 compaction 退役（线程全量装载后阈值必命中且摘要逐请求漂移成新击穿源，context rot 归确定性截断链）。批 D 验收——新增 scripts/cache_hit_report.py（只读稳态命中率报告，剔除每项目首调与 <12K 预热，≥95% 人工判定不做 CI 机械闸）；测试面：截断位置无关性/线程装载/mechanical 压缩字节稳定三组新回归+受影响契约钉死测试同步（铁律模板两条款口径、暂停判定式、防虚报第 7 条指针、目录金线重采 16 包、frontmatter 测试接受裸键形态）。
- **验证**：pytest tests/unit+integration 2272 passed / vitest 880 passed / acceptance --quick 全绿（GATES+tsc）。
- **遗留注记**：data/skills 新增用户包「新-Skill」（裸键形态）曾致 2 测试失败，已随基线重采与断言修正闭环；存量项目《执行铁律.md》旧第 1 条属用户数据不动（语义被头部声明覆盖）；「新-Skill」类用户测试包后续增删需再重采目录金线。

### 2026-09-08 · 模型编辑面板批（3333 复盘：思考开关/窗口三挡/digest 关停）
- **背景**：3333 项目（proj-1788838336-1281297f，同 Skill 同剧本，deepseek-v4-flash-0731）对照 6666 实证四问题：① 无思考——直连 tokenrhythm 实测（同 key）：deepseek-v4-flash 为 hybrid 默认关思考，enable_thinking / reasoning_effort 任意一个可触发，平台请求体未带任何参数；② 快 17.5s vs GLM 189.7s（无思考输出 + 系统段缓存命中）；③ 流程离散（skill 启动协议与暂停点顺序的散文歧义，deepseek 字面执行先确认后分析，GLM 合并推进，转录六 第三种——均在容差内，用户裁决不加机械闸）；④ 缓存 37.5%（7 请求 cached 恒 6144=system+tools+Skill 固定段，历史段全断）+ 上下文变小（digest 把 read_uploaded_doc 全文等换指针，msgs 7→5）。另：上下文窗口子串表过时（deepseek/glm 家族键=128K，新模型实际 1M/1.05M），chat_models_meta 读取端存在但无写入端。
- **用户裁决**：模型下拉框 hover「编辑」→ 侧边编辑面板三项配置（窗口三挡 200K 默认/400K/1M、思考模式开关默认开、推理档位四档默认/高/中/低——复用现有枚举不变）；缓存策略选「全部命中」（历史只追加），digest 默认关闭；子串表删家族漂移键；未配置模型回落 200K。
- **改动**：
  - 编辑面板（前端）：ModelThinkingPill 模型项 hover 出编辑铅笔 → 侧边展开编辑面板（窗口三挡/思考开关/推理档位，改动即时 PUT /providers 全量保存）；`chat_models_meta` 类型化（ChatModelMeta）+ lib/providers 读写 helper（saveChatModelMeta 更新 store + putProviders）；样式 pill-model-editor 侧边浮层。
  - 思考注入（后端）：`chat_model_meta()` 共享读取函数下沉 provider_config_loader（adapters→utils 合法向）；OpenAICompatChatAdapter 加 provider_id，`_apply_thinking_level` 四级优先级——None=env 回落（814H7 保留）、显式档位=reasoning_effort（不变）、`""`（UI 默认档）=meta 注入（关=不发；开+档位=effort；开+无档=enable_thinking）> env 回落 > 兜底 enable_thinking=true；400 剥离名单加 enable_thinking。factory 两处构造传 provider_id。
  - 窗口查表：token_budget.context_window_for_model 的 meta 内联逻辑改用共享 chat_model_meta（行为不变）；context_window_size 回落默认 128000→200000（对齐三挡默认）。
  - digest 默认关：TOOL_RESULT_DIGEST_CHARS 默认 200→0（历史只追加保前缀缓存连续命中；round_compact 预算兜底保留）。
  - 子串表收窄：model_context_windows.json 删 16 个家族漂移键（deepseek/qwen/glm/kimi/moonshot/doubao/ark/seed/mistral/llama/phi/command-r/yi 等），保留窗口稳定的官方条目（gpt/claude/gemini/o 系）；家族模型窗口唯一来源=chat_models_meta。
- **测试**：test_thinking_meta_and_fallback_injection 新增（meta 开/关/带档/未配置兜底四分支，PROVIDERS_FILE monkeypatch）；test_thinking_override_wins_over_global 的 "" 档断言随新语义更新（env high → 回落 effort）；test_context_window_meta_takes_priority 新增（meta 窗口优先/无字段回落/无 provider_id 路径）。验收：pytest 2268 passed（2 失败为新-Skill 包既有遗留，与本批无关）；tsc/vitest 880/eslint/cov_ratchet 全过。
- **待用户动作**：① 重启后在模型胶囊 hover 编辑面板为 deepseek-v4-flash-0731 配 1M 窗口（思考开关默认开即生效）；② UI 目测编辑面板交互（宪法 §3.1）；③ 新-Skill 包 frontmatter 非 --- 包裹导致 2 个 pytest 失败待处理（改标准 frontmatter 或移走包）。

### 2026-09-08 · 对齐批（6666 复盘：成果全文双份/保守多轮/暂停细则多源治理）
- **背景**：6666 项目（proj-1788838065，同 Skill 同剧本）第一轮 189.7s 三步取证：step2 139.9s（reasoning 全分析 + report_markdown 全文参数）；正文 = 模型浓缩交代 + `stage_deliverables` 全文渲染 → 上下文双份全文（0 缓存下每轮双价重算）；step3 为 workflow_pause 单独跑一轮（20s + 19.4k prompt 全价重算）。外部标杆 同 skill 同剧本对照（用户供 转录六 实测）：分析只给约 200 字浓缩交代、无全文报告展示、分析与暂停卡同轮——skill 的 script_analyze「输出」在 外部标杆 被理解为供后续阶段消费，不进正文；此前「外部标杆 也会输出全文」的判断被 转录六 推翻。联网对标：Claude Code / Codex / DeepSeek Harness 均同轮连续工具循环（一次响应多 tool_use 为 API 原生能力，harness 只管执行侧）；外部标杆 暂停时机为平台机械档位（设置页四档实证）。
- **用户裁决**：四项平台侧优化全做（skill 一字不动）；速度 3-5 倍差距的大头归因中转吞吐与缓存透传（维持 4444/5555 复盘结论，另行走渠道侧）。
- **改动**：
  - 渲染通道迁移：`stage_deliverables` 正文渲染退役删除；报告全文改挂「剧本分析已完成」事件卡折叠——`event_cards` 新增 script_analysis_report 分支，`product_event_card` 返回扩 4 元组携 detail_md；`emit_event_card`/`record_subaction` 加 detail_md 参数，随 SSE（tool_started/finished 可选字段）与 trace 双通道持久化；to_ctx=False 全文不进模型上下文。`planner_output` 成果正文拼接移除（暂停轮客观事实兜底保留）。前端 detail_md 贯穿 sse-events → stream store → turn-ledger/timeline → TimelineDetail（折叠行=单行摘要、展开=全文，复用 resultSummaryView 折叠机制），SSE 契约帧加 detail_md 后重跑 gen_api_types。
  - 暂停细则单一化：message ≤120字 / options 结构 / group 分页 / 回应三态从 protocol 第 5 行迁入《Skill 流程纪律》唯一家（第 2/5/6 条既有），protocol 收缩为「调用时机 + 冻结语义 + 指针」。
  - 收尾批可合并：protocol 第 5 行与《Skill 流程纪律》第 4 条补「落账/写档类收尾工具可与同批 workflow_pause 连续提交（先收尾后暂停，不必为暂停单独再跑一轮）」——消除模型对「暂停即冻结」的保守解读，省 step3 型独立轮。
  - 正文口径：protocol 第 15/27 条改「浓缩交代（类型判定/剧情主线/镜数预估/待确认项一段话），不复述报告全文；skill 明确要求正文完整展示时按 skill 执行（平台不拦截）」。
- **测试**：test_skill_flow_batch1 渲染测试改事件卡断言（卡名/一句话明细/to_ctx=False/detail_md 全文）；test_stage_deliverables 随模块退役删除；use-sse-events 断言随签名同步。验收：quick（GATES+tsc）EXIT=0；全量 pytest 2266 passed（2 失败为用户导入「新-Skill」包 frontmatter 非 --- 包裹 + 存量快照 15→16 漂移，stash 归因与本批无关）；vitest/eslint/cov_ratchet 全过。

### 2026-09-08 · 上下文与缓存优化批（5555 复盘：思考纠结/写两遍/缓存 0 命中治理）
- **背景**：5555 项目（proj-1788790634，AI-短剧一站式生成，glm-5.3-flash）149 秒完成剧本分析三步。trace 全量取证四病根：① step2 思考开头花大段澄清「工具结果是否重复注入」（read_skill 流程段+目录与 system 的 Skill 轻量块双份；script_analysis_report 落账全文与 state.analysis JSON 双份）；② 写两遍（思考里预演 5260 字分析后工具参数再写一遍）；③ 缓存 0 命中（step1→step2 prompt 11739→13908 全量重算）；④ 工具结果伪装 user 消息（git 考古：从首版循环顺手沿用，从未做过 role 裁决；2026-07-29 Qoder 快照里的标准 tool role 实现从未落地）。业界对标（Codex 工程文/DSH 源码/Anthropic 官方文档/Gemini/DeepSeek）：思考回传是全行业硬要求（Claude/Gemini/DeepSeek 不回传直接 400，GLM 最宽松）；Codex「旧提示=新提示精确前缀」+ tools 跨请求一致；DSH 一等 tool-call/tool-result 块 + snapshot 快照语义；Claude 工具结果用完即清。
- **本地实测**（2026-09-08，tokenrhythm 中转）：reasoning_effort 三档对比 low 470字/2.9s vs 无档 981字/8.6s（low 真实生效，5.3-flash 无「low 映射 high」）；主对话档位来自前端请求体 thinking_level（runtime_settings 的 model_policy 是 executor/summary 角色策略）；`clear_thinking:false` 中转 400 拒收（保留式思考增益不可得，记录放弃）；GLM 通道缓存恒 0（同载荷重发 6871 tok 前缀仍 0）vs deepseek-v4-flash 同中转同玩法重发命中 4608/4616（99.8%）→ GLM 通道缓存问题属中转侧（上游多账号轮询嫌疑），实验数据交用户与中转方交涉。
- **用户裁决**：A/D/B1/B2/C1/C2 六批全做，先出计划书（`docs/上下文与缓存优化执行计划.md`）再做；执行模式/执行偏好双轴（已对齐外部标杆）、思考回传开关（必须开）、Skill 文件（不加规矩）、clear_thinking（中转拒收）四项不动。
- **改动**（六批独立 commit）：
  - 批 A（52abacb）：`openai_compat` 400 兜底扩展——报文点名拒收 assistant 消息 `reasoning_content` 时剥离历史思考字段重试一次并按实例记忆（`messages.reasoning_content` 键），后续请求组装侧预剥离（思考回传开着的端点迁移到拒收型端点不再持续 400）。
  - 批 D（2b03522）：tools 清单指纹观测——`_record_budget_breakdown` 增记 tools_count/tools_fp（sha1 前 16 位）入 budget 与 StepTrace（`tools_fp` 字段，空值不写键），跨步变化 = 工具集漂移 = KV 前缀击穿点可观测。
  - 批 B1（d4b2183）：read_skill 回喂去重——无 section（流程段+目录）与 system Skill 轻量块重复 → 指针回喂；有 section 首次全文（带 `skill=/section=` 结构化行头）、同会话同章节重复取读 → 指针；`FEEDBACK_FULL_TOOLS` 移出 read_skill 单独分支。
  - 批 B2（4823e9d）：报告双份治理——事实修正（script_analysis_report 回喂仅字数计数，全文实际藏在 assistant tool_calls 参数里）；新增 `digest_projected_tool_args`（assistant tool_calls 大参数消化：白名单工具 arguments 内超阈值字符串字段替换为 ARG_DIGEST_PLACEHOLDER，最近 2 条保留原文，幂等），`PROJECTED_STATE_TOOLS` 纳入 script_analysis_report；流式/非流式两通道 truncate 前接线。
  - 批 C1（01ddabb）：流式 tool_call id 通道——`StreamChunk` 加 `tool_call_id`，`_stream_once` yield 携带供应商 id，`llm_call` 流式组装优先真实 id（空串回落合成 id）。
  - 批 C2（4adbb1c）：工具结果切标准 tool role——`fc_tool_runner` tool_results 项携带 call_id；新增 `format_tool_result_messages`（逐调用 `{"role":"tool","tool_call_id":...,"content":行式文本}`，view_storyboard_media 图片保留 user 多模态）；回喂组装改经 `_extra._pending_feedback_msgs` 上抛，agent_loop 轮末按标准顺序统一 append（assistant(tool_calls) → tool 结果们 → [图片 user] → STEP_FEEDBACK，含问即停悬挂调用补「未执行」tool 消息）；fc_feedback 家族（compress/digest/_skill_section_seen）role 判定统一 `_is_feedback_msg`（tool role 或 user+marker 双形态）；STEP_ASSISTANT_PLACEHOLDER 分节退役（tool_calls 形态 content 为空合法）；400 兜底再扩——点名拒收 tool role 时 `_downgrade_tool_role_messages` 降级 user 伪装重试并记忆（`messages.tool_role` 键），两通道组装点统一 `_prepare_endpoint_messages` 入口。
- **测试**：test_reasoning_passthrough 扩 400 兜底四例（reasoning 剥离重试/记忆跳过/不误剥顶层/tool role 降级）；test_cached_tokens_telemetry 批 D 两例；test_fc_tool_feedback B1 去重三例 + C2 组装两例（read_skill 无 section 指针化/章节首末行为/图片走 user）；test_tool_result_digest B2 五例（长参数替换/最近 2 条保留/非白名单跳过/关闭与幂等/双通道接线）；test_adapter_stream_protocol C1 一例（流式 id）；test_prompt_relocation_batch3 同步退役断言；test_shell_payoff 承重接线断言随签名更新；test_tracer_concurrency 修本地 .env 污染默认值断言的环境依赖（delenv 后重建 Settings）。
- **验收**：批批 `acceptance.py --quick` 退出码 0；B2 后与 C2 后各跑全量 `acceptance.py` 退出码 0；全程无 UI 变更。遗留：C2 后 5555 同场景真实项目冒烟待用户目测（模型应不再出现「历史是否重复」式澄清思考）。

### 2026-09-07 · 小步提速批（外部标杆对齐：写入降档 + 提示词小步化 + parallel_safe 补标 + 未注册口径改名）
- **背景**：4444 项目慢的根因定案——执行时机非问题（Codex/dsh/外部标杆 三家均整轮后执行；dsh `agent.ts:378-476` 实证），慢在单轮输出体量（一轮 11 角色/28 分镜全套结构化 JSON 数万字 × 中转 ~40 字/秒）。外部标杆转录实证其节奏 = 一小件事一轮 + 大批量按段落分批（3~5 个）+ 失败小步修 + 写入零机器拦截（唯一卡 = 花钱生成确认）。用户裁决：「其他没点名的都要做」（计划书 `docs/小步提速执行计划.md`）。
- **改动**：① `document_write` + `canvas_add_node`/`canvas_update_node`/`canvas_delete_node`/`canvas_batch_add_nodes` risk high→medium（写状态但可撤销：文档带修订、画布有撤销），写入不再弹确认卡；宪法 §2.7 同步修订（high 定义移出「文档写入」），同意矩阵中「规格文档写入」转历史条款（CONSENT_CHARTER 表保留，降档后路径自然失效无害）；② planner 提示小步化（skill_runtime.md / protocol.md：结构化登记按段落一轮一批 3~5 个，引导不强制）；③ 8 个纯只读工具补标 `parallel_safe=True`；④ 未注册工具口径改名（confirm→other_high 拦截回喂，纯注释零行为）。行为变化（正面）：含写操作批次现可建批首 checkpoint，回滚保护覆盖面变大。
- **保留不动**：生成类确认闸（image_generate/generate_video，V6 裁决）、执行模式阶段闸、规格确认暂停卡（产品依赖）、未注册拦截、暂停纪律、PARALLEL_POOL_LIMIT=4。
- **测试**：test_tool_risk_gate.py 定级表与闸级用例同步改写（写入直执行断言、偏好无关断言、override/审计留痕改走 generate_video）；check_consent_copy 门禁回归（protocol.md / execution_preference.md 文案如实更新）。
- **验收**：见各批 commit（每批 acceptance --quick 退出码 0；批 2/批 4 后全量）。

### 2026-09-07 · 五项修法批（4444 事故链治理：输出预算/盲重试/并行池/思考回传调研）
- **背景**：4444 项目（Skill「AI-短剧一站式生成」，glm-5.3-flash）用户确认制片参数后，模型在「默认（原生）」思考档发起调用，思考内容耗尽 `llm_max_tokens=8192` 输出预算 → 返回空/畸形（finish_reason=length、正文空、无工具调用）→ `agent_loop` 判空分支同输入全价重试 2 次（每次约 3.5 分钟）→ 共约 10 分钟零产出，用户手动停止（原子轮废弃，状态零损失）。根因链：① 输出预算 8192 对思考型模型太小；② 判空分支不看 finish_reason，「预算截断」与「真空响应」同罪同罚；③ 重试 = 同输入原样重跑，必现同结局。业界调研（2026-09-06/07 联网+源码实证）：dsh（DeepSeek 官方 harness）默认单次输出 256_000、撞帽以该原因收轮绝不原样重试、循环无空响应重试分支、工具有界并行池（默认 10）；Claude Code 五条静默恢复路径均配熔断、无一步一调用强制；Codex 跨步保留 reasoning items。结论：无一家强制一步一调用、无一家让用户调输出预算。
- **用户裁决**：五项修法全做；不留兜底闸机、不改 Skill 文件、不加注入声明、不加治理条款、无前端改动、无 gen_api_types 再生成；模型选择/推理等级由用户自理；判空（正文空+无工具调用）= 正常收轮，删同输入全价重跑。
- **改动**（四批独立 commit）：
  - 批 1（98e6f1f）：`llm_max_tokens` 默认 8192→256_000（对齐 dsh，上限非目标不增费）；输出上限表外置 `data/model_output_limits.json`、实现下沉 `utils/model_limits`（adapters 钳制同用，过 check_layer_imports R3），补录 glm-5/4.7/4.6=128K、glm-4.5/zhipu=96K（智谱开放平台文档保证值）；`openai_compat` 三处下发点统一「400 点名拒收大 max_tokens → 钳到 output_limit_for_model 重试一次 + 按模型记忆预钳」（改值不剥离，区别于字段剥离探针）；`round_compact`/`history_compact` 摘要撞帽（finish_reason=length）走既有失败回落，半截摘要不入缓存/不落 session_summary。
  - 批 2（3222ac2）：`recovery_policy` 新增 `FAILURE_OUTPUT_TRUNCATED`（finish_reason=length），`bad_output` 动作 nudge_retry→新增 `ACTION_END_WITH_NOTICE`（收轮+用户可见提示+retry 芯片，不重试），nudge_retry 键退役；`classify_step_failure` 按 finish_reason 分流；agent_loop 判空分支删同输入重试循环与 `_bad_output_nudge`，feedback.md::BAD_OUTPUT_NUDGE 分节退役；全拒收 FC 轮（had_fc_calls）不入收轮分支（批 9 拒因续轮语义保住）；chat_retry_context 收编 output_truncated 失败键。
  - 批 3（9f993d0）：`BaseTool.parallel_safe` 声明轴（default False 独占串行，注册期非 bool 拒收照 costly 校验段）；`fc_tool_runner.execute` 重构分桶执行——连续 parallel_safe 调用进有界并行池（池上限常量 4，切片并发），独占调用自成屏障，PRE/提交段抽为 `_prepare_call`/`_commit_call` 单一实现；结果与 SSE 事件按模型顺序提交；组内同幂等键重复延后串行补跑命中账本（T4 语义不变）；批首 checkpoint、问即停（workflow_pause 永独占）、取消穿透（已启动跑完+保守回滚判定+上抛）、独占失败回滚-中止全保既有语义，组内失败不级联（组员均只读）；本批只标记 read_skill/read_draft/list_skills 三个只读工具。
  - 批 4（本条）：思考回传调研——智谱开放平台官方文档确认 GLM 4.5+ 默认支持交错思考，工具循环场景官方要求把 assistant 消息 `reasoning_content` 完整、未修改回传 API（流式自 delta.reasoning_content 累积；普通多轮无需回传；Preserved Thinking 须完整未修改且标准 API 端点经 `clear_thinking` 开启），据此按计划「若支持」分支实现 default-off `llm_reasoning_passthrough`（env LLM_REASONING_PASSTHROUGH）三层组合：①请求侧 openai_compat 关=剥离 assistant 历史消息 reasoning_content（浅拷贝，不改调用方本体）防残留字段外泄、开=原样下发，非流式响应捕获 reasoning_content（`ChatResponse` 新增契约字段）；②工具循环内 turn_executor 累积流内 reasoning_delta/非流式捕获随 5 元组 extra 上抛，agent_loop 末轮胜出写入 AgentLoopResult，FC 工具轮占位消息闸门开时附着该轮思考（GLM 推理连续性主场景），轮末经 assemble_response/PlannerResponse 随 done payload 透传（闸门开且非空才下发）；③会话消息结构 `build_chat_entry/add_chat_message` 加 reasoning_content（非空才落字段），`truncate_history` 闸门开时对 assistant 历史消息透传。执行器子代理式适配实例记忆方案已否决：adapter 实例按 provider:model 长存复用，会话并发下思考内容跨会话污染（违反 Rule 3 并发契约），捕获必须走会话内链路。
- **测试**：批 1 test_output_budget_fixes 重写（表值/glm 键/损坏降级/256k 默认）+ test_openai_compat 钳制重试与按模型记忆 + test_compact_truncation_failclosed；批 2 test_recovery_policy 重写（分派表覆盖/动作预算/nudge 退役防复活/finish_reason 分流/收轮不重试/全拒收轮不吞/分派表消费显式 KeyError）+ agent_loop 系旧语义用例改写；批 3 新增 test_fc_parallel_pool（真并发/模型序提交/池上限/独占屏障/默认串行/注册拒收/失败不级联/组内取消/组内幂等）；批 4 新增 test_reasoning_passthrough（默认关/捕获/剥离与透传/工具轮附着/消息结构/历史透传/轮末组装）。
- **验收**：批批 `acceptance.py --quick` 退出码 0；批 3 后与批 4 后各跑全量 `acceptance.py`（GATES+SUITES+RATCHETS）退出码 0；全程无 UI 变更（批 2 走既有 warnings/建议芯片通道）。

### 2026-09-06 · 语言闸私设推导删除 + 执行模式默认档假警告修复（7777 复盘；变更 2026-08-31 裁决）
- **背景**：7777 项目复盘 + 外部标杆 对标实证两处缺陷。①语言闸从规格「输出语言」私设推导提示词语言地板（中文占比≥15% 硬拦），事前不出示、事后才拦截：模型按行业/Skill 语义（输出语言=成片内容语言）写英文提示词被 9 连拦直至烧尽 MAX_STEPS，铁律优先级链无从裁决——冲突另一方不是文档，是代码隐藏条款；②执行模式 ai_decide 默认档「无分节=不注入」为设计约定（execution_mode.md 文件头明示），但 planner 仍每轮查找不存在的分节并打缺失警告。
- **用户裁决（变更 2026-08-31「语言归用户选择」裁决）**：提示词书写语言归文档层——默认按所选 Skill 要求执行；用户在《制片规格》显式声明「提示词语言」时以规格为准（用户/规格 > Skill），经优先级链生效；闸机不再执法语言、**不留兜底**；不改 Skill、不加注入、不加治理条款（模型更换用户自理）。
- **改动**：`prompt_gates.py` 删 `_CJK_MIN_RATIO`/`_SPEC_LANG_LINE_RE`/`LANG_EN_HARD_PREFIX`/`spec_output_language`/`resolve_prompt_language` 与 validate_prompt_write 语言检查块，死 import（find_spec_doc/registry）与 GATE_STRUCTURE 注释「语言」项一并清理（字数地板/字段白名单/音色参考软提醒保留）；`prompts/planner/protocol.md` 语言规则改为文档层裁决表述；`prompts/gates/messages.md` 升级文案去「中文占比」；宪法 §2.1 提示词书写闸描述去「语言」；planner `_load_execution_mode_note` ai_decide 档提前返回不再查找（批 1 独立 commit 2864556）。
- **测试**：旧语言闸语义用例删除/反转——test_prompt_gates 两个英文拒收用例与 8888 事故样本常量、test_trace_sse 0817 B2 六用例、test_prompt_gates_branches ⑤⑥ 节（registry patch 死支）、test_gate_pipeline_wiring 坏提示词夹具改过短文本（管线接线语义不变）、test_skill_manifest C1a 用例反转为防复活锁；新增防复活用例（英文正文+规格中文→不拦；字数地板照拦；ai_decide 档不触发分节查找）。
- **验收**：全量 pytest 2217 passed；`acceptance.py` 三阶段全 PASS（GATES + SUITES + RATCHETS，退出码 0）；无 UI 变更。

### 2026-09-06 · 三批复查修正（用户要求逐项自查后）
- **子对话守卫补漏**：轮末阶段闸 `_apply_stage_gate` 补 `adjust_scope` 守卫——微调真子对话内阶段翻转不签发闸卡（对齐「子对话不发确认卡」既有纪律与 FC 轨 `scope_auto_pause`；此前子对话翻转会在隐藏线程挂起 review 决议+发卡）。补端到端集成测试 `test_stage_gate_e2e.py`（完整 handle_message_stream 轮次发闸卡全链 + 子对话静默；守卫有效性经去守卫变红验证）。
- **设置页注释同步**：ExecutionPreferenceSection 头注释仍列旧标签（自动决定/生成前确认/直接生成），同步为对齐后用语。
- **验收**：全量单测 2132 passed + `acceptance.py --quick` 全绿。

### 2026-09-06 · 动作日志成果语批（外部标杆对齐·呈现层轻量改造）
- **范围**：仅后端单一文案源，前端零改动（live SSE 与 settled actionLog 同吃 describe_fc_tool / aggregate_action_log）。用户侧呈现对齐外部标杆「动作完成卡只讲成果」；固定流程进度模板经用户裁决不做（外部标杆 亦无——流程级进度由模型按各 Skill 步骤词汇在正文汇报，平台只固定动作→完成卡一层）。
- **成果语**：`fc_feedback.describe_fc_tool` 产出类动作改用户视角——script_analysis_report→「剧本分析已完成」、storyboard_create_group→「故事板已更新」、image_generate→「已发起生图（单张）」、generate_video→「已发起视频生成」、read_skill→「Skill「X」流程已加载」（保留「」结构兼容聚合正则）。
- **噪音折叠**：`action_descriptions.aggregate_action_log` 新增低信息抑制集（read_skill/list_skills/get_skill_asset 整类折叠不进聊天动作日志；trace 与审计账本照记）。
- **验收**：新增 test_action_copy_outcome 6 用例 + 全量单测 2130 passed；UI 呈现变化构建后经用户目测确认（宪法 §3.1）。

### 2026-09-06 · 执行模式四档 + 轮末阶段闸批（外部标杆对齐，闸机增减经用户裁决）
- **背景**：6666 复盘确认平台只有「防多停」闸、无「防漏停」闸（阶段暂停全靠模型自觉，flash 档模型实测漏卡/走回头路）；外部标杆 实测（无确认节点自定义 Skill 照样在规格/故事板/素材三停）证明其执行模式档位在产品里程碑上是平台机械行为，档位 > Skill 散文。用户裁决按机械闸版落地、出厂默认档零行为变化；CLI 实验不必做（行为契约已足够）。
- **执行模式四档**：`config.py` 新增 `EXECUTION_MODE_VALUES/DEFAULT/GATE_MODES` + `normalize_exec_mode`（与素材生成轴 `execution_preference` 正交）；`runtime_settings.py` 路由同款清洗/加载/拒收；`gen_api_types.py` 契约导出 EXECUTION_MODE_* 常量；设置页新增 `ExecutionModeSection.tsx`（执行偏好下拉标签同步对齐外部标杆 用语，hint 承诺不动过 consent_copy 门禁）。测试：路由三件套 + 设置页 UI + 契约门禁。
- **引导注入**：`prompts/planner/execution_mode.md` 四分节（ai_decide 无分节 = 不注入）；planner `_load_execution_mode_note` 轮始签发、经状态尾部消息每步注入（auto_full 压制自发暂停；确认档只承担呈现引导，停由平台保证）。测试：test_state_tail_injection 逐档注入 + 脏值回落。
- **机械闸（仅 key_steps_confirm/pause_all 激活）**：①D-18 清偿——stage_done 补 "spec" 分支（has_spec_document 同源）；②默认 workflow 扩为全流程 16 节点（媒体四阶段 ke_media/shot_media/audio_assets/assembly 入定义），审批节点扩为 6 个（规格/关键元素[生图前确认，3/4 合并口径]/故事板/镜头视频/音频/成片），workflow_runtime 审批前置映射表化；③planner 轮末 `_apply_stage_gate`：轮始 run 快照 vs 轮末 sync_run 重算判「阶段翻转」，确认档下新当前节点符合档位目标（key_steps_confirm=审批节点；pause_all=任意节点）→ 机械签发暂停卡（复用 `_issue_pause` 单一链 + review: 前缀 pending_decision，chat_consume.resolve_decision 消费）；档位 > Skill 散文（确认档下 Skill 声明直通照停）。④workflow_runtime.resolve_decision 补落账后 sync_run（模块级 commit_turn 无尾部重算，DecisionResolved 入账后评审节点才能完成——B3 语义延伸到决议路径）；sync_run 补 waiting_user→ready 恢复。ai_decide/auto_full 零闸卡；默认档行为与现状逐字节一致。
- **治理登记**：执行模式与档位优先级条款入 `docs/GOVERNANCE.md` §五（唯一家）；不新增 GATES/RATCHETS。
- **验收**：档位×节点矩阵测试 `test_stage_gate.py`（默认档/直通档零卡、确认档六里程碑逐一停、非审批节点不停、槽位占用不重发、批复闭环入账）+ workflow 契约/运行时/路由/注入全量回归。

### 2026-09-06 · 工具描述去污染批（D-20 当日登记当日清偿）
- **背景**：6666 项目复盘 + 外部标杆 对比调查确认工具层内容模板污染 2 处（全量普查 27 个注册工具 description，仅此两处）：`script_analysis_report`（tools/analysis_tools.py）description 与 `report_markdown` help 内嵌通用报告结构示例（"分类结论、角色/场景/道具清单、幕次结构"），与各 Skill `<script_analyze>` 章节的分析路径冲突（实证：6666 项目据此产出通用剧本拆解，未走该 Skill 五问策略路径）；`workflow_pause`（tools/document_tools.py）description"用于拆解完成后…"把具体时刻写成通用示例——各 Skill 暂停点散布各异（15 个 Skill 六种写法实证）。
- **改动**：前者两处文案改"按所用 Skill 的 script_analyze 章节要求撰写；Skill 未声明分析路径时格式自定"；后者改"在所用 Skill 声明的强制暂停点调用，请用户审阅当前阶段成果后继续"。长期评审纪律（2026-09-06 用户裁决，无机械闸）：工具 description 只写工具用法与机器契约，内容产出模板示例归各 Skill 章节（外部标杆 分层原则：工具层零内容模板）。
- **验收**：受影响 10 个测试文件 96 passed + `acceptance.py --quick` 全绿（12 GATES + tsc）；债务清单 D-20 同批删除。

### 2026-09-05 · Skill 流程跑通修复批 12（1000 事故正向修复：同意章程 + 告示牌同源 + 兜底网）
- **事故**：项目 1000（未来科幻真人电影 skill，proj-1788604999）——用户接受规格确认暂停卡后，模型重提 `document_write` 写「制片规格.md」仍被 tool_risk 闸硬拦：批 9 同意账本执行时收窄为仅 costly 工具消费（`guard_pipeline` `if costly:`，原收窄裁决「非花钱高危不吃同意」与本条修正），规格确认卡的兑现写入落在断点另一侧；拒因文案对它承诺「接受后重提即放行」=空头支票；部分拒收轮（read_skill 成功）不触发批 9 全拒收轮回喂，模型口播「已写入制片规格」假完成收尾——skill 阶段 1 零产物、workflow 卡死 analyze_script。与 9999 同根（同意语义碎片化 + 承诺与实现脱节），按用户裁决正向收拢而非打补丁（对标外部产品：确认对象是产物、落账即兑现、承诺与实现同源）。
- **批 12a · 同意章程**：`guard_pipeline.CONSENT_CHARTER`（同意来源 × 动作类 = 放行范围唯一声明，宪法 §2.4 同意来源枚举 / §2.7 同意范围矩阵同步）；consented 消费从 `if costly:` 改为章程判定——costly 生成 ∪ 规格写入（`spec_write`，fc_gates 按 `is_spec_doc_name` 注入，文档名口径同 fc_tool_runner）可吃暂停卡同意；other_high 维持 fail-closed；四条同意路径登记端零改动（保留为入口）。测试：章程分支单测 + 闸级规格写入（放行/无同意拦/账本轮号失配拦）+ `test_1000_spec_write_consent_flow_smoke`（accept → 重提放行 → 规格落盘 → 「规格已完成」事件卡 → consent 留痕；非规格文档仍拦）。
- **批 12b · 告示牌同源**：拒因按动作类分支——新增 `TOOL_RISK_BLOCKED_OTHER`（other_high 如实指引「本次放行」，禁含 pause-accept 承诺，头部前缀不变 15 处断言保绿），gen/spec 类保留现承诺（12a 后成真）；protocol.md / execution_preference.md 补规格写入口径；**新门禁 `scripts/check_consent_copy.py`**：五处承诺文案（messages.md 三节 / protocol.md / execution_preference.md / 设置页 hint）承诺 ⊆ 章程、other_high 拒因禁含 pause-accept 承诺、C1a 已废「文本解读式同意」措辞全文本禁绝（GATES 表 + ci.yml + 双向 canary 登记，GATES 12 道）；wiring 等值断言补 tool_risk 两分支（「外置改了兜底没改」盲区收口）。
- **批 12c · 兜底网**：①回喂放宽——产出类调用被拒/失败的混合轮不再按纯文本轮提前终止（`turn_executor` 上抛 `rejected_productive_tools`：detail_tier=expand 或 risk≥medium 声明推导，workflow_pause 排除，未注册保守计入）；②续轮预算 = recovery_policy 新键 `productive_reject`（max_retries=2，超限收尾 + 产物缺失警告，防「被拒-口播-续轮」打转）；③对账扩展——`round_end_policies.claims_unbacked_products` 产物族（结构搭建/制片规格）宣称 ↔ 账本对账，`false_claim_audit` 纯文本轮承重 + agent_loop 确认轮审计泛化（未来时豁免与 4444 校准基调不变）。测试：混合轮续轮/预算耗尽/无产出类负样本 + 规格宣称对账正负样本；1000 冒烟补回喂段（混合轮被拦 → 续轮发行暂停卡）。
- **批 12d · 复查修正（用户要求全面复查后）**：①TOOL_RISK_BLOCKED 拒因删「也可在工作台确认相关草稿」越界承诺——drafts_confirmed 归 gen_confirm 闸消费（guard_pipeline L244），evaluate_tool_risk 不认，对 tool_risk 拒绝的操作（规格写入/画布写入/单张生成）该指引是又一处空头支票（12b 门禁漏检项）；check_consent_copy 同批堵漏（tool_risk 两分支禁含该指引）。②productive_reject 预算计数改为只计「真实行使的例外续轮」（finish=tool_calls 的多步链轮本就续轮，不消费预算）。③债务清单 D-19 登记无运行时消费者的文案 re-export 与孤儿判定函数（12 计划承诺项）。④execution_preference.md 头注同步 OTHER 分节与门禁指针。
- **验收**：批末 `acceptance.py` 全量通过（12 GATES 含新 consent_copy + 2199 pytest + vitest + tsc + eslint + RATCHETS）；skill 正文零改动（15 份扫描无冲突）；治理载体 = 本条 + 债务清单 D-18（顺带发现，非事故残留）。
- **待用户目测**：无新 UI 变更（设置页 hint 本批未动）。

### 2026-09-05 · Skill 流程跑通修复批 9-11（生成确认闭环：9999 死锁根治，计划书 v6）
- **立项**：9999 项目事故（古风甜宠 skill 阶段 2 死锁）trace 全量取证——模型建组+写提示词后两次 `image_generate` 被 tool_risk 闸拦截，**全拒收轮被当纯文本轮终止**，闸机指引（"先 workflow_pause"）没回喂给模型，回合以模型过期口播「现在生成男女主形象参考图」（假话）+「重试」结束；且 protocol.md 承诺"暂停卡确认后生成视为明确指令"，闸机根本不认=契约断点。对照 外部标杆 双轴偏好（官方更新日志 2026-08-10 + 四份转录）：确认对象是**产物**（提示词草案先审后生成），花钱是提醒不拦截。用户裁决：不搬 外部标杆 设置页控件；轴 1 执行模式偏好直接不要且不登记；同意作用域=暂停卡接受的工作轮内有效。
- **批 9 · 同意账本 + 回合终止盲区**：①`consume_pause_response` accept 登记 `interaction.generation_consented_turn`(=turn_seq)，`tool_risk`/`gen_confirm` 两闸接同一意分支（工作轮内放行 provider 生成、audit 留痕 `consent=pause_accept`；decline/未登记/轮次推进 fail-closed 保持；非花钱高危不吃同意）；②全拒收轮不再按纯文本轮终止——`turn_executor` 上抛 `had_fc_calls`，agent_loop FC 分支纳入、全拒收跳过提前终止（max_steps 仍封顶，纯文本轮收尾语义不变）；③拒因文案升级（三条确认路径，删 C1a 已废"消息明确指示"暗示）。
- **批 10 · 引导层对齐外部标杆**：①执行偏好注入模型上下文——planner 轮始按档位签发 `execution_pref_note`（文案唯一源 `prompts/planner/execution_preference.md`，脏值回落默认档），经状态尾部消息每步可见，模型主动先审后生成（行为层，闸机兜底）；②工具边界注释每步刷新——`_build_system_prompt` 重跑 `_compute_excluded_tools`（原轮始冻结：同轮建组后旧注释"仅开放单张应急出图"滞留，9999 模型据其错选 mode=single），`_excluded_tools` 同步刷新；③设置页 confirm_before_gen 文案如实（先发暂停卡审提示词草案/草稿标已确认/点本次放行；确认后重提不再重复拦截——UI 文案待用户目测，宪法 §3.1）。
- **批 11 · 验收与治理**：9999 场景端到端冒烟进机器线束（`test_9999_consent_flow_smoke`：建组→直接生成→闸拦→指引回喂→发暂停卡→用户接受→重提放行且留痕→新一轮无同意再拦 fail-closed）；机器线束 16 份全绿；批末 `acceptance.py` 退出码 0（11 GATES + pytest + vitest + tsc + eslint + RATCHETS）；9999 事故清偿登记。
- **待用户目测**：设置页 confirm_before_gen 文案、暂停卡审阅交互（宪法 §3.1）。

### 2026-09-05 · Skill 流程跑通修复批 5-8（方案甲正向设计：A3 资产树转正）
- **立项**：8888 项目实测翻车诊断（分析连败放弃/建组形态跑偏/规格零写入/暂停卡只有题目没选项）暴露批 0-4 的补丁式修复不够——用户拍板**方案甲正向设计**：一次把产物模型对齐外部标杆 机制。依据 = 四份 外部标杆 一手转录 + 设置页/规格文档截图的机制推理（资产树+自由文本+动作即事实+skill 散文即流程+两层偏好）。
- **批 5 · A1 自由文本**：`script_analysis_report` 废弃自创结构化字段表（characters/scenes/acts 正是 8888 连败根因），收窄为「一句话锚点 + 自由文本报告」——外部标杆 同构（全程无字段表）；`stage_done("analysis")` 语义改「动作落账即事实」（summary=最小锚点，不解析报告内容）；context_builder 注入面/stage_deliverables 渲染器同步。func_imports 白名单缺口以顶层化 ToolManager 导入根治（非 refresh 收编）。
- **批 6 · A3 资产树落地**（D-17 转正清偿）：①建组规范引导进 `storyboard_create_group` description（一元素一组/组名=元素名/设定写 desc/分镜一镜一组+`[元素名]`令牌）——原语级引导非校验锁死；②draft 字符串宽容解析 `coerce_draft_payload`（8888 高频误用：draft 传 JSON 字符串）；③令牌解析器 `parse_element_tokens`+`match_element_titles`：分镜 desc 的 `[元素名]` 自动同步 sceneRefs（显式传以显式为准、匹配不到丢弃不拒收）；④音色锚点自动挂 `resolve_scene_audio_refs`（sceneRefs 元素 audioUrl → reference_audio，图轴的姊妹轴）；⑤「资产已注册」事件卡（M8 预留位兑现，keyElement 建组双卡）；⑥修复手动批量生图路由收集 refs 却漏传 `reference_images` 的一致性缺陷。调研确认：sceneRefs→resolve_scene_refs→submit_image/video 的挂载骨架批 1-4 已存在，本批补齐的是入口与音色轴。
- **批 7 · 前端两 bug + 协议开场纪律**：①暂停卡"只有题目没选项"双因修复——模型把维度名当选项 label（工具 description 强引导：label 必须是具体可选值、维度名放 group、候选禁用"|"拼接）+ `pickDimension` 兜底误判空下拉加严（命中过半且 ≥2 项 + 对应类别真实配置了厂商，否则回落选项卡）；②对话流滚轮跳动——wheel/touchstart 直控跟随开关（scroll 事件在钉底期被 pinning 豁免吞掉是拉回根源）+ rAF 续期前复查 autoScroll；③`protocol.md` 补「开场盘点（外部标杆同款）」元纪律（自述流程计划+盘点已有产物+条件式启动；流程顺序以 skill 散文为唯一依据，本协议不规定顺序不设拦截——回应用户"不锁顺序"立场）。
- **批 8 · 验收与治理**：批末 `acceptance.py` 退出码 0（11 GATES + pytest 2068 + vitest 866 + tsc + eslint + RATCHETS）；线束 15 份全绿（A1 新参数形态）；D-17 销账。
- **待用户目测**：暂停卡分页向导选项渲染、对话流滚动手感（宪法 §3.1）。

### 2026-09-05 · Skill 流程跑通修复批 0-4（计划书 v5 全量执行；15 包裁决）
- **立项与对齐标尺**：`docs/Skill流程跑通修复计划书-v5.md`（外部标杆 一手转录 + 全局设置页截图对齐）。做法 = skill 一行不改，把平台补成能接住 外部标杆 skill 的样子。
- **前置裁决（2026-09-05 用户）**：①存量 skill 删「剧本生视频需上传剧本」→ 存量 **15 包**（字节级目录/章节快照同步重采，`test_global_settings_authority.py` 随被测对象删除）；②草稿卡审阅形态维持现状（不新增「素材生成前确认提示词」开关）；③设置页文案采纳候选 a（先把假话说成真话）。
- **批 0（bug 清偿）**：设置页失真文案改真话（`ExecutionPreferenceSection` 不再承诺「Skill 声明的暂停点不可被跳过」——该机制从未存在）；**pause 声明化石链整链删除**（`parse_pause_rules` / `_PAUSE_RULES_BLOCK_RE` / `_lint_prose_obligations` + 相关 lint 与测试），退役符号入 `check_legacy_orchestration` FORBIDDEN 防复活。
- **批 1 造格子**：A1 新工具 `script_analysis_report`（分析结论唯一落点；命名与能力词 `script_analyze` 刻意区分防幻影词回潮，`prompts/planner/protocol.md` 同批改写「分析结论直接写入回复」旧口径）——既有消费方零改动生效（stage_done 探针 / 阶段成果渲染器 / context_builder 注入）；A2 草稿 `desc` 字段落盘 + 白名单外原子拒收（`ALLOWED_NEW_DRAFT_FIELDS`），前端 DraftCard 空卡展示 desc；A4 规格文档可更新留痕（`revisions` 计数）。
- **批 2 插播报**：具名事件卡（`core/event_cards.py` 唯一映射表；`progress.emit_event_card` 双通道 = trace 子步骤 + 时间线帧）——规格已完成（建立/更新都发）/ 故事板已更新 / 素材已完成 / 时间线已更新 / 信息搜索完成（只进时间线不进上下文）；写产物卡进模型上下文（flowEvents 环扩至 6 条）；「素材变更已同步」卡 = 整板落库媒体指纹 diff 记 `media_synced` → 轮始一次性播报（`StateManager.consume_flow_events`）。Skill 已加载卡沿用开场既有 emit 点。
- **批 3 会喊疼/消干扰/拆伪按钮**：B1 工具边界提示去指令化（删「请先搭建…」，留客观描述）；B4 `suggest_next_actions` 族 + `current_node_title` 整体退役（平台不再算"下一步"，防复活入 FORBIDDEN；假停继续按钮 label 固定「继续」）；B3 账本重算收敛到写动作落账（`WorkflowRuntime.ensure_run` 轮始轻量、`commit_turn` 落账后重算）；B5 失败回喂加全局状态保留声明（`compose_failure_feedback`）+ storyboard 写类工具报错三要素（原因/保留声明/补救指引）；B6 显式草稿 id 查重写入前拦截（`ops.draft_id_exists`，外部标杆「镜头 ID 重复」标尺）。
- **批 4 冒烟重放（两层）**：机器门禁 `tests/unit/test_skill_smoke_harness.py`——scripted 假模型 × 15 份 skill × 标准产物序列（含 workflow_pause → 用户回复 → 续作），逐份断言 §五 平台事实（无假成功/会喊疼/事件卡/无干扰/不死锁/失败原子性）；漂移 lint `scripts/check_skill_anchor_lint.py` 入 GATES + ci.yml（V3-3 收窄口径：只查 planner 必备/锚点合法/开闭配对）；判官观察层脚手架 `scripts/judge_replay.py`（对照包打包，不进门禁、不设阈值；真模型跑 + 人工打分留待用户按 V5-2 节奏执行）。
- **缓办登记**：A3 槽位-令牌-解析 → `docs/未清偿债务清单.md` D-17（机器门禁全绿后评估立项）。
- **验收**：`python scripts/acceptance.py` 退出码 0（11 GATES 含新 skill_anchor_lint + pytest 2061 + vitest + tsc + eslint + RATCHETS）；机器线束 15/15 绿。
- **待用户目测**：A2 草稿卡 desc 展示、批 2 事件卡里程碑行样式（宪法 §3.1）。

### 2026-09-04 · 收尾后用户裁决批（断点续跑立项 + 三项登记）
- **背景**：对两次会话（全面深度审核 + 裁决落地）做执行完整性核查后，报告 3 条「悬空项」——审计提出但既未执行也未登记也未裁决的发现，交用户逐条拍板。
- **裁决**：
  - **断点续跑：做**——重启后生成任务从检查点继续；原审计 D-23 后半（优雅关停前半已由后端批清偿）。
  - **paths-ignore 不加 → 登记冻结清单 #15**（系审计「CI 四项配置」唯一不采纳项，防重复提案）。
  - **登记债务 D-15**（全局异常兜底 + 安全响应头，公网部署前必修）与 **D-16**（数据层 schema_version / migration，随下次存储格式改动一并做）。
- **断点续跑落地**（`web/video_batch.py`：批次表本就持久化 + 逐镜状态 + resume，本批补齐重启/取消盲区）：①重启加载（`_load`）与取消（`cancel`）时，把卡在 running 的镜降级 interrupted（`_normalize_orphan_running`，此前 resume 不认 running 镜 → 永久卡死、批次永远差一镜）；②`resume` 前先归一 + 计数器按当前镜态重算（修复「续跑全成功终态误标 partial」）；③前端 Job 面板补镜级「已中断」标签。回归：`tests/unit/test_video_batch_queue.py` 6 条（真实落盘 `_load` / 卡死镜重试 / 取消归一 / 续跑全成功终态 done）。
- **登记纪律**：D-15/D-16 编号顺延本清单（未清偿债务清单）自身序列，与深度审核报告的候选编号（D-11~D-28 多数已当场清偿未登记）无对应关系。

### 2026-09-04 · 三维评审返修批（任务11；Chloe 后端 / Robin 闸脚本+canary / Hunk prompts）
- **评审入口**：完整性 Mark / 正确性 Ryan / 影响面 Daniel 三路独立审查本轮 9 个实施批的落地物，结论收敛为「2 Critical + 8 Warn + 7 Sugg/Low」，按文件归属分三路并行返修。
- **Critical-1 ETag 跨项目串台**：原 ETag 仅由 `board_version` 派生，而该账本每项目独立、新建/分叉从 0 起算（非单射）→ 浏览器可 304 命中另一项目的缓存体。改为 `project_id` + `board_version` 双因子弱校验子（`W/"{pid}-{bv}"`）+ `Cache-Control: private, no-cache` + `If-None-Match` 按 RFC9110 弱比较（剥 `W/` 比 opaque-tag，`*` 通配）。
- **Critical-2 trace 分级留存 100% 空转**：压缩目标是刚被 `rename` 掉的主文件（轮转后已不存在 → 立即 return 全零）。改为压轮转产物 `.jsonl.N`（存在才压），主文件的老化记录另由 lifespan startup 单点 `compact_persisted()` 补压；同批加模块级串行锁、`trace_retention_enabled`（默认关）× `log_file_enabled` 双守卫、首次实质压缩前 `.pre-compact` 备份、保守销毁边界（无/非法 timestamp 计 hot 不当 cold 销毁、损坏行原样保留单独 corrupt 计数）+ timestamp 解析健壮。
- **Warn 八项**：`check_layer_imports` 相对导入还原后判定（原只认绝对导入、可绕）、`check_category_keys` 计数搭车与 `--refresh` 空扫描清零、`check_prompt_literals` 双向前缀漏报（改「精确相等 + 单向显式前缀」）、`cache_metrics.jsonl` 无界（增 `cache_metrics_max_bytes` 滚动上限）、loguru `%s` 误用清零、关停 `_SHUTTING_DOWN` 无复位（startup 无条件复位 + `handle_exit` 前置位）、**PUT 整板 422**（请求体回退宽松 `List[Dict]` + `_coerce_elements` 逐元素软校验，非法元素丢弃并记 `record_degradation`；取舍与契约面退化风险登记入 `docs/未清偿债务清单.md` D-06）、prompts 两条件模板补注入条件注释。
- **契约漂移收口**：上述 PUT 请求体宽松化后未重跑 `scripts/gen_api_types.py`，`api.generated.ts` 仍带 6 个类型化 interface → contract 闸红。重新生成后与后端一致（请求体在契约面为 `Record<string, unknown>[]`，与本批开工时的 HEAD 基线同形——6 个类型化 interface 系返修中途态产物，非既有契约资产）。
- **canary 增量**：`test_gate_canaries` 44 → 71 条、`test_category_keys_frontend` 8 → 16 条（每个闸脚本缺陷均配「会咬人」的 FAIL 侧反例，非正例空转）。
- **暴露的新债务**：评审收紧后暴露 3 处真实产品 prose 仍硬编码，带理由登记 `DECLARED_PREFIXES` 并上交外置（明细与销账条件见 `docs/未清偿债务清单.md` D-14）。
- **不修项**：css_size / entry 体积闸重加属门禁增减（用户裁决面）→ 登记 `docs/冻结与暂缓清单.md` 第 14 项防翻案；vite chunk 命名 / `.claude` 出仓 / max_steps 行为注记 → 已评估不采纳（无用户可见影响或既裁决），不登记债务。
- **验收**：`python scripts/acceptance.py --with-eval` 退出码 0（10 GATES + pytest 2118 + vitest 865 + tsc + eslint + cov 88.33% / fe_cov 71.18% + eval_pipeline）。

### 2026-09-04 · prompts 物理重组（任务21，Hunk；用户裁决选 A）
- **目录收缩 23 → 14 文件**：`planner/{protocol,skill_runtime,adjust,feedback,compaction}` + `gates/messages` + `shared/{degradation,global_settings,iron_rules_header,selected_draft,session_summary,retry_resume,skill_inject,storyboard_progress}`。
- **三处合并**：`planner/system_fc.md` 连同其 6 个 `{{include}}` 段落全部展开内联为 `planner/protocol.md`（协议正文单文件，include 拼装机制随之消失）；`shared/skill_load_reject.md` 折入 `planner/skill_runtime.md`；`shared/skill_catalog.md` + `skill_selected.md` + `skill_source.md` 合并为 `shared/skill_inject.md`。
- **装配等价校验**：`_dump_before` / `_dump_after` 逐条比对，差异**仅**「复述收敛」与「语气转化」两类 → PASS；校验用临时脚本已删（不留仓内垃圾）。
- **复述收敛**：消除跨文件重复陈述（防「单一定义源」虚报）；现行规则家 = 宪法 Rule 6，本条不复述。
- **turn_budget 改客观步数**：进状态尾部（「步数：N/M」，P3 状态即数据）；同批删除已无消费方的死参数。
- **语气转化**：`core/fc_feedback.py` 移除 `READ_RESULT_NOTE` / `IMAGE_RESULT_NOTE` 说教式附注。
- **指针同步**：`scripts/check_doc_pointers.py` ANCHORS 的 `prompts/planner/system_fc.md` → `protocol.md` 由本批自行更新（ref_integrity 恢复绿）；宪法 Rule 6 两处文件名指针由阶段2治理批（任务20）跟进，Rule 6 的 `{{include}}` 机制描述由收尾批（任务28）改为现行陈述（协议正文单文件内联、`shared/` 为条件注入模板）。

### 2026-09-04 · 前端批次1（任务22，Cindy）
- **`check_category_keys` 扩面到前端**：扫描面增 `src/web` 的 `*.ts` / `*.tsx`；测试夹具（`__tests__` / `*.test.ts(x)`）在扫描面外，与后端「只扫产品代码、tests/ 在外」同口径。
- **单一事实源与豁免分层**：`src/web/lib/state-keys.ts` 设为永久合法出口（`WHITELIST_FE`，前端 CAT_* 常量唯一家）；其余存量合法点（TS 类型联合位置 / subTab 页签标识）登记于新建**收缩型基线** `scripts/category_keys_frontend_baseline.txt`（只减不增，与 `func_imports_baseline.txt` 同机制）。
- **消除自我声明脱钩**：`state-keys.ts` 原头部的假安全声明修正为与闸实际行为精确一致的表述。
- **消 `studio-*` 双同名**：`stores/studio.ts` barrel 并入 `stores/studio/index.ts`，对外导出面不变、importer 零改动。
- **canary**：新建 `tests/unit/test_category_keys_frontend.py`（8 条），锁前端扫描面 / 白名单 / 基线收缩行为。

### 2026-09-04 · 前端批次2（任务23，Sarah）
- **Job 面板**：新建 `src/web/api/jobs.ts` + `stores/jobs.ts` + `components/layout/JobsPanel.tsx`，接 video-batch 列表 / 详情 / resume / cancel 四端点。
- **共享确认组件收编**：`components/docs/DocsPanel.tsx` 裸 `confirm` 改走 `confirmDialog`（`components/shared/ConfirmDialog.tsx`）。
- **a11y**：四模式扫描 + 白名单归零 + 棘轮；修 conv-tabs 补 `role="tablist"` 消除 critical 存量。
- **trace 分级留存**：归后端独立模块 `utils/trace_retention.py`（hot 24h 保留全量 / warm 7d 压缩为摘要 / cold 由既有轮转丢弃），`core/tracer.py` 轮转接入。
- **tokens/sec + 整程计时**：消费 SSE `elapsed_ms` 与 `trace.token_usage`。

### 2026-09-04 · 后端批次（任务24，Chloe）
- **SSE 载荷改投影**：`done` / `actions_applied` 由全量快照改走 `state/manager.py::get_board_projection()` = 11 键投影（9 个板键 + `chatMessages` + `board_version`），保留 `elapsed_ms` / `turn_id` / `snapshot_id` / `workflow` / `final_payload`（含 trace）。
- **state GET 条件请求**：加 `ETag` / `If-None-Match` / `304`。
- **EventLedger 索引化**：`core/workflow_events.py` 增 `by_run` 索引 + 事件缓存增量同步，检索由「每次全表重建 + 线性过滤」改为摊销 O(1) 建 + O(k)/run。
- **优雅关停**：`shutdown_grace_seconds=30`（原硬编码 3s 过短、长生成轮次被截断）+ 关停时向在途 SSE 投递终态帧。
- **缓存遥测落盘**：`data/cache_metrics.jsonl`（路径归 `utils/paths.py`、写入在 `utils/live_metrics.py`），与 `log_file_enabled` 同守卫防多进程争用。
- **Settings 分组**：12 组嵌套（`SETTINGS_GROUPS`：agent / canvas / context / llm / mcp / media / metrics / security / server / skills / storage / tasks）+ `_SettingsGroup` 只读委托视图（属性访问实时委托底层扁平字段）；**env 键名 / 扁平属性 / 热更新行为全不变**。
- **`.env.example` 机械生成**：新建 `scripts/gen_env_example.py`，同批声明 `TRACE_HOT_WINDOW_S` / `TRACE_WARM_WINDOW_S` / `TRACE_WARM_REASONING_MAX` 三字段（tasks 组，缺省值与 `utils/trace_retention.py` 默认一致）。

### 2026-09-04 · adapters 残留环边清零（任务25，Chloe）
- **cancel_token 下沉**：`adapters/cancel_token.py` → `utils/cancel_token.py`（跨切面原语，与 `stop_signal` / `provider_config_loader` 同层；各层单向依赖 utils 而非互相依赖）。
- **共享数据类下沉 + 端口倒置**：`ChatResponse` / `StreamChunk` 抽出为 `core/chat_port.py`（契约由 core 拥有）并增结构化端口 `ChatAdapterPort`（Protocol）；`BaseChatAdapter` 保留在 `adapters/base_chat.py` 作 Rule 4 宪法锚点，adapters 侧反向 re-export → 旧导入路径不变。
- **canvas_adapter 端口倒置**：改经 `core/ports.py::canvas_online_cached()` 端口（`web/port_wiring` 装配），`core/planner.py` 消除方法内延迟 import。
- **门禁收缩**：`scripts/check_layer_imports.py` 的 `R2_BASELINE` 由 8 条 core→adapters 环边收缩至**空集**（此后新增即 FAIL）。
- **宪法同步**：现行规则家 = 宪法 §六「层间依赖方向」子节 + §十一 文件地图（`core/chat_port.py` 与 `utils/` 明细行），由收尾批（任务28）补齐——下沉前宪法未陈述该规则，属「被三处 docstring / 门禁提示引用而正文空缺」的缺口。

### 2026-09-04 · ci.yml ↔ acceptance.GATES 名集对账 canary 落地（任务26，测试侧防复发兜底）
- **缺口**：门禁的「自我声明」（`scripts/acceptance.py::GATES`）与「事实接线」（`.github/workflows/ci.yml` 实际跑的 step）此前靠人工比对，一侧增删而另一侧漏改不会报错（静默掉闸 / 孤儿 step）。
- **机械身份 = 被调用的 `scripts/*.py` 路径**：GATES 的 `name` 是标签、ci step 的 `name` 是自由散文，二者不可直接比；唯一两边都稳定可比的是实际执行的脚本路径。对账函数落在 `tests/unit/test_gate_canaries.py` §11c（`_parse_ci_scripts` 从 ci.yml 抽脚本路径、`_real_reconcile_inputs` 取真实两侧输入、`_reconcile` 双向求差）。
- **双向断言 + 反例钉死**：`test_canary_ci_gates_reconcile_real_consistent`（正例：无漏接 `missing`、无孤儿 `orphan`）、`test_canary_ci_gates_reconcile_missing_gate_fails`（删一个已登记 gate → `missing` 非空）、`test_canary_ci_gates_reconcile_orphan_step_fails`（注入未登记的 `scripts/check_ghost_gate.py` → `orphan` 非空）——后两个反例确保「对账会咬人」而非永真空转。
- **门禁未增减**：`_EXPECTED_GATE_NAMES`（防静默掉闸的门禁表完整性 canary）本批未变，GATES 仍为原有集合；本条属**测试侧**防复发兜底，不改任何门禁语义与容差。

### 2026-09-04 · CHANGELOG 历史留痕物理分卷（任务17 / R-6，纯文档治理）
- **分卷**：§二 中 **2026-09-01 及更早**的 9 个日期小节（09-01 / 08-31 / 08-29 / 08-27 / 08-21 / 08-20 / 08-19 / 08-18 / 08-12）**verbatim 物理迁至新建 `docs/history/`**（`2026-09-01.md` / `2026-08.md`），不改写历史正文（迁出前后逐字节比对一致，仅加卷首源流说明）；本文件 281 → 242 行（含本条留痕与新增 §五 索引）。
- **分界点与判据**：§二 保留 **2026-09-02 起**（「治理闸机减负」= 现行闸机形态起点，其后各批相互引用密集且被 §一 / §三 / §四、`AGENTS.md` §七、`docs/未清偿债务清单.md` 段级引用）；迁出侧条目所属裁决时代已封闭、编号已由 §一（ADR）/ §三（任务与内部编号）对照表承载。明细见 §五 索引。
- **新增 §五 历史分卷索引**：逐卷登记覆盖日期区间与内容概要 + 分界点 / 迁出判据 / 不改写原则（供后续分卷沿用）。
- **inbound 指针同步**：宪法头部「需要出处时查该文件」补分卷说明、宪法 §五 血泪条款「事故经过见 CHANGELOG.md」直连 `docs/history/2026-08.md`；本文件头部与 §二 顶部留重定向（泛化指针一跳可达）、§四「历史审计文书」落点补分卷；`AGENTS.md` §四 加 `docs/history/` 行（为守 ≤60 行目标，同批将未清偿债务清单与冻结清单两行合为一行，信息不减）。
- **门禁影响**：`docs/history/` 属历史档案子目录，按 `scripts/check_doc_pointers.py` 现行口径不受 docs 模块指针检查（该脚本只 glob `docs/*.md` 顶层）；分卷内保留的当时原貌指针（如 `prompts/planner/system_fc.md`）不构成门禁死指针，现行落点由 §三 对照表承载。

### 2026-09-03 · 阶段2治理文档瘦身（任务20，纯文档治理）
- **AGENTS.md 瘦身为纯入口索引**（120 → 60 行）：§一 由 10 条删至 5 条（P2 约束下沉 / 闸门做减法 / 状态写入归属 / Skill 指令性制作手册 / UI 目测 五条复述删除，改指宪法与 `docs/GOVERNANCE.md`）；§五 门禁枚举删除只留指针；§六 冻结 / 暂缓明细迁出改 1 行指针；§七 台账条款改指针；§八 治理条款整体迁出、只留 1 行指针（章节号保留，避免外部「AGENTS §六/§八」指针失效）。
- **新建 `docs/GOVERNANCE.md`**：治理条款唯一家（三原则 P1/P2/P3、修复决策树、捷径禁令、方案四关 G1-G4、指令体量、门禁登记、错误信封、治理限速）；迁自 AGENTS §八，同批删除已失效步骤「→ 查耦合行」（耦合台账已根除，见本文件 F1）；「指令体量」条的文件名指针改目录级（`prompts/planner/`），避免随提示词重组漂移。
- **新建 `docs/冻结与暂缓清单.md`**：用户已裁决冻结 / 暂缓项唯一登记处（迁自 AGENTS §六 11 项 + 补登本轮裁决 R-5「A4 不加」、R-12「阶段6 评测管线不做」，防交接文档删除后失据）；第 7 项「机器眼睛代目测」的规则家收敛为宪法 §3.1 单家（原「AGENTS §一.8 + 宪法 §3.1」双家违反 P1）。
- **宪法 §三 重编号 + 去重**：§3.4 → §3.2（§3.2/§3.3 早已迁 `docs/前端体验规范.md`，编号断档修正）；前端规范 §三 与宪法 §3.2 重复的两条（唯一前端 src/web、类型契约 gen_api_types）改指针，前端规范侧只留品牌 / 视觉 / 交互与文案、断点条款（台账 #18/#19 标注条款家）。
- **过期声明清除**：`docs/配置说明.md` 与 `README.md` 的「记忆后端」配置声明删除（记忆层已随批次 D 退役、`.env.example` 无对应键）；`README.md` 目录导览 `skill_runtime` 描述改现行职责（执行器族已退役）；`scripts/archive/README.md` 清「季度脚手架审计」失效引用（脚手架台账已根除）+ 批次编号改指本文件。
- **本文件 4 处规则正文改指针**（CHANGELOG 不承载规则正文）：§一 尾注 adr-bilateral 现状陈述、裁决③（覆盖率棘轮显式上调，已被 B2 固定地板取代）、裁决④（新增门禁「退役条件」三件套，义务已随 F3 废除）、B5+D 连带影响的 GATES 名单枚举（含已退役 `css_size`、缺三道新闸）。
- **指针同步**：宪法头部 / 治理总纲第 7 条 / §十二 违规清单由「AGENTS §八治理条款摘要」改指 `docs/GOVERNANCE.md`；本文件 ADR-0007 落点、2026-08-29 冻结项活表述、批次 D 落点、§四 归档索引三行同批改指新家；`README.md` 文档索引同步。
- **顺带清死指针（并行批产物）**：提示词物理重组（任务21）将 `prompts/planner/system_fc.md` 改名为 `protocol.md`、`skill_discipline.md` 内容并入 `skill_runtime.md`；本批同批更新宪法 Rule 6 两处文件名指针与本文件 §三「任务#6 C-1」落点（`scripts/check_doc_pointers.py` ANCHORS 已由该批自行更新，ref_integrity 恢复绿）；本批开工时拍到的 ref_integrity 红即此根因，非本批引入。

### 2026-09-03 · 用户裁决新增 prompt_literals 门禁（R-4）
- **裁决**：R-4 =「A3 硬编码 prose 完整性闸 加」。门禁增减属宪法 §2.3 用户裁决事项，本条留痕。
- **门禁**：GATES **新增** `prompt_literals`（扫描器 `scripts/check_prompt_literals.py`）——AST 扫 `core/state/web/tools/adapters` 五目录，CJK 且长度 ≥8 的硬编码 prose（进模型上下文 / 用户可见气泡）非外置 `prompts/` 或未登记脚本内 `DECLARED_DATA`（带理由）即拒收（约束下沉 P2、提示词外置 Rule 6）；7 层结构豁免（docstring / 函数体 / 类体 / Call 参数 / Return / f-string 片段 / `description=` 赋值）。
- **落地**：`scripts/acceptance.py` GATES 表加 `prompt_literals` 条目；`.github/workflows/ci.yml` backend-test job 接线对应 step（与本地 acceptance 同构）；`tests/unit/test_gate_canaries.py` `_EXPECTED_GATE_NAMES` 同步 + 补 FAIL/PASS 双向 canary；唯一未登记命中 `tools/document_tools.py` 的 `_TARGET_VALID_HINT`（target 合法取值枚举，结构化报错数据非 prose）登记进 `DECLARED_DATA`。门禁清单以 `scripts/acceptance.py` GATES 表为唯一事实源。

### 2026-09-03 · 用户裁决退役 css_size 门禁（R-2）
- **裁决**：退役 `css_size` 门禁（镜像基线反模式，`scripts/css_size_baseline.txt` 基线曾被上调 5 次 152752→161853，与已退役的覆盖率镜像基线同构）。
- **落地**：`scripts/acceptance.py` GATES 表删除 `css_size` 条目；`.github/workflows/ci.yml` build job 删除对应 step；删除 `scripts/css_size_baseline.txt` 与 `scripts/check_css_size.mjs`；`tests/unit/test_gate_canaries.py` 同步。门禁清单以 `scripts/acceptance.py` GATES 表为准。

### 2026-09-03 · 四路深度审核 → 三维独立审查修复批（裁决 Q1-Q4；I-1~I-4 / M-1~M-6 / D-06 / D-09）
- **背景**：一次四路深度审核暴露系统性臃肿/旁路/死规则，用户要求「彻底修复所有暴露问题、正向设计、不打补丁、不引入新问题」；主体修复后再经**三维独立审查**（完整性 / 正确性 / 影响面）复核，据其发现同批再修一批（下列「审查发现」项）。
- **用户裁决**：
  - **Q1** 批准全部关卡（门禁）改动。
  - **Q2** `gate_heal` 退役 + FORBIDDEN 加锁——**结案**下方「会话中断承诺清偿批 R2」遗留的「gate_heal 恒不触发是否有意设计」待批 C 会签项（文本轨退役后 gate_rejections 恒空、total_exec 恒 0，生产路径永不可达；FC 轨闸机拦截已由 fc_gates reject_message 回喂闭环）。
  - **Q3 / M-4** 走路 B：删只读并行（`readonly_parallel`）做减法。
  - **Q4** I-5（chat_service 893 行拆分）**不做**；D-06 + D-09 **做**。
- **批次落地**（逐项与代码核对，每批 `acceptance.py --quick` 退出码 0）：
  - **I-1** 轮末死规则收敛（`round_end_policies.py`）：`gate_heal` 退役（Q2）；**审查发现** `partial_fail_warnings`（轮末工具失败汇总策略）生产唯一构造点 ledger 恒 None、FC 批轮永不到轮末→恒不可达，按 gate_heal 同口径退役（删策略 + `RoundEndContext.ledger` 死字段 + FORBIDDEN），工具部分失败已由 FC 轨 `fc_feedback.compose_failure_feedback` 逐步回喂承接；`applied=0` 死值→`result.applied_actions` 真实累计值（假停判定才可达）；`structure_stage_review` 死副本合并进活实现 `fc_reconcile._reconcile_stage_review_card`；登记期自检 `_validate_policy_table` 强化为 AST 拦 `getattr(ctx,...,默认值)` + condition/apply 实访 ctx 字段集与 `requires` 三段交叉核对；补轮末可达性集成回归（`test_fc_leak_fakestop.py`）。
  - **I-2** 旁路面拆除：删 `web/generation_dispatch` 绕过 Planner 的 chat 直调函数（`call_chat_completion[_stream]` 直接构造 OpenAICompatChatAdapter）+ `web/generation.py` re-export + FORBIDDEN；新门禁 `check_web_chat_bypass.py`（web/** 禁止直接构造 *ChatAdapter，唯一合法构造点 = adapters/factory.py）。
  - **I-3** provider 注入声明驱动：抽象为工具登记期属性 `provider_kind`（tools/base.py，与 risk/costly 同轴）+ `core/provider_injection.py` 统一注入器（按类声明发现，调度器不感知工具内部形态）+ 消除 `fc_tool_runner` 工具名字面量 + 新门禁 `check_fc_tool_name_literals.py`；**审查发现**新造的 `get_tool_provider_kind` 死接口已删；调度器剩余非-provider 轴按名分支登记为债务 **D-10**。
  - **I-4** `acceptance.py` 重构为 **GATES→SUITES→RATCHETS** 三阶段：覆盖率棘轮移到测试之后读本轮新鲜产物（带 mtime 证据），`--quick` 跳过 RATCHETS（无新鲜产物 = 不假装校验）。
  - **M-1** 删 `gate_registry.normalize_rule_id` 恒等函数 + FORBIDDEN 锁。
  - **M-2** `agent_loop` 内联兜底改显式最小占位；**审查发现**工具轮占位「（本步无输出）」是常态路径假陈述且与 STEP_FEEDBACK 矛盾→改外置客观分节 `STEP_ASSISTANT_PLACEHOLDER`（读不到退化空串，不内联兜底消除双源）。
  - **M-3** 宪法 §六 增状态写面分类表。
  - **M-4** 删 `readonly_parallel` 只读并行（路 B）+ 模块/测试/config 开关 `readonly_parallel_enabled` + FORBIDDEN（批内工具一律串行）。
  - **M-5** AGENTS §八 两处过期「台账」引用对齐 §七。
  - **M-6** 删 `data/gate_trigger_counts.jsonl` 死文件；`fc_feedback` 两处 prose 从数据体抽到外置分节 `READ_RESULT_NOTE`/`IMAGE_RESULT_NOTE`（P3 状态即数据）；**审查发现**其内联兜底重造双源→去除。
  - **D-06** 保存路径元素模型统一 `extra="allow"` + `ProjectStateUpdate` 五列表类型化 + `_dump_elements`（model_dump by_alias/mode=json/exclude_unset）单点回转 + 往返零丢失回归（`test_project_state_roundtrip.py`）+ `api.generated.ts` 重生成（FrontendAsset EXEMPT 登记）；前端消费面残留仍挂账（见债务清单 D-06）。
  - **D-09** 暂停旧卡作废标记：`StageCard` expired 旧卡挂 `stage-card-void`（语义色 token，去翡翠绿改中性灰 + 标题删除线）+ 点击 Toast 反馈（`rp.msg.expiredCardClick`）+ 组件/CSS 契约测试；作废卡 `confirmTarget=false` 不渲染选项按钮，无「降级普通文本」路径。**属 UI 改动，测试全绿 ≠ 交付，须构建后用户目测确认（宪法 §3）**。
- **门禁变动（宪法 §2.3 用户裁决事项，Q1 批准，必须留痕）**：
  - GATES **新增** `web_chat_bypass`、`fc_tool_name_literals` 两道（本地 acceptance 与 `ci.yml` backend-test 同构接线）。
  - `cov_ratchet`/`fe_cov_ratchet` 从 GATES **移入独立 RATCHETS 阶段**（I-4：覆盖率本质是测试产物的后置断言，读本轮新鲜产物）。
  - `--quick` **不再含覆盖率地板**（归批末全量 RATCHETS）；GATES 现 10 项（清单以脚本内表为唯一事实源，不写死数量）。
- **文档/CI/前端收口（本批）**：`ci.yml` 接线两道新门禁 + 计数注释去写死数字；前端删死 locale 键 `agent.gateHeal`（后端 `_apply_gate_heal` 退役、无发射点）；宪法 §十一 文件地图补登 `provider_injection.py`、§六 写面表补「配置写面」行、Rule2/§十二「展示层作废标记未实现」随 D-09 销账改为「已实现」；债务清单 D-09 清偿销账 + D-06 交叉引用修正 + 新增 D-10；AGENTS §二 补「--quick 不含覆盖率地板」口径。

### 2026-09-03 · 会话中断承诺清偿批（R1-R3，接续 Qoder 会话中断点对账后）
- **背景**：用户要求自 Qoder 会话导出起全面对账。对账发现三类「已承诺未兑现」的中断残留：①上批承诺「guard_pipeline 死指针 + GATE_TRIGGER_COUNTS 遥测写者随后一次性修掉」未兑现；②三维审查（Daniel）交付的 4 Major/5 Minor 修复项全部未处理；③「退役条件」之外还散落个别元治理表述。
- **批次落地**：
  - **R1** 根除 GATE_TRIGGER_COUNTS 遥测写者：`guard_pipeline.py` 删 `_append_trigger_counts` + 常量 + 锁 + 4 个 import；其唯一读者 `audit_gate_triggers.py` 已先随 B3 退役，写者属无消费者纯开销（业界无人做此类折旧遥测）。连带删 conftest 隔离夹具、test_gen_confirm_gate 遥测断言（tracer 审计断言保留，留痕语义不降级）。
  - **R2** 根除 action_executor 五恒空字段（`action_log`/`documents_written`/`chat_inserts`/`gate_rejections`/`skill_name`）：生产路径零写入、FC 轨 collector 才是实际来源；`planner_output` 4 处合并口、`agent_loop` 2 处读取（skill 解析唯一口径收敛为 usedSkills 兜底）同批删。gate_heal「恒不触发是否有意设计」待批 C 会签项已由上方「四路深度审核 → 三维独立审查修复批」Q2 裁决结案（退役 + FORBIDDEN 加锁）。
  - **R3** 三维审查遗留项清偿：`eslint.config.js` 假安全表述（宣称有门禁把守，实已降信息工具）；`check_file_lines.py` 假安全表述（信息工具口径下仍写「CI 失败」）+ 两处棘轮基线注释改为参考基线；`gate_registry.py` docstring 自相矛盾（「无判定逻辑」vs「判定在 prompt_gates」）；交接文档 5 处过期数字（13 门禁→10、cov_baseline 指针→固定地板、88.08→地板口径）。
- **连带影响**：tracer.record_gate 审计链路（/api/agent/gates）零变化；`assemble_response` 的 `executor` 参数保留（`executor.state` 仍是活依赖）；Daniel 建议的「覆盖率地板收紧 87/70」属新增门禁强度变更，按闸机增减用户裁决原则**未采纳**（留用户定夺）。

### 2026-09-03 · 用户审定「元治理台账根除」裁决（批次 F）
- **背景**：比对业界 8 家主流 agent（Claude Code / Codex / OpenHands / 外部标杆 等）后确认，「闸机棘轮 / 冻结基线 / 脚手架折旧 / 耦合台账 / 退役条件」一类元治理机制**全部没有人做**；2026-09-02「治理闸机减负」只砍了仪式层、保留了台账本体，用户据此裁定**连台账本体一起根除**，不留尾巴。
- **裁决**：
  1. 耦合台账 `core/coupling_registry.py` + 遍历测试 `tests/unit/test_coupling_registry.py` **物理删除**；
  2. 脚手架台账 `core/scaffold_registry.py` + 其测试**物理删除**；
  3. `scripts/acceptance.py` GATES 与各闸机脚本头部的「退役条件」声明义务**整体废除**。
- **保留边界**：6 核心闸（`tool_risk` / `gen_confirm` / `prompt_write` 运行时安全闸 + `layer_imports` / `contract` / `legacy_orchestration` 架构闸）+ `category_keys` + `ref_integrity` 死指针检查保留——业界均有等价物（权限系统 / approval / 三级风险 / linter 架构约束），且实测有真实拦截。
- **批次落地**（每批 `acceptance.py --quick` 退出码 0 后独立 commit）：
  - **F1** 耦合台账根除：删 `core/coupling_registry.py` + `tests/unit/test_coupling_registry.py`；宪法 §2 P2 / §十 / §十一 文件地图 / §十二 违规清单四条引用同批删；AGENTS §一.4 同步；代码注释 6 处去指针（stage_probes / planner_triage / gate_registry / chat_service / state/manager / test_shell_payoff）；`docs/未清偿债务清单.md` §三 改为独立人读审查备注。
  - **F2** 脚手架台账根除：删 `core/scaffold_registry.py` + `tests/unit/test_scaffold_registry.py`；AGENTS §一.4 / §七 条款改写（§七 由「脚手架退役仪式」改为「已根除」留痕 + 归档件到期策略）；原台账 15 条登记符号的可导入冒烟检查不再单列——逐一核验已由各自回归测试覆盖（skill 回退/闸机升温/假停审计/降级遥测/暂停结构/上下文经济等），无覆盖回退。
  - **F3** 「退役条件」声明义务废除：`scripts/acceptance.py` GATES 表 10 条门禁与 `check_semantic_colors` / `check_layer_imports` / `check_func_imports` / `check_cov_ratchet` / `check_fe_cov_ratchet` / `check_css_size.mjs` / `audit_assets` / `check_doc_pointers` / `check_legacy_orchestration` 九个脚本头部的退役条件段落整体删除；顺带清两处失效指针（`check_doc_pointers.py` 与 `test_gate_messages_coverage.py` 仍指向宪法 §2.3 已删的「闸机冻结基线」）；`docs/交接-20260902…md` 两条「新增门禁须事故依据+退役条件」口径同步改为「事故依据 + 书面裁决」。全库「退役条件」零残留。
- **连带影响**：耦合表 26 行的强制项随之消失，其中 R18 / R22 / R26 / R28 等机械约束本已由各自门禁与回归测试独立覆盖（`test_gen_confirm_gate` / acceptance GATES / `gen_api_types` / `check_layer_imports`），无覆盖回退；`ref_integrity` 闸所检的宪法锚点与文件地图在同批同步更新，未留死指针。

### 2026-09-03 · 用户审定「委托壳与历史兼容层根除」裁决（批次 E3/H）
- **背景**：用户裁定「堆积的历史兼容层、委托壳、元治理台账」一次性解决；E3 指向上一批 deferred 的 `fc_tool_runner` 整族收敛（两个 R13 符号是登记哨兵，物理拆双层须整族收敛）。
- **批次落地**：
  - **E3a** 回喂 re-export 壳收敛：`fc_tool_runner.py` 顶部 14 符号 re-export 块 + `_PAUSE_WINDOW_READONLY` / `_STAGE_ALLOWED_GROUP_KINDS` 两个闸机常量别名删除；消费方（`core/turn_executor.py` + 6 个测试文件）全部直连实现体 `core/fc_feedback.py`。
  - **E3b** 闸机方法壳整族收敛：`FCToolRunner` 的 6 个闸机方法壳（`_resolve_current_refs` / `_prompt_gate` / `_strip_structure_prompt` / `_structure_integrity_gate` / `_gen_confirm_gate` / `_tool_risk_gate`）删除——`execute()` 早已直调 `fc_gates.run_gate_chain`，6 壳在生产代码零调用、仅测试引用；5 个测试文件（约 30 处调用点）改直连 `fc_gates` 各闸函数 + `GateContext`。非-manager 承重壳自此清零；`state/manager.py` 门面保留（Rule3 唯一写入点属架构决策，非委托壳）。
  - **H** 历史兼容层清偿：`agent_loop._unpack_llm`（旧 3/4 元组容忍）删除，改为 5 元组契约就地解包；`LlmCall` 别名自 4 元组声明修正为 5 元组（与全部生产实现一致）；约 30 处测试桩跨 14 个文件归一为 5 元组，透传桩在测试边界以 `_p5` 助手承担便捷写法（不再由生产壳兜底）。
  - **I1** `chat_consume.py` 按关注点拆分：会话压缩簇（13 符号：`_maybe_compact_history` + 采样/指纹/探针助手 + `_compact_card_enumeration` + `_summary_thinking_level`）切出至 `web/history_compact.py`；`chat_consume.py` 只留暂停态消费域（调用图零交的实证依据）。顺带删除退役规格向导管线遗留的 10 个顶层死 import；两处叶子模块 lazy import 上提 + 一处冗余函数内 `import re` 删除，`func_imports` 基线 101 → 93 只降不升。
  - **I2** `storyboard.ts` 内联**实测后判定不做**：该 19 行壳并非纯 re-export——`storyboardActions` 合并面若移入 `board-edit.ts`，实测（模块体打点）`board-edit` 先于 `board-sync` 执行完、合并点取到 `undefined`：既有依赖链 board-edit → board-sync → adjust-scopes → use-sse → chat/agent-state（多处引用 studio 组合出口）存在初始化序敏感的环，壳模块恰是环外稳定叶子。维持原判（与上批「前端 -core 破环层不动」同口径）：此属**依赖倒置承重层**而非堆积壳，强行内联 = 制造新 bug。
- **连带影响**：`readonly_parallel` / `batch_checkpoint` 经 `runner._dispatch_tool` / `runner._idempotency` / `runner.tool_manager` 消费，不涉被删壳；`planner` 消费 `execute()` / `reset_turn_tracking` / `costly_failures`，接口零变化；闸机判定路径（guard_pipeline 唯一实现）未动，仅消除测试侧的旧命名空间。`AgentTimeline` 经核查无 re-export shim（6 个消费方全部直连实现文件），无事可做。

### 2026-09-02 · 用户审定「治理闸机减负」裁决（做减法，批次 B0-B5+D）
- **背景**：治理闸机/门禁长期棘轮化叠加，累积大量镜像数字锁、幽灵闸（登记但从不签发 verdict）、纯仪式门禁（覆盖率镜像基线逐批上调、脚手架计数棘轮、行数硬闸）与折旧休眠机器，维护成本高于拦截收益。用户审定做减法，授权修改宪法 / AGENTS / 门禁 / 注册表。
- **裁决**：解除镜像数字锁、删幽灵闸机、覆盖率改固定容差地板、删脚手架棘轮 / 折旧机器 / 行数硬闸、清相关 prose；**保留 6 核心闸**——`tool_risk` / `gen_confirm` / `prompt_write`（运行时 3 安全闸，有实测拦截）+ `layer_imports` / `contract` / `legacy_orchestration`（架构 3 闸），另保留 `category_keys`（防硬编码）与 `ref_integrity` 的死指针检查（仅删其基线数字对拍）。
- **批次落地**（每批 `acceptance.py --quick` 退出码 0 后独立 commit）：
  - **B0**（04d5834）解除镜像数字锁：`test_coupling_registry.py` 去掉 `==26` 硬断言；`check_doc_pointers.py` 删 `check_gate_baseline_numbers()`（运行时 5 / 验收 13 基线对拍）；宪法 §2.3 删闸机冻结基线数字表。
  - **B1**（8a3f805）删幽灵闸：`gate_registry.py` 删 `platform.shot_min_chars` / `platform.element_min_chars` 两条 GATE_RULES + GATE_MESSAGE_SECTIONS 对应键（登记但从不签发 verdict）。
  - **B2**（dafaa61）纯仪式门禁减负：覆盖率棘轮改**固定容差地板**（`check_cov_ratchet.py` core=85.0 / `check_fe_cov_ratchet.py` fe=68.0，删 baseline 文件精确对拍与 `--update-baseline` 仪式）；acceptance GATES 删 `scaffold_registry` / `file_lines` / `file_lines_frontend` 三条 + 删 `check_scaffold_registry.py` + 删 ci.yml 对应 step（`check_file_lines.py` 保留为信息工具，eslint max-lines 维持 warn）。
  - **B3**（bf3b9af）删折旧休眠机器：删 `scripts/audit_gate_triggers.py` + 其测试；AGENTS §七 清「闸机折旧 / 连续 4 周期零触发降级 / audit_gate_triggers」条款。
  - **B4**（eb9c103）台账仪式层减负：`scaffold_registry.py` 删 `SCAFFOLD_COUNT_BASELINE` 棘轮常量（留数据删棘轮）；`coupling_registry.py` 删纯 prose 强制行 R14（壳到期制）/ R21（按钮基线），说明迁 `docs/未清偿债务清单.md` §三；R09 有 `file` 机械强制项，按判据**保留**。
  - **B5+D**（5789c74）清 prose：AGENTS §一.4 / §五 / §七 / §八 清棘轮 / 冻结基线 / 退役条件 / 书面裁决残余；**D** 将「`system_fc.md` ≤7KB 预算」prose 改为实话「展开后保持精简、靠人工审核」，**不恢复机械闸**；宪法 §十二 更新 file_lines 降级注记；`docs/未清偿债务清单.md` D-02 措辞同步。
- **连带影响**：GATE_RULES 由 5→3 条；acceptance GATES 由 13→10 项（名单不在本文件枚举，唯一事实源 = `scripts/acceptance.py` GATES / RATCHETS 表）；覆盖率不再逐批镜像上调，改为低于固定地板才 FAIL。本裁决为「只减不增」棘轮化治理的一次性反向减负，此后闸机增减由用户裁决。

### 2026-09-02 · 裁决③——覆盖率棘轮改显式上调（**已被同日「治理闸机减负」B2 取代**）
- **背景**：全量验收时 cov 闸 PASS 即半自动改写 `scripts/cov_baseline.txt`；叠加「门禁先于套件、读上一轮覆盖率产物」的顺序局限，每次全量都可能静默改基线——本会话发生两次静默改写，均手动还原。
- **裁决**：改为仅显式传 `--update-baseline` 才上调基线（fe3729c；后端 `scripts/check_cov_ratchet.py` 与前端 `scripts/check_fe_cov_ratchet.py` 同构）；日常门禁实测高于基线只打印 NOTE、不写文件。
- **现行口径（不在本文件）**：镜像基线与 `--update-baseline` 仪式已随下方 B2 退役，改为固定容差地板 + RATCHETS 后置断言；唯一家 = `scripts/check_cov_ratchet.py` / `scripts/check_fe_cov_ratchet.py`，操作口径见 `AGENTS.md` §二。

### 2026-09-02 · 裁决②——消息排队档2 取消
- **核查结论**：档2 主体早已实现——步间插话 / 轮边界注入（R3）、重试上下文还原、排队区可视化、队列消息可编辑与删除、失败保留、侧边打开；「立即发送 / 打断按钮」与「当前步骤不打断」的既定设计相悖。
- **裁决**：取消不做（不重复造轮子）；仅剩队列计数徽标、拖拽排序两件纯装饰记入待办，无事故依据不立项。

### 2026-09-02 · 裁决④——响应契约 phase2 门禁暂缓
- **结论**：path×method 存在性门禁（从 OpenAPI 派生合法集合、静态对拍前端 `api/` 调用）暂缓、记入待办、未立项。
- **现行口径（不在本文件）**：门禁增减由用户裁决（宪法 §2.3），清单唯一事实源 = `scripts/acceptance.py` GATES / RATCHETS 表；当时要求的「事故依据 + 退役条件 + 书面裁决」三件套中，退役条件声明义务已随本文件 F3 整体废除。

### 2026-09-02 · 裁决①轻量版——暂停槽表述对齐
- **背景**：宪法正文「重复暂停拒收留痕」与代码实际行为（旧卡作废 + trace + 发新卡 + 继续等确认，不拒收）矛盾，属 P1 单一事实源冲突。
- **裁决**：以表述对齐消除矛盾，代码行为不改（现状已正确）；宪法 / gate 文案 / fallback / 注释 / 测试 docstring 统一为「旧卡作废 + trace 留痕（pause_slot_collision）+ 发行新卡 + 继续等待人工确认，不拒收、绝不未经确认自动继续」。
- **暂停队列暂缓**：按旧卡所属 run 存活性分流「入队 vs 作废」暂缓，须待「同步双发卡丢真问题」的真实事故证据再升级（G2）。

### 2026-09-02 · 全面深度审核收尾批（对标外部产品/DeepSeek/Codex/Claude；8 commit）
- **背景**：全面深度审核完成后 P0 等 8 批修复。原登记于交接文档 §1，该文档随 2026-09-03 R-7 裁决删除，批次留痕迁此唯一家（只搬移不改写事实）。

| commit | 内容 | 验证 |
|---|---|---|
| 719f356 | P0：image_generate 批量轨双闸互让→豁免改有条件+24 组组合断言；generate_image 路由 docstring 修正 | 113 单测+--quick exit0 |
| 2f9a301 | 删除悬置脚手架 S09/S10，基线 8→6 | 2012 单测+93 集成+--quick |
| 3eb90ed | MCP 政策单一源+删虚假"不得旁路"+costly 底线只升不降 | 99+35 单测 |
| 6a9e74e | Skill 质检清偿：删孤儿 ~~eval/quality.py~~、eval error 级生效、卫生接 --with-eval WARN、能力词单源测试 | 137 单测+eval exit0 |
| 4f6de70 | 闸机文案孤儿：PAUSE_MESSAGE_SECTIONS 登记+删死孤儿 SPEC_DOC_OPTIONS+覆盖断言双向 | --quick exit0 |
| 404ceb6 | 小件清理：CLI 帮助断链修复、CI 补 css_size、白名单/D-03 销账、闸措辞改准、删 AGENTS§五/ARCH§十三 冗余 | --quick 14/14 |
| 5e43d2d | 响应契约 phase1：19 端点补 response_model、前端手抄改生成物别名 | vitest 859+gen --check 无漂移 |
| f343f56 | core 覆盖率基线 88.00→88.08 顺批登记（用户裁决，理由留痕 acceptance.py 注释） | check_cov_ratchet PASS |

### 2026-09-02 · 治理文档清理批
- **宪法去地质层**：正文内嵌的批次 / 裁决 / 事故注记全量迁至本文件，正文只留现行规则。
- **ADR 僵尸引用清理**：`docs/adr/` 已清空，全仓 78 处「ADR-000X」出处标注（76 行 / 39 文件）
  改为语义术语 + 归档指针；指针落点为 §一 对照表 + git tag `adr-archive-20260901`，消除指向空目录的幽灵引用。
  代码层按「每文件首个命中处放一次指针、同文件其余只保留语义术语」收敛，避免长指针成为新的考古噪声。
- **宪法 §十一 注记迁出**：`core/fc_feedback.py`（C3 落点）、`core/round_end_policies.py`（层 9 唯一落点）、
  `core/prompt_gates.py`（D-08 清偿）、`core/action_executor.py`（Q2 裁决）、`web/port_wiring.py`（D-01 / 任务#13 F-4）、
  `skill_runtime/frontmatter.py`（任务#5）、`tests/fixtures/`（C1a / C1b 夹具退役）等条目的编号注记迁出，
  文件地图只留现行职责描述。

<!-- 2026-09-01 及更早条目已 verbatim 迁至 docs/history/（索引见 §五），本处不留副本（P1 单一事实源）。 -->

---

## 三、任务编号 / 内部治理编号对照

宪法正文与代码注释曾内嵌的内部编号，现行规则落点见右列；编号本身只在本表留痕。

| 编号 | 结论（一句话） | 现行规则落点 |
|---|---|---|
| 任务#5 | Skill 声明唯一源 = 文档头部 YAML frontmatter（`name` / `description` 必填），外置 JSON sidecar 退役 | 宪法 §2.8 |
| 任务#6 C-1 | 剧本定稿入文档的编排约定单家在提示词外置资产（现 `prompts/planner/skill_runtime.md`） | 宪法 Rule 6 |
| 任务#9 | 熊布画布通道退役（阶段 7 彻底清理），infinite-canvas 单后端经 canvas-agent 协议 | 宪法 Rule 7 |
| 任务#12 | 渐进披露：`prompt_builder` 只注入 L1 目录与轻量状态提示，Skill 正文经 read_skill 按需读取；批次 B 拆除 L2 全文 / 分级 / 组合注入路径 | 宪法 Rule 2、§2.8 |
| 任务#13 F-4 | `web/port_wiring.py` 侧 action_executor 等 4 件 re-export 壳清退 | 宪法 §十一 |
| 任务#14 | 编排器正名：旧模块名 `pipeline_orchestrator` → `stage_probes` 纯数据层（同名复用即视为复活） | 宪法 §十一 |
| 任务#27 | 文本轨残留退役：`web.action_parser` 文本块解析通道 / `parse_actions_from_reply` / StudioActionExecutor 旧名（已更名 StateOperationExecutor） | 宪法 Rule 2 |
| 任务#36 B5 | 执行器族一步退役（`skill_runtime/executors`、`exec_common` 等）：管线阶段由通用主路径直走平台工具、无执行器子代理；执行器输出校验 / 黑匣子档案同批删除 | 宪法 Rule 2、§2.5、§2.8 |
| 任务#37 | MCP 外部工具接入层预留扩展点（尚未落地）；不得在注册表外私设工具通道 | 宪法 §2.8 |
| C3 | 工具结果回喂 / 压缩家族落点 = `core/fc_feedback.py` | 宪法 §十一 |
| D-02 | 单轮执行 / 回喂治理 / 预算装配切出 `core/turn_executor.py`，planner 保留委托 | 耦合行 R27 |
| 批 6 | frontmatter `resources` 素材清单形状校验（`manifest_schema` 首版 WARN） | 耦合行 R16 |
| 批 6-1 / Q25 | 并发契约：单用户多会话并行，任务级状态实例绑定 `bound_conversation_id`；两会话同改一状态属用户自担，后写生效、系统不自动合并 | 宪法 Rule 3 |
| 批 12 | planner 分诊 / 收权退场 | 耦合行 R27 |
| 批次 D | 记忆层有意退役、当前阶段不重建（有意空缺，非债务） | `docs/冻结与暂缓清单.md` #1 |
| 批次 E | `web/provider_config` 薄壳清偿，消费方全部直连 `core/provider_config.py` | 耦合行 R10 / R13 |
| 层 9 | 轮末兜底引导卡（`round_end_policies` 的状态派生建议）≠ 暂停卡；引导卡仅承载客观状态选项 | 宪法 Rule 2 |
| 层 10 | FC 工具 description 是模型可见的唯一工具语义面 | 耦合行 R11 |
| P2d | 结构性测试减负：兼容壳文本棘轮下沉至防复活门禁 | `scripts/check_legacy_orchestration.py` |
| P2e | 协议单轨收敛：文本协议退役，唯一协议 = `system_fc.md` | 宪法 Rule 6 |
| 4-3 / 4-4 | ADR-0001 双轨「冻结」/「删除」两阶段编号 | 宪法 Rule 2 |
| F-1 / F-2 | 引导卡与暂停卡边界定义单家在宪法；提示词双源合并快照锁 | 宪法 Rule 2；`prompts/` |
| S01 / S02 / S04 / S14 | 脚手架台账条目（双轨护栏 / 退化信号探测 / 概率路由 / 兼容壳），随 ADR-0001、ADR-0002 同批下账 | 台账已根除（本文件 §二 F2） |
| 三通道分离 B / C | 超长 pause message 原文走正文通道；点选回携 value 走结构化通道 | `core/turn_executor.py`、`web/chat_opening.py` |
| R-1 | 回滚 / 分叉统一口径 = 能力已存在 + 并排对比 UI 冻结 + 不得重复实现 / 不得再报「缺分叉回退入口」 | `docs/冻结与暂缓清单.md` #2 |
| R-2 | `css_size` 门禁退役（镜像基线反模式） | 本文件 §二 2026-09-03 条；`docs/冻结与暂缓清单.md` #14（防重加） |
| R-3 | `scan_skills` 退役正文句式扫描、只留结构诊断 | `scripts/scan_skills.py` |
| R-4 | A3 硬编码 prose 完整性闸 **加** | 本文件 §二 2026-09-03 条；GATES `prompt_literals` |
| R-5 | A4（`ref_integrity` 扩面）**不加**，已知死指针维持现状 | `docs/冻结与暂缓清单.md` #12 |
| R-6 | CHANGELOG 物理分卷（2026-09-01 及更早迁 `docs/history/`） | 本文件 §二 2026-09-04 条 + §五 索引 |
| R-7 | 交接文档不长期留存、不携带规则正文；收尾后删除（内容先迁各唯一家） | 本表（20260902 文档已删；20260903 文档同口径） |
| R-8 | `layer_imports` 闸方向校正（三规则数据驱动）+ 跨切面原语下沉 `utils/` | `scripts/check_layer_imports.py`、`src/video_agent/utils/` |
| R-9 | Python 工具链选 a：`pyproject` + ruff/black，**不接门禁** | `pyproject.toml` |
| R-10 | 不做并排对比 UI | `docs/冻结与暂缓清单.md` #2 |
| R-11 | 失败差异图 / axe 报告不保存，4 张 win32 截图基线保留 | `tests/e2e/` |
| R-12 | 阶段 6 评测管线**不做**（含降级诊断脚本） | `docs/冻结与暂缓清单.md` #13 |
| R-13 | interaction 全域 reducer（解释 A）：6 处直写归零、语义逐字等价 | `src/video_agent/core/` 交互归约面 |
| R-14 | 清理备份分支 / worktree（34 个无独有提交 backup 分支已删） | IDE 缓存 worktree 已于 2026-09-20 全部回收（`git worktree list` 只剩主工作树）；原 D-13 已清偿删除，见本文件 §二 2026-09-20 条 |

> 注：右列原「耦合行 RNN」落点随耦合台账根除（本文件 §二 F1）失效，现行语义以左列结论指向的宪法条款 / 模块为准；编号本身仅在本表留痕。
>
> 注：R-1~R-14 为 2026-09-03 全面深度审核的用户裁决编号（原载于当次交接文档，该文档按 R-7 删除前编号已迁此表）。

---

## 四、已整卷归档的原文件（git tag）

| 原文件 / 原卷 | git tag | 活条款摘要落点 |
|---|---|---|
| `docs/adr/0001-0007` | `adr-archive-20260901` | 本文件 §一 |
| 指令治理层（GOVERNANCE，原宪法第十三章） | `governance-archive-20260901` | `docs/GOVERNANCE.md` |
| 脚手架折旧规程 | `scaffold-deprecation-archive-20260901` | `scripts/archive/README.md`（归档件到期策略）+ 本文件 §二 F2 |
| 长期路线图（含冻结 / 暂缓裁决原卷） | `roadmap-archive-20260901` | `docs/冻结与暂缓清单.md` |
| 历史审计文书 | `audit-history-archive-20260826` | 本文件 §二 + `docs/history/2026-08.md` |
| 治理文档 R0 批原卷 | `gov-docs-archive-batchR0-20260901` | `AGENTS.md` |

`scripts/archive/` 归档件到期策略唯一家 = `scripts/archive/README.md`。

---

## 五、历史留痕物理分卷索引（`docs/history/`）

较早的批次 / 裁决 / 事故注记已**物理分卷**（任务17 / R-6）：verbatim 搬移、不改写历史正文；
本文件 §二 只保留近期活跃留痕（现行闸机形态与本轮裁决所自出）。

| 分卷文件 | 覆盖条目 | 内容 |
|---|---|---|
| `docs/history/2026-09-01.md` | 2026-09-01 | Q2 / Q10 / Q27 裁决、D-01 层级例外清偿（core→web 端口倒置）、批 3.3、宪法 §5-6 条款来源 |
| `docs/history/2026-08.md` | 2026-08-12 ~ 2026-08-31 | C1a / C1b / B1 / D-08、批 4（ADR-0007）、交互确认改革批 A（ADR-0006）、P2-6（ADR-0005）、审核整改批 4（ADR-0004）、宪法 v6（ADR-0003）、audit-0819 系列（ADR-0001 / 0002）、0818 架构板正批（B0-B5）、2026-08-12 事故（宪法 §5 血泪条款与验收口径依据、体验基线） |

- **分界点**：§二 保留 **2026-09-02 起**——「治理闸机减负」（B0-B5+D）是现行闸机形态（GATES→SUITES→RATCHETS 三阶段、覆盖率固定容差地板、6 核心闸保留）的起点，其后各批（裁决①②③④ / 批次 E3·H·F / 会话中断清偿 R1-R3 / 三维审查修复批 / R-2·R-4 / 阶段2治理文档瘦身）相互引用密集，且被本文件 §一 / §三 / §四、`AGENTS.md` §七、`docs/未清偿债务清单.md` 段级引用。
- **迁出判据**：条目所属裁决时代已封闭——无活跃段级 inbound 指针、其编号已由 §一（ADR）/ §三（任务与内部编号）对照表承载。后续新分卷按同判据在本表追加行。
- **不改写原则**：分卷正文中提及的已改名 / 已删除文件（如 `prompts/planner/system_fc.md`）保持当时原貌，现行落点查 §三 对照表与宪法。
