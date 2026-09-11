# 架构宪法 — AI 协作开发强制约束（v9 · 2026-09-01）

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder / CodeBuddy 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
> 现行定版要点：Skill = **指令性制作手册**（改动裁决关 G1 见 `docs/GOVERNANCE.md` §四）；
> 控制流 = 模型永远唯一行动主体 + Workflow Runtime 账本/裁判数据层；指令治理层（原第十三章/GOVERNANCE）
> 已退役并入，治理条款唯一家见 `docs/GOVERNANCE.md`（原卷见 git tag `governance-archive-20260901`）。
> 四条红线不变：§2.4 Context≠Consent、platform 闸机 manifest 无权关闭、
> §2.7 确认闸、动作单轨 FC + guard_pipeline 唯一判定（scripts 键只静态校验）。
>
> **本文只写现行规则**：批次号 / 裁决编号 / 事故注记 / 已退役机制的历史留痕唯一家 = `CHANGELOG.md`，
> 正文与文件地图不内嵌考古编号（需要出处时查该文件，较早留痕已分卷至 `docs/history/`、逐卷索引见其 §五，整卷原文查其 §四 git tag）。
>
> **治理总纲：按业界最高标准执行，禁止走捷径。** 具体含义：
> 1. **策略即数据（Policy-as-Data）**：所有闸机/安全规则以注册表数据表达，带稳定 `rule_id`、层级归属、外置文案；禁止散落硬编码。
> 2. **单一事实源（Single Source of Truth）**：状态写入归 StateManager、循环归 agent_loop、入口归 Planner、提示词归 `prompts/`、前端类型归 `gen_api_types` 生成物。
> 3. **评测驱动（Evaluation-Driven）**：平台固定地板行为由客观回归测试钉死；提示词快照测试不作为强制项。
> 4. **deny-overrides 分层合并**：平台硬边界永远优先，Skill 配置只能加强或持平，不能削弱。
> 5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批未提交改动（血泪条款见 §5）。
> 6. **验收 = 一键脚本 + 用户目测**：`python scripts/acceptance.py` 全 PASS（三阶段清单以脚本内 `GATES`/`SUITES`/`RATCHETS` 表为准，不写死数量，**只认进程退出码**，人眼读终端输出不算验收；`--with-eval` 补评测管线）；UI 变更必须构建后由**用户目测反馈**确认（不派浏览器子代理截图代目测，可做轻量定点代码级验证），缺一项不算完成。
> 7. **指令治理**：治理条款（三原则 P1/P2/P3、修复决策树、捷径禁令、方案四关 G1-G4）唯一家 = `docs/GOVERNANCE.md`；修改前必须按其修复决策树定位归属层，禁止在事故现场就近补条款。

---

