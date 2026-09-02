# CHANGELOG — 裁决 / 批次 / 事故历史留痕（唯一家）

> 本文件是「批次号 / 裁决编号 / 事故注记 / 已退役机制」**历史留痕的唯一登记处**（P1 单一事实源）。
> 规则正文（`ARCHITECTURE_RULES.md`、`AGENTS.md`）与代码注释只写**现行规则与结论**，不内嵌考古编号；
> 需要出处时查本文件，整卷原文查 §四 对应 git tag。
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
| ADR-0007 | 2026-08-29 | Skill = 指令性制作手册（用户显式裁决，不可再议）：只读属性废除、压制性包壳退役、manifest 无权覆盖平台硬边界 | 宪法 §2.2、§2.8；`AGENTS.md` §八 G1 |

取代关系为双边注记（ADR-0002↔0003、ADR-0003↔0004、ADR-0004↔0006），原文见 git tag；
`scripts/check_doc_pointers.py` 的 adr-bilateral 检查项随 `docs/adr/` 清空而无对象（保留不删，属只减不增闸机的待折旧项）。

---

## 二、宪法正文迁出的批次 / 裁决 / 事故注记

以下条目原内嵌于 `ARCHITECTURE_RULES.md` 规则正文（地质层）。每条保留原编号、裁决日期与结论；
规则的**现行语义**仍在宪法正文，本处只留历史细节。

### 2026-09-03 · 用户审定「元治理台账根除」裁决（批次 F）
- **背景**：比对业界 8 家主流 agent（Claude Code / Codex / OpenHands / Flova 等）后确认，「闸机棘轮 / 冻结基线 / 脚手架折旧 / 耦合台账 / 退役条件」一类元治理机制**全部没有人做**；2026-09-02「治理闸机减负」只砍了仪式层、保留了台账本体，用户据此裁定**连台账本体一起根除**，不留尾巴。
- **裁决**：
  1. 耦合台账 `core/coupling_registry.py` + 遍历测试 `tests/unit/test_coupling_registry.py` **物理删除**；
  2. 脚手架台账 `core/scaffold_registry.py` + 其测试**物理删除**；
  3. `scripts/acceptance.py` GATES 与各闸机脚本头部的「退役条件」声明义务**整体废除**。
- **保留边界**：6 核心闸（`tool_risk` / `gen_confirm` / `prompt_write` 运行时安全闸 + `layer_imports` / `contract` / `legacy_orchestration` 架构闸）+ `category_keys` + `ref_integrity` 死指针检查保留——业界均有等价物（权限系统 / approval / 三级风险 / linter 架构约束），且实测有真实拦截。
- **批次落地**（每批 `acceptance.py --quick` 退出码 0 后独立 commit）：
  - **F1** 耦合台账根除：删 `core/coupling_registry.py` + `tests/unit/test_coupling_registry.py`；宪法 §2 P2 / §十 / §十一 文件地图 / §十二 违规清单四条引用同批删；AGENTS §一.4 同步；代码注释 6 处去指针（stage_probes / planner_triage / gate_registry / chat_service / state/manager / test_shell_payoff）；`docs/未清偿债务清单.md` §三 改为独立人读审查备注。
- **连带影响**：耦合表 26 行的强制项随之消失，其中 R18 / R22 / R26 / R28 等机械约束本已由各自门禁与回归测试独立覆盖（`test_gen_confirm_gate` / acceptance GATES / `gen_api_types` / `check_layer_imports`），无覆盖回退；`ref_integrity` 闸所检的宪法锚点与文件地图在同批同步更新，未留死指针。

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
- **连带影响**：GATE_RULES 由 5→3 条；acceptance GATES 由 13→10 项（`contract` / `semantic_colors` / `func_imports` / `category_keys` / `legacy_orchestration` / `layer_imports` / `ref_integrity` / `cov_ratchet` / `fe_cov_ratchet` / `css_size`）；覆盖率不再逐批镜像上调，改为低于固定地板才 FAIL。本裁决为「只减不增」棘轮化治理的一次性反向减负，此后闸机增减由用户裁决。

