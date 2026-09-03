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

### 2026-09-04 · 收尾后用户裁决批（断点续跑立项 + 三项登记）
- **背景**：对两次会话（全面深度审核 + 裁决落地）做执行完整性核查后，报告 3 条「悬空项」——审计提出但既未执行也未登记也未裁决的发现，交用户逐条拍板。
- **裁决**：
  - **断点续跑：做**——重启后生成任务从检查点继续（详见本批实施提交）；原审计 D-23 后半（优雅关停前半已由后端批清偿）。
  - **paths-ignore 不加 → 登记冻结清单 #15**（系审计「CI 四项配置」唯一不采纳项，防重复提案）。
  - **登记债务 D-15**（全局异常兜底 + 安全响应头，公网部署前必修）与 **D-16**（数据层 schema_version / migration，随下次存储格式改动一并做）。
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
- **背景**：比对业界 8 家主流 agent（Claude Code / Codex / OpenHands / Flova 等）后确认，「闸机棘轮 / 冻结基线 / 脚手架折旧 / 耦合台账 / 退役条件」一类元治理机制**全部没有人做**；2026-09-02「治理闸机减负」只砍了仪式层、保留了台账本体，用户据此裁定**连台账本体一起根除**，不留尾巴。
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

### 2026-09-02 · 全面深度审核收尾批（对标 flova/DeepSeek/Codex/Claude；8 commit）
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