## 一、核心架构铁律

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` / `handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: Workflow Runtime 单一控制实体 + 动作通道单轨（FC）
- `core/agent_loop.py::run_agent_loop()` 是节点内模型循环的**唯一实现**；**不设步数上限**（跑飞兜底 = 输出 token 截断 `settings.llm_max_tokens` + 模型自决；`MAX_STEPS`/`settings.max_steps` 已退役）
- **动作通道唯一 = FC 工具调用**（`core/fc_tool_runner.py`）；禁止恢复自由文本动作解析与非 FC 动作通道
- **确认单轨化**：暂停确认唯一经 `workflow_pause` FC 工具产生，经 llm_call 第 5 元组结构化上抛；`agent_loop` 纯文本轮仅收尾（轮末策略照常承重）
- **无执行器子代理**：管线阶段由通用主路径直走平台工具（`prompt_builder` 只注入 L1 目录与轻量状态提示，Skill 正文经 read_skill 按需读取）；防虚报收敛到 `fc_tool_runner` 关键步骤探针；退役符号登记 `check_legacy_orchestration` 防复活，禁止恢复
- **闸机单轨一致**：所有动作判定统一经 `core/guard_pipeline.py`（见 §2.0），禁止旁路
- **控制流主体回归**（决策史见 git tag `adr-archive-20260901`）：模型永远唯一行动主体——每轮做什么由模型接到用户消息后发起工具调用（带附件首条消息也由模型接手，系统不静默自动分析）；`core/workflow_runtime.py` 为**账本 + 裁判数据层**（Skill 激活**不再编译节点 DAG**——16 节点 `WorkflowDefinition` 契约已退役，`compile_definition` 恒 None；持久化 `WorkflowRun`，**仅 runtime reducer 可改**，StateManager 仍唯一写入点 Rule3；完成度只认客观探针 stage_done，按平铺节点清单重算，只服务审计与机械停闸判据，**平台不判流程完成**），不发起任何行动；机械直跑/审批直跑一律禁止（驱动符号登记 `check_legacy_orchestration` 防复活）。「不暂停连跑」= 自主性档位（用户指令/开关授予模型豁免非平台硬暂停点；平台硬闸任何档位必停，Context ≠ Consent，授权留痕）。**原子轮提交**：一轮只提交一个 `TurnResult`（turn_id 归组）；正文只承载成果；暂停卡只承载一句问句 + 系统派生选项（暂停卡唯一发行主体 = 模型 `workflow_pause`，单一活跃暂停槽位；重复暂停 = 旧卡作废 + trace 留痕（pause_slot_collision）+ 发行新卡 + 继续等待人工确认，不拒收（作废 = 失去活跃暂停槽位登记、不再作为待确认项被消费；展示层作废标记已实现（旧卡挂作废态 + 点击失效反馈））；轮末兜底引导卡（round_end_policies 的状态派生建议）≠ 暂停卡；暂停卡唯一发行主体仍为模型 workflow_pause，引导卡仅承载客观状态选项）；文档卡源自同轮 artifact；**正常完成禁空正文**；`ArtifactCommitted` 先于 `StageSucceeded`；SSE/历史/时间线/卡片四投影同源派生，瞬态通道不得作为唯一可见性；一切机械动作进转录一等条目。控制流决策全记 `tracer.record_control_flow` + `[ControlFlow]` 日志，永不无据可查
- **动作语义唯一实现**：故事板增删改查领域逻辑统一在 `state/storyboard_ops.py`，执行路径必须委托，禁止各自重写查找/字段白名单/类别映射
- **层级例外**：动作执行器下沉 `core/action_executor.py`，对 web 生成管线/供应商配置的依赖倒置为 `core/ports.py` 端口、web 装配点注入（`web/port_wiring.py`）；core→web 任何 import（含延迟/TYPE_CHECKING）一律禁止

### Rule 3: StateManager 唯一写入点
- `state/manager.py::StateManager` 是状态的**唯一写入点**；复杂嵌套操作允许直接操作 `state_dict`，但完成后**必须 `save()`**
- **禁止**在 routes / tools / adapters 中直接写 JSON 文件；**禁止**绕过单例自建状态实例（配置类文件除外：快照 / 运行时设置 / 供应商配置等不走状态管理的配置类文件，不在本禁令范围内；后台 Agent 任务的任务级实例经 `create_task_bound` 受控创建，不属绕过）
- **并发契约**：单用户多会话并行——同项目多对话可同时运行 Agent 任务、共享项目状态；任务经任务级状态实例绑定提交时的对话（`bound_conversation_id`，聊天写入定向单点 `conversation_ops.target_chat_messages`）；两个会话同时修改同一状态属用户自担责任，后写生效，系统不做自动合并

### Rule 4: 外部调用必须走 Adapter
- LLM/图/视频外部调用必须继承 `adapters/base_chat.py::BaseChatAdapter` 或 `adapters/base.py::Base{Image,Video}Adapter`
- **禁止**在 route / tool / planner 中直接 `httpx.post()` / `requests.get()`；错误抛 `AdapterError`，不得静默吞掉

### Rule 5: Tool 统一注册 + 消歧原则
- 新增业务 Tool 继承 `tools/base.py::BaseTool`，实现 `get_input_schema()`（Pydantic）+ `aexecute()`，经 `ToolManager.register()` 注册
- 业务 Tool 必须声明 `risk = low|medium|high`（按可逆性/影响面，见 §2.7）；未声明视为 high（deny-by-default）
- **工具消歧原则**：同名近义工具优先通过重写 description 互斥消歧；**改名/合并属高风险重构，必须单独评估立项**