### 2026-09-02 · 裁决③——覆盖率棘轮改显式上调
- **背景**：全量验收时 cov 闸 PASS 即半自动改写 `scripts/cov_baseline.txt`；叠加「门禁先于套件、读上一轮覆盖率产物」的顺序局限，每次全量都可能静默改基线——本会话发生两次静默改写，均手动还原。
- **裁决**：改为仅显式传 `--update-baseline` 才上调基线（fe3729c；后端 `scripts/check_cov_ratchet.py` 与前端 `scripts/check_fe_cov_ratchet.py` 同构）；日常门禁实测高于基线只打印 NOTE、不写文件。
- **连带影响**：棘轮下限不再自动上升，基线上调改为批末显式登记动作（操作口径见 `AGENTS.md` §二 纪律）。

### 2026-09-02 · 裁决②——消息排队档2 取消
- **核查结论**：档2 主体早已实现——步间插话 / 轮边界注入（R3）、重试上下文还原、排队区可视化、队列消息可编辑与删除、失败保留、侧边打开；「立即发送 / 打断按钮」与「当前步骤不打断」的既定设计相悖。
- **裁决**：取消不做（不重复造轮子）；仅剩队列计数徽标、拖拽排序两件纯装饰记入待办，无事故依据不立项。

### 2026-09-02 · 裁决④——响应契约 phase2 门禁暂缓
- **结论**：path×method 存在性门禁（从 OpenAPI 派生合法集合、静态对拍前端 `api/` 调用）暂缓、记入待办、未立项；属新增门禁，须事故依据 + 退役条件 + 书面裁决三件套（宪法 §2.3 闸机冻结基线只减不增）。

### 2026-09-02 · 裁决①轻量版——暂停槽表述对齐
- **背景**：宪法正文「重复暂停拒收留痕」与代码实际行为（旧卡作废 + trace + 发新卡 + 继续等确认，不拒收）矛盾，属 P1 单一事实源冲突。
- **裁决**：以表述对齐消除矛盾，代码行为不改（现状已正确）；宪法 / gate 文案 / fallback / 注释 / 测试 docstring 统一为「旧卡作废 + trace 留痕（pause_slot_collision）+ 发行新卡 + 继续等待人工确认，不拒收、绝不未经确认自动继续」。
- **暂停队列暂缓**：按旧卡所属 run 存活性分流「入队 vs 作废」暂缓，须待「同步双发卡丢真问题」的真实事故证据再升级（G2）。

### 2026-09-02 · 治理文档清理批
- **宪法去地质层**：正文内嵌的批次 / 裁决 / 事故注记全量迁至本文件，正文只留现行规则。
- **ADR 僵尸引用清理**：`docs/adr/` 已清空，全仓 78 处「ADR-000X」出处标注（76 行 / 39 文件）
  改为语义术语 + 归档指针；指针落点为 §一 对照表 + git tag `adr-archive-20260901`，消除指向空目录的幽灵引用。
  代码层按「每文件首个命中处放一次指针、同文件其余只保留语义术语」收敛，避免长指针成为新的考古噪声。
- **宪法 §十一 注记迁出**：`core/fc_feedback.py`（C3 落点）、`core/round_end_policies.py`（层 9 唯一落点）、
  `core/prompt_gates.py`（D-08 清偿）、`core/action_executor.py`（Q2 裁决）、`web/port_wiring.py`（D-01 / 任务#13 F-4）、
  `skill_runtime/frontmatter.py`（任务#5）、`tests/fixtures/`（C1a / C1b 夹具退役）等条目的编号注记迁出，
  文件地图只留现行职责描述。

### 2026-09-01
- **Q2 裁决**：文本轨动作分派与「草稿 / 生成 / 媒体」三域模块退役删除，动作通道唯一 = FC 工具直连
  `state/storyboard_ops.py`；驱动符号入防复活清单。
