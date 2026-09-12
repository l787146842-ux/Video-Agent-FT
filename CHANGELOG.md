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
| R-14 | 清理备份分支 / worktree（34 个无独有提交 backup 分支已删） | `docs/未清偿债务清单.md` D-13（IDE 缓存 worktree 残留） |

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