### Rule 6: 指令治理（Prompt 外置 + 单一事实源 + 快照防漂移）
- 所有 system prompt / 闸机文案 / 回喂模板存放在 `prompts/`（`planner/`、`gates/`、`shared/` 分区），经 `utils/prompts.py::load_prompt()` / `load_prompt_section()` 加载
- **禁止**在代码中硬编码超过 3 行的 prompt 字符串；代码只留组装逻辑
- **快照防漂移**：提示词外置/迁移语义由外置单一事实源 + 回归测试保障；提示词快照测试不作为强制项
- **协议单轨**：平台协议唯一 = `prompts/planner/protocol.md`（文本动作协议已退役删除、禁止复活，决策史见 git tag `adr-archive-20260901`）；协议正文**单文件内联**，prompts/ 无 `{{include}}` 拼装机制；`prompts/shared/` 存条件注入模板，由 `load_prompt_section()` 按注入条件成段加载，**禁止**把条件模板复制进协议正文
- 纪律条款外置为独立 md（如 `planner/skill_runtime.md`、`planner/adjust.md`），不得内联代码

### Rule 7: 画布边界 — 任何时候都禁止修改（fork/改源码均禁止）
- 画布（infinite-canvas）是**独立迭代项目**，代码不在本仓库，**任何时候禁止修改或 fork 其任何文件**
- 仅依赖三个公开面：① Canvas Agent HTTP 协议（`/api/tools` 工具调用 + `/health`，封装于 `adapters/infinite_canvas_backend.py`）；② hash 引导（iframe 加载时注入 `#agentUrl`/`#agentToken`）；③（可选）画布插件 SDK。除此之外一律视为不可实现，确需新能力只能向画布项目提需求（见 `docs/对画布的需求清单.md`）
- **已知集成边界**：画布内生成的图存于画布浏览器端（本地存储），服务端无法回读原图，只能通过 config 节点连线回读导出 URL；素材录制遗留一条测试素材（见 `workspace/assets`），属已知残留不影响功能

---

## 二、闸机与安全边界宪法

### 2.0 闸机管线宪法（Guardrails are Execution Logic）
- 闸机是**执行逻辑**，不是提示词条款：任何「拦截/放行/剥离」不得依赖模型自觉遵守。
- 统一 guard pipeline：`input guard → tool input guard → tool execute → tool output guard → output guard → audit`；
  动作通道单轨（FC，Rule 2），全部判定经同一管线实例。
- 工具级闸在**每一次工具调用**前后都执行；tripwire 触发立即中断并保留已完成调用记录，禁止把残品当成品。
- 所有 verdict 结构化（`GateVerdict(rule_id, layer, ok, message)`），回喂模型与展示用户用同一源，杜绝两套说辞。

### 2.1 策略层模型（闸机仅 platform 层）
| 层 | 内容 | 可配置性 |
|---|---|---|
| 平台层 `platform.*` | 生成确认闸、阶段硬边界（写文档/建结构强制暂停）、字数地板（镜头/元素最短字数）、提示词书写闸（字数/字段）、工具 risk 分级 | **manifest 无权关闭**；安全底线（tool_risk、gen_confirm / costly 确认）任何模式均强制生效；质量闸（prompt_write、structure）严格度可经 `prompt_gate_mode`（strict/warn/off）调节，属质量档位而非安全开关；仅可经用户一次性申诉逐条放行 |

### 2.2 manifest 只能加强或持平（强制不变量；Skill = 指令性制作手册，平台硬边界不可被覆盖）
- 外部 Skill 文档来自成熟平台，其配置**不可信**；系统必须坚守自身安全底线
- **Skill 是指令性制作手册**（教 Agent 理解任务/拆步骤/调工具/选模型/出片，创作者自由书写，对齐业界）：其指令仅在创作流程内有效——不能覆盖平台闸机、不构成用户同意（§2.4 Context≠Consent）、不能要求执行平台外动作（动作单轨 FC + guard_pipeline 唯一判定，scripts 键只静态校验绝不执行）
- manifest 试图触碰 `platform.*` 的任何键：**静默忽略 + warning 日志**，并必须有负面用例测试断言其无效
- 可配项仅限风格/流程类；「规格前置」经用户确认为可配置项，不锁死