- **Q10 裁决**：版本锁核验 / 记账整体退役（保留 `.history` 本地备份能力）。
- **Q27 裁决**：治理文档脚本 / 夹具指针防腐 + 宪法 §2.3 闸机基线数字防腐，两项并入 ref_integrity 门禁。
- **D-01（层级例外清偿）**：动作执行器下沉 `core/action_executor.py`；对 web 生成管线 / 供应商配置的依赖
  倒置为 `core/ports.py` 端口 + `web/port_wiring.py` 装配点注入；core→web 任何 import 一律禁止
  （机械化门禁 `scripts/check_layer_imports.py`）。
- **批 3.3**：core / tools 需消费 web 层能力（媒体注入解析 / 降级链 / 文档与生成任务面）时，
  一律改走 core/ports 端口或 storage / core 公开 API，新门禁零豁免。
- **宪法 §5-6 条款来源**：宪法不复述具体分支名（v3 曾复述，随分支合并过期漂移）。

### 2026-08-31
- **C1a 裁决**：黄金语料闸机校准与提示词快照测试退役；frontmatter `gates` 键全链路删除
  （`parse_gate_rules` 退役）；夹具 `gate_corpus` 删除。
  → 宪法「评测驱动」「快照防漂移」条现行语义：平台固定地板行为由客观回归测试钉死，
    提示词外置 / 迁移语义由外置单一事实源 + 回归测试保障，提示词快照测试不作为强制项。
- **C1b 裁决**：`pause_points` 机械暂停退役——暂停由模型读 planner 散文自主经 `workflow_pause` 执行；
  `parse_pause_rules` 仅存诊断口径（skill_docs lint / scan_skills 报告）；夹具 `skill_pause_golden` 删除。
- **B1 裁决**：选中 Skill 预算式头部注入退役，默认注入收窄为 `<planner>` 段全文 + 章节目录，
  其余章节正文经 read_skill 按需取读。
- **D-08 清偿**：`core/prompt_gates.py` 尾部规格 / 剧本闸家族（`gates_spec` / `gates_script`）退役删除，
  两实现体模块同批删除；prompt_gates 仅存承重壳 re-export `core/gate_registry.py`（注册表唯一家）。

### 2026-08-29
- **用户裁决（批 4，ADR-0007）**：Skill = 指令性制作手册；G1「只读属性」废除——系统与 Skill 冲突时
  修平台层，禁止降低 Skill 要求迁就系统缺陷；压制性包壳退役，仅外部 / 社区来源附中性来源标记。
- **用户裁决**：撤除 Skill 正文中性化层（不检查 / 不消音 skill 正文句式），耦合行 R29 同批退役删除。
- **用户裁决（冻结项）**：不做 skill_search 模型自行检索；不做社区 + 排序 / 搜索前端
  （活表述见 `AGENTS.md` §六）。

### 2026-08-27
- **交互确认彻底改革批 A（ADR-0006）**：问即停 / 三态消费 / 事务性写入落地；
  旧「执行后拒收」形态退役，重复暂停改为告警 + trace 留痕并照常发行（新卡覆盖旧卡解除死锁）。
- **P2-6 批次（ADR-0005）**：子代理隔离草案产出，未接受、零编码。

### 2026-08-21
- **审核整改批 4（ADR-0004）**：控制流主体回归；runtime 机械直跑 / 审批直跑驱动符号退役，
  防复活入 `scripts/check_legacy_orchestration.py`。

### 2026-08-20
- **宪法 v6（ADR-0003）**：Workflow Runtime 单一控制实体登记，耦合行
  `R_workflow_runtime_subject_return` 同批登记。

### 2026-08-19
- **audit-0819 / audit-0819b（ADR-0001）**：双轨制冻结（4-3）→ 删除（4-4）同日完成；
  协议单轨 = `prompts/planner/system_fc.md`，文本协议 `system.md` 退役删除；
  `agent.executing` 文案随 `executing_actions` 事件退役删除；暂停确认不再合成 studio-actions 块。
- **audit-0819e（ADR-0002）**：控制流统一，废除概率路由（`_route_orchestrator` 按语料决定走向的接缝）。
- **audit-0819-leak**：假停止 / 泄漏形态演化取证，后续随单轨化收敛。
- **0B 度量**：存量持久化历史中非 FC 通道占比 0%（样本 11 条），构成 ADR-0001 触发判据之一。