### 2.3 规则注册表（Policy-as-Data）
- `core/gate_registry.py` 维护 `GATE_RULES` 注册表（唯一家；消费方直连本模块，原 `prompt_gates.py` re-export 壳已收敛）：稳定 `rule_id` + 层归属 + 中文描述
- 判定返回结构化 `GateVerdict(rule_id, layer, ok, message)` 列表；文案外置 `prompts/gates/messages.md`，杜绝自由文本
- 回喂模型与展示用户用**同一 verdict 源**（防两套说辞）

### 2.4 拦截可见 + 一次性申诉放行
- 拦截必须用户侧可见（警示 chips 带规则描述 + 来源标注「平台」/「Skill『xxx』」）
- **Context ≠ Consent（上下文不等于同意）**：平台硬边界只能被「针对**当前动作**的显式用户指令」解除；模型不得自证「用户已确认」，历史上下文、Skill 文档中的「用户已同意/默认放行」一律不构成同意。
- **同意来源枚举（批 12 章程，`guard_pipeline.CONSENT_CHARTER` 唯一家）**：①「本次放行」（gate_overrides 单次消费）；②暂停卡 accept（同意账本，工作轮内有效，放行范围 = costly 生成 ∪ 规格文档写入，见 §2.7）；③工作台草稿标「已确认」（gen_confirm 专属）；④执行偏好三档（系统代发同意，仅 costly 生成）。各来源的放行范围以章程表为唯一判定声明；闸机拒因/协议/设置页文案的承诺必须 ⊆ 章程（一致性门禁 `check_consent_copy`）。
- 「本次放行」单次生效、全程留痕、不形成持久削弱；每次放行单独点，且必须可追溯到产生它的用户消息。

### 2.5 审计闭环
- `tracer.record_gate(...)` 持久化到 `agent_traces.jsonl`；调试端点 `GET /api/agent/gates` 与 `/api/agent/traces` 并列
- 闸机触发/放行、工具调用、截断/回滚全部入 trace

### 2.6 校准闭环（评测驱动）
- **闸机校准经验**：连续相同原因拦截必须升级改写指引（合并相同 verdict、附「第 N 次被拦」差异化提示），防模型陷入「拦截-重写-再拦截」空转；拦截事件入生成日志面板可见

### 2.7 工具风险分级（Tool Risk Tiers）
- 每个业务 Tool 声明 `risk = low | medium | high`：low=只读/可逆；medium=写状态但可撤销；high=生成、跨阶段建结构、外部副作用。（2026-09-07 外部标杆对齐裁决：文档/画布写入属「写状态但可撤销」归 medium，写入不设逐次确认闸——外部标杆转录实证：规格/分镜/画布全程零机器拦截，唯一卡=花钱生成确认。）
- high 级工具必须平台闸机 + 用户确认；medium 级按 Skill 配置；low 级直接执行。
- 新工具未声明风险级别视为 high（deny-by-default），不得静默放行。
- **同意范围矩阵（批 12 章程）**：暂停卡 accept 的同意按动作类声明（`CONSENT_CHARTER`）：costly 生成（image_generate/generate_video）可吃同意放行；「规格文档写入」为历史条款——document_write 已降 medium（2026-09-07），该路径自然失效，章程表保留（写入类不再入闸，fail-closed 无害）。其余 high（未注册工具等）不吃自动同意，仅「本次放行」可解除（fail-closed）。MCP costly 地板 high 不可下抬的底线不变。

### 2.8 Skill 宪法（单一包形态 + 三级渐进披露）
- Skill 上传/保存/删除 = `data/skills/<slug>/SKILL.md` 单一包形态唯一数据源（对齐 Agent Skills 开放标准，frontmatter `name`/`description` 必填）+ 自动解析文档头部 frontmatter 声明（声明唯一源，外置配置文件退役）→ 刷新注册表；下拉框数据源不变。
- **三级加载（渐进披露）**：① 开关（用户启停）→ ② 目录摘要常驻（L1 元数据目录 + 轻量状态提示）→ ③ 正文预算化注入、资源按需（read_skill 续读）。
- **注入面纪律**：官方/平台 Skill 干净注入，不加任何包壳；仅外部导入 Skill 带来源标记供用户知情。
- 管线阶段由通用主路径直走平台工具，无执行器子代理。
- 关键步骤失败**禁止绕过回喂/虚报**：`fc_tool_runner` 按客观探针（document_write 等工作台状态）覆写完成文案，模型不得假装已执行。
- 注册表是数据（policy-as-data），不得散落硬编码；外部工具接入层（MCP）为预留扩展点，不得在注册表外私设工具通道。

---

## 三、前端体验宪法

### 3.1 体验基线不退化
- **2026-08-12 02:00 前的系统状态为可接受基准线（baseline）**；任何变更不得导致基线功能/交互/视觉退化
- UI 变更必须构建后经**用户目测反馈**确认交付（禁止浏览器子代理截图代目测——动作慢、截不到目标图且浪费算力；可做轻量、定点、快速的代码级验证）；「测试全绿」不等于「UI 正确」
- **品牌、视觉与交互细节规范（飞天品牌、确认卡片样式、@面板、分组卡片等）**见 `docs/前端体验规范.md`，同样为强制约束，由前端工程按批次执行

### 3.2 前端工程
- 唯一前端为 `src/web` SolidJS SPA，构建产物 `static/dist`；启动脚本自动补构建；**禁止**复活旧 studio 页面
- 前端类型以 `scripts/gen_api_types.py` 生成物为契约，`--check` 纳入每批验收；**前端 API 边界类型以 `api.generated.ts` 为唯一来源**（豁免/精化清单登记于 `types/index.ts` 文件头；生成物豁免 eslint max-lines）；消费覆盖防回退由 `api-contract.test.ts` 桥接测试机械断言

---

## 四、运行时配置宪法

- `Settings` 为 frozen dataclass（全局不可变约定）；运行时热切换**仅限** `web/routes/runtime_settings.py` 域，经 `object.__setattr__` 定点突破并落盘 `data/runtime_settings.json`，启动时加载覆盖
- **模型 fallback 开关语义（用户定义）**：开 = 厂商联不通/出不了图视频时自动换同模型其他 API 厂商；关 = 直接按上游报错。默认开；顶栏开关热生效不重启

---

## 五、进程与版本治理宪法（血泪条款）

> 以下条款为强制铁律，源自一次真实的整批工作丢失事故（事故经过见 `docs/history/2026-08.md` 的 2026-08-12 条）：

1. **开工先备份**：任何修复/整改会话开工前，先建备份分支并立即 commit 现状；每完成一批立即 commit，**禁止攒大批未提交改动**
2. **救火先留现场**：回滚前先把现场 commit 到 archive 分支；**禁止裸 `git restore .` / `git checkout -- .`**（reflog 不留痕的销毁式操作）
3. **备份切回核对**：从含未跟踪文件的备份分支切回后，必须 `git diff --diff-filter=A -z` 核对并恢复被 git 删除的未跟踪文件
4. **端口清理**：重启服务前先按 PID 杀净旧进程（`netstat -ano | findstr :8080`），防旧代码假象
5. **验收 = acceptance.py 全 PASS**：只认进程退出码，人眼读终端输出不算验收；`--with-eval` 终验补评测管线；pre-commit 钩子强制执行
6. **分支现状**：以 git 分支实际状态与事故台账为准，宪法不复述具体分支名
7. **CLI 旧线处置**：workflows 引擎下线为已批准决策，实现体在 backup 分支；落地前新代码**禁止新增依赖**旧线

---

## 六、代码组织约束

### 路径与配置
| 需求 | 正确做法 | 禁止做法 |
|------|----------|----------|
| 引用项目目录 | `from src.video_agent.utils.paths import ASSETS_DIR` | `Path(__file__).resolve().parent...` |
| 读取可调参数 | `from src.video_agent.config import settings` | 硬编码数字如 `timeout=120` |
| 状态类别 Key | `from src.video_agent.state.models import CAT_SHOTS` | 硬编码 `"shots"` 字符串 |