### 2026-08-18
- **0818 架构板正批（B0-B5）**：状态驱动编排重构机械退役老机制（FlowGateSet 闸机链 /
  skill_pipeline_plan 调度工具 / 盲重试 / 总结注入链 / 正则通道）；B5 设立防复活门禁
  `scripts/check_legacy_orchestration.py`。

### 2026-08-12
- **事故（宪法 §5 血泪条款依据）**：因「未提交改动 + 救火回滚」丢失整批工作 →
  开工先备份、禁止裸 `git restore .` / `git checkout -- .`、备份切回必须核对未跟踪文件、
  重启前按 PID 杀净旧进程。
- **事故（验收口径依据）**：Windows 终端 GBK 乱码曾把「契约不一致」伪装成「一致」、
  把门禁失败伪装成通过 → 验收只认进程退出码，人眼读终端输出不算验收。
- **体验基线**：2026-08-12 02:00 前的系统状态定为可接受基准线（宪法 §3.1），
  任何变更不得导致基线功能 / 交互 / 视觉退化。

---

## 三、任务编号 / 内部治理编号对照

宪法正文与代码注释曾内嵌的内部编号，现行规则落点见右列；编号本身只在本表留痕。

| 编号 | 结论（一句话） | 现行规则落点 |
|---|---|---|
| 任务#5 | Skill 声明唯一源 = 文档头部 YAML frontmatter（`name` / `description` 必填），外置 JSON sidecar 退役 | 宪法 §2.8 |
| 任务#6 C-1 | 剧本定稿入文档的编排约定单家在 `prompts/planner/skill_discipline.md` | 提示词外置资产 |
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
| 批次 D | 记忆层有意退役、当前阶段不重建（有意空缺，非债务） | `AGENTS.md` §六 |
| 批次 E | `web/provider_config` 薄壳清偿，消费方全部直连 `core/provider_config.py` | 耦合行 R10 / R13 |
| 层 9 | 轮末兜底引导卡（`round_end_policies` 的状态派生建议）≠ 暂停卡；引导卡仅承载客观状态选项 | 宪法 Rule 2 |
| 层 10 | FC 工具 description 是模型可见的唯一工具语义面 | 耦合行 R11 |
| P2d | 结构性测试减负：兼容壳文本棘轮下沉至防复活门禁 | `scripts/check_legacy_orchestration.py` |
| P2e | 协议单轨收敛：文本协议退役，唯一协议 = `system_fc.md` | 宪法 Rule 6 |
| 4-3 / 4-4 | ADR-0001 双轨「冻结」/「删除」两阶段编号 | 宪法 Rule 2 |
| F-1 / F-2 | 引导卡与暂停卡边界定义单家在宪法；提示词双源合并快照锁 | 宪法 Rule 2；`prompts/` |
| S01 / S02 / S04 / S14 | 脚手架台账条目（双轨护栏 / 退化信号探测 / 概率路由 / 兼容壳），随 ADR-0001、ADR-0002 同批下账 | `core/scaffold_registry.py` |
| 三通道分离 B / C | 超长 pause message 原文走正文通道；点选回携 value 走结构化通道 | `core/turn_executor.py`、`web/chat_opening.py` |

---

## 四、已整卷归档的原文件（git tag）

| 原文件 / 原卷 | git tag | 活条款摘要落点 |
|---|---|---|
| `docs/adr/0001-0007` | `adr-archive-20260901` | 本文件 §一 |
| 指令治理层（GOVERNANCE，原宪法第十三章） | `governance-archive-20260901` | `AGENTS.md` §八 |
| 脚手架折旧规程 | `scaffold-deprecation-archive-20260901` | `AGENTS.md` §七 |
| 长期路线图（含冻结 / 暂缓裁决原卷） | `roadmap-archive-20260901` | `AGENTS.md` §六 |
| 历史审计文书 | `audit-history-archive-20260826` | 本文件 §二 |
| 治理文档 R0 批原卷 | `gov-docs-archive-batchR0-20260901` | `AGENTS.md` |

`scripts/archive/` 归档件到期策略唯一家为 `scripts/archive/README.md`（满两季度即删）。