### 异常处理
- 业务异常继承 `exceptions.py::VideoAgentError`；Adapter 失败 → `AdapterError`；生成管线 → `GenerationError`；状态操作 → `StateError`
- **禁止**用 `return False` / `return {"error": ...}` 代替异常

### Import / 类定义
- import 放文件顶部（标准库→第三方→项目内部）；禁止方法内 import；禁止循环导入（routes⊄tools⊄adapters）
- 禁止同名类覆盖；禁止文件末尾追加 Mock 覆盖正式实现；修改必须原地修改

### 层间依赖方向（core 不得依赖 adapters）
- **禁止 core → adapters**。core 需要「外部调用结果的数据形状」或「一个适配器长什么样」时，**契约由 core 拥有**：`core/chat_port.py` 定义 `ChatResponse` / `StreamChunk` 纯数据类与结构化端口 `ChatAdapterPort`（Protocol）；adapters 侧反向依赖该模块并 re-export（旧导入路径保持不变），抽象基类 `BaseChatAdapter` 仍定义在 `adapters/base_chat.py`（Rule 4 锚点）并结构化满足该端口
- **跨切面原语下沉 `utils/`**：被 core / tools / adapters / web 多层共用且不专属任一层的原语（取消令牌 `cancel_token`、停止标志 `stop_signal`、供应商配置加载 `provider_config_loader`、实时度量 `live_metrics`、trace 留存 `trace_retention`）一律放 `utils/`，使各层单向依赖 utils 而非互相依赖；**禁止**为此类原语在 core↔adapters 之间开洞
- 门禁 = `scripts/check_layer_imports.py`（core→adapters 违规基线已收缩为空集，新增即 FAIL；函数级 import 存量白名单见 `scripts/check_func_imports.py`）

### 状态写面分类

| 写面类型 | 持有者 / 持久化路径 | 规则 |
|----------|---------------------|------|
| 项目创作状态 | `state/manager.py` StateManager → `workspace/state.sqlite3` 项目表 | Rule 3 唯一写入点；任何创作数据变更必须经 StateManager |
| 运行时元数据（批次） | `web/video_batch.py` → `data/video_batch_tasks.json` | 允许独立持久化；**禁止反向写项目状态**（读 StateManager 快照合法） |
| 运行时元数据（任务） | `web/agent_task_manager.py` → TaskStore / `workspace/state.sqlite3` kv 表 | 允许独立持久化；**禁止反向写项目状态**（经 contextvar 绑定项目 StateManager 仅读取） |
| 配置写面（供应商 / 运行时设置 / .env） | `core/provider_config.py`（`data/api_providers.json` + `API/.env` 原子写）、`web/routes/runtime_settings.py` 与 `web/routes/config.py`（`data/runtime_settings.json`） | 属 Rule 3「配置类文件除外」豁免、不走 StateManager；热切换/落盘机制单家见 §四；**禁止写入项目创作状态**（StateManager 域） |

> 判定准则：凡「运行时调度/队列/进度」类元数据与「供应商/运行时设置/.env」类配置，
> 允许在 StateManager 之外独立持久化，但必须单向依赖——只读项目状态、禁止向项目状态写入。
> 配置写面的热切换/落盘机制单家见 §四与 Rule 3「配置类文件除外」，本表只登记写面归属、不复述机制。
> 新增状态写面或配置写面须在此表登记。

---

## 七、新增功能标准流程

| 类型 | 步骤要点 |
|---|---|
| 新增 Tool | tools/ 新建 → Input Schema(BaseModel) → 继承 BaseTool → `get_input_schema()`+`aexecute()` → `ToolManager.register()` → 单测 |
| 新增 API 路由 | `web/routes/xxx.py` → `APIRouter()` → `app.py include_router(prefix="/api")` → 内部走 StateManager/ToolManager/Planner → VideoAgentError 体系 → 集成测试 |
| 新增 Adapter | `adapters/xxx.py` → 继承对应基类 → 实现全部抽象方法 → AdapterFactory 注册 → `data/api_providers.json` 配置 → mock 单测 |
| 修改状态模型 | `state/models.py` → 新字段给 default（向后兼容）→ 新类别常量 CAT_XXX → StateManager 辅助方法 → `to_frontend_dict()` 兼容 → 全量测试 |

---

## 八、接入外部平台专项规则

- **LLM 供应商**：必须实现 `BaseChatAdapter`（`chat()`+`chat_stream()`）；不支持 FC 时 `supports_function_calling=False`；流式 `tool_calls[].function.arguments` 必须 `json.loads()`；超时读 settings；错误抛 `AdapterError`
- **画布/设计工具**：作为 Tool 接入；HTTP 封装在 Adapter（infinite-canvas 唯一后端，经 canvas-agent 协议）；结果经 StateManager 持久化；画布边界见 Rule 7
- **CLI 工具**：`asyncio.create_subprocess_exec()`，禁止 `subprocess.run()` 阻塞；`await asyncio.sleep()`；解析失败抛 `AdapterError` 不返假数据
- **桌面端**：复用 `/api/agent/chat`，不得另写状态管理/LLM 逻辑

---

## 九、维护与修改规则

- **先读懂再动手**，不得"重写一遍"；修改范围最小化；不为"觉得更好"重构无关代码
- 删除前全局搜索确认无引用；DEPRECATED 保留别名导入不立即删；删除后跑测试
- 禁止提交 `print()` / `# TODO: remove` / `# HACK`；调试用 `logger.debug()`；临时 mock 不得覆盖正式实现
- **事故注释约定**：新注释只写结论（这里为什么这么做），不写事故过程；未清偿项登记于仓内清单（`docs/未清偿债务清单.md`），代码里引用事故编号即可

---

## 十、测试要求

- 新增 Tool→单测；新增路由→集成测试（TestClient）；新增 Adapter→mock 测试；改核心（Planner/StateManager/agent_loop/闸机）→回归测试
- 闸机改动→平台固定地板回归测试；提示词迁移→外置单一事实源断言；动作通道改动→FC 单轨一致性测试；新增 SSE 事件→sse_protocol 注册表登记

```bash
python scripts/acceptance.py             # 一键验收：三阶段 GATES→SUITES→RATCHETS（清单以脚本内同名表为准），只认 exit code
python scripts/acceptance.py --quick     # 快验：GATES + tsc（无 SUITES/RATCHETS）
python scripts/acceptance.py --with-eval # 终验：追加评测管线
```

---

## 十一、文件地图（核心锚点）

```
src/video_agent/
├── core/
│   ├── planner.py          ← Agent 唯一入口（Rule1）
│   ├── agent_loop.py       ← 节点内有界模型循环唯一实现（Rule2）
│   ├── workflow_runtime.py ← Workflow Runtime 账本+裁判数据层（Rule2 主体回归：定义编译/run reducer/产物账本/客观探针，不发起行动）
│   ├── pause_composer.py   ← 暂停卡通道/选项面处理（Rule2 主体回归：发行主体 = 模型 workflow_pause）
│   ├── fc_tool_runner.py   ← FC 轨执行臂；回喂家族在 fc_feedback.py
│   ├── fc_feedback.py      ← 工具结果回喂/压缩家族
│   ├── provider_injection.py ← provider 注入唯一分派面（按工具 provider_kind 声明统一注入，被 fc_tool_runner 顶层导入）
│   ├── chat_port.py        ← core 拥有的 LLM 数据契约 ChatResponse/StreamChunk + 结构化端口 ChatAdapterPort（依赖倒置，§六）
│   ├── planner_output.py   ← 轮末产出组装域
│   ├── round_end_policies.py ← 轮末策略状态机 + suggest_next_actions（轮末兜底引导卡唯一落点）
│   ├── prompt_gates.py     ← 提示词写入校验（validate_prompt_write 等）+ gates_cards 文案族 re-export 壳
│   ├── gate_registry.py    ← 闸机规则注册表唯一家（GATE_RULES，§2.3）
│   ├── guard_pipeline.py   ← 闸机管线（2.0，动作判定唯一入口）
│   ├── prompt_builder.py   ← 上下文组装；token_budget.py ← 窗口/截断
│   ├── action_executor.py  ← 状态视图载体（动作通道唯一 = FC 工具，文本轨动作分派
│                        已退役；防复活见 check_legacy_orchestration）
│   └── tracer.py           ← 审计链路
├── skill_runtime/
│   ├── registry.py / guard.py / progress.py
│   └── frontmatter.py / manifest_schema.py ← 文档头部 frontmatter 声明单一事实源（外置配置文件退役）
│   （执行器族已整体退役，防复活见 check_legacy_orchestration；
│     MCP 外部工具接入层为预留扩展点）
├── web/
│   ├── app.py / chat_service.py(+chat_opening/chat_consume/history_compact) / sse_protocol.py
│   ├── port_wiring.py ← core 端口装配点（web 侧 re-export 壳已清退）
│   ├── task_manager.py / skill_docs.py / routes/
├── state/  manager.py（唯一写入点）/ models.py / storyboard_ops.py / context_builder.py
├── adapters/  tools/  config.py  exceptions.py
├── utils/                  ← 跨切面原语下沉层（§六）：cancel_token.py / stop_signal.py / provider_config_loader.py / live_metrics.py / trace_retention.py / prompts.py / paths.py
src/web/                    ← SolidJS SPA 唯一前端（§3）
prompts/                    ← 指令治理外置资产（Rule6）
tests/fixtures/             ← 技能夹具等快照
```

---

## 十二、违规检查清单（代码审查用）

完成任何修改后，逐项确认：

- [ ] 没有修改画布项目的任何文件（Rule 7）
- [ ] 没有绕过 Planner / StateManager / Adapter / Tool 体系（Rule 1-5）
- [ ] 没有硬编码 prompt >3 行；文案治理迁移同批更新锁旧文案的断言测试（Rule 6）
- [ ] 没有 manifest 削弱平台硬边界；触碰项有负面用例（§2.2）
- [ ] 工具已声明 risk 分级；high 级工具带平台闸机与确认（§2.7）
- [ ] Skill 改动符合单一形态 `<slug>/SKILL.md` 与三级加载；官方 Skill 干净注入无包壳，仅外部导入带来源标记（§2.8）
- [ ] 闸机改动带平台固定地板回归；连续拦截有升级指引（§2.6）
- [ ] UI 改动符合 §3 与 `docs/前端体验规范.md`，且构建后经用户目测反馈确认
- [ ] 没有 box-shadow/发光出现在确认卡片；品牌仍为「飞天」
- [ ] 没有裸 restore/checkout -- .；本批已 commit；未跟踪文件已核对（§5）
- [ ] 拆分模块新增顶层符号已同步登记 re-export 壳清单，测试 patch 目标为调用方命名空间
- [ ] 测试不得写生产 data/skills（conftest session 级镜像目录保障）
- [ ] 暂停槽行为符合 Rule 2
- [ ] 一轮一 TurnResult 提交（turn_id 归组），无空文本 docCard 消息、无合成 actionLog（Rule2）
- [ ] 控制流范式表述唯一归宪法 Rule2（P1）
- [ ] 修改前已按 `docs/GOVERNANCE.md` 修复决策树定位归属层；没有在事故现场就近补条款（P1/P2）
- [ ] 没有在 Skill 文件里改系统层缺口；没有用 prose 教模型配合既有机制（G1/G3）

> 以下事项已由 acceptance 门禁机械强制，不再人工勾选：
> 方法内 import 防新增（check_func_imports）、
> 类别 Key 字面量（check_category_keys，CAT_* 单一事实源）、已删编排符号防复活（check_legacy_orchestration）、
> 前后端契约（gen_api_types --check + api-contract 桥接）、
> 四件套 pytest/vitest/tsc/eslint。
>（文件行数红线 check_file_lines 已随 2026-09-02「治理闸机减负」降为信息工具，不再入 GATES 硬闸；前端 max-lines 维持 eslint warn。）
