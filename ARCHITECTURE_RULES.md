# 架构宪法 — AI 协作开发强制约束（v6 · 2026-08-20）

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder / CodeBuddy 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
> 本版为宪法 v6：Rule 2 控制流范式按 2026-08-20 用户审定裁决（ADR-0003）翻转为
> **Workflow Runtime 单一控制实体**（反转批 12「模型主动权 + 平台否决权」，
> GOVERNANCE §13.13 同批修订）；指令治理层方法论（原第十三章）整体迁出为
> [docs/GOVERNANCE.md](docs/GOVERNANCE.md)（与总纲同权，编号 13.x 不变）。
> 历史版本归档：`docs/archive/recovery-sources-20260813/qoder-history/ARCHITECTURE_RULES-pre-damage-20260811.md`。
>
> **治理总纲：按业界最高标准执行，禁止走捷径。** 具体含义：
> 1. **策略即数据（Policy-as-Data）**：所有闸机/安全规则以注册表数据表达，带稳定 `rule_id`、层级归属、外置文案；禁止散落硬编码。
> 2. **单一事实源（Single Source of Truth）**：状态写入归 StateManager、循环归 agent_loop、入口归 Planner、提示词归 `prompts/`、前端类型归 `gen_api_types` 生成物、耦合行归 `core/coupling_registry.py`。
> 3. **评测驱动（Evaluation-Driven）**：闸机行为由黄金语料库校准，误杀/漏放计数劣化即测试失败；提示词迁移由快照测试锁语义。
> 4. **deny-overrides 分层合并**：平台硬边界永远优先，Skill 配置只能加强或持平，不能削弱。
> 5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批未提交改动（本仓库已因此丢过整批工作，见 §5）。
> 6. **验收 = 一键脚本 + 用户目测**：`python scripts/acceptance.py` 全 PASS（五门禁 + 四件套，**只认进程退出码**——Windows 终端乱码曾把契约门禁失败伪装成通过；`--with-eval` 补评测管线）；UI 变更必须构建后由**用户目测反馈**确认（不派浏览器子代理截图代目测，可做轻量定点代码级验证），缺一项不算完成。
> 7. **指令治理层（docs/GOVERNANCE.md，原第十三章）与本总纲同权**：任何规则只有一个家（P1）、约束下沉代码层（P2）、状态即数据（P3）；修改前必须按 GOVERNANCE.md §13.5 决策树定位归属层，禁止在事故现场就近补条款。

---

## 一、核心架构铁律

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` / `handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: Workflow Runtime 单一控制实体 + 动作通道单轨（FC）
- `core/agent_loop.py::run_agent_loop()` 是节点内有界模型循环的**唯一实现**；`MAX_STEPS` 读 `settings.max_steps`
- **动作通道唯一 = FC 工具调用**（`core/fc_tool_runner.py`）；4-4 双轨退役（audit-0819，ADR-0001）已删除：非 FC 聊天通道（agy CLI）、text_actions.md 注入、退化信号探测、流式预执行；禁止恢复自由文本动作解析
- **确认单轨化（audit-0819b/0819d）**：暂停确认唯一经 `workflow_pause` FC 工具产生（单一正名，对齐业界「只有一个 AskUserQuestion」；别名工具 request_confirmation 与文本别名归一 split_actions 已删），经 llm_call 第 5 元组结构化上抛；合成 studio-actions 文本块、流式抑制器（S01）、strip 清洗已同批删除；`agent_loop` 纯文本轮仅收尾（轮末策略照常承重）；mock 演示动作以结构化 dict 直达执行器
- **执行器结构化输出（audit-0819d）**：执行器子 LLM 的 JSON 产出点一律下发 `response_format=json_object`（端点不支持时适配器探针剥离降级），产出严格 `json.loads` 校验，畸形走既有 C2 拒因纠正重试——宽容正则兜底已删（S17），禁止恢复；外来工具名运行时翻译层（S15）已删，Skill 导入期工具名转换归专用 Skill 系统
- **闸机单轨一致**：所有动作判定统一经 `core/guard_pipeline.py`（见 §2.0），禁止旁路
- **控制流统一 v2（2026-08-20 裁决，ADR-0003，1111 根治）**：`core/workflow_runtime.py` 是控制流**唯一驱动器**——Skill 激活编译 `WorkflowDefinition`（canonical slug + revision + content hash，源 = sidecar 声明，`validate_sidecar` 注册期门禁）；持久化 `WorkflowRun`（current_node/completed_nodes/pending_gate/artifacts），**仅 runtime reducer 可改**（StateManager 仍唯一写入点，Rule 3）。**确定性阶段**（阶段表声明 executors）由 runtime 直跑，**零模型规划轮**；**创作型阶段**（deterministic=False）交接有界模型循环（`agent_loop` 为节点内唯一实现）；模型只做节点内语义创作，**不决定阶段顺序、不撰写暂停卡选项面**。平台保留否决权：`platform.stage_precondition`/暂停纪律闸/原料闸/规格闸内嵌执行路径首位（hooks guarantee behavior），不依赖模型自觉。**原子轮提交**：一轮只提交一个 `TurnResult`（body+artifacts+timeline_events+decision_request+next_transition，turn_id 归组）；正文只承载成果；暂停卡只承载一句问句 + 系统派生选项；文档卡源自同轮 artifact；**正常完成禁空正文**；`ArtifactCommitted` 先于 `StageSucceeded`；SSE/历史/时间线/卡片四投影同源派生，瞬态通道不得作为唯一可见性；一切机械动作进转录一等条目。批 12「模型主动权 + 平台否决权」范式与「快路径退场」叙事被本裁决退役（GOVERNANCE §13.13 同批改指针，P1 规则单家）；控制流决策全记 `tracer.record_control_flow` + `[ControlFlow]` 日志，永不无据可查
- **动作语义唯一实现**：故事板增删改查领域逻辑统一在 `state/storyboard_ops.py`，执行路径必须委托，禁止各自重写查找/字段白名单/类别映射
- **层级例外（已收敛）**：`web/action_executor.py` 因依赖 web 生成管线暂留 web 层；core→web 顶层 import 一律禁止（经构造注入装配）

### Rule 3: StateManager 唯一写入点
- `state/manager.py::StateManager` 是状态的**唯一写入点**；复杂嵌套操作允许直接操作 `state_dict`，但完成后**必须 `save()`**
- **禁止**在 routes / tools / adapters 中直接写 JSON 文件；**禁止**绕过单例自建状态实例

### Rule 4: 外部调用必须走 Adapter
- LLM/图/视频外部调用必须继承 `adapters/base_chat.py::BaseChatAdapter` 或 `adapters/base.py::Base{Image,Video}Adapter`
- **禁止**在 route / tool / planner 中直接 `httpx.post()` / `requests.get()`；错误抛 `AdapterError`，不得静默吞掉

### Rule 5: Tool 统一注册 + 消歧原则
- 新增业务 Tool 继承 `tools/base.py::BaseTool`，实现 `get_input_schema()`（Pydantic）+ `aexecute()`，经 `ToolManager.register()` 注册
- 业务 Tool 必须声明 `risk = low|medium|high`（按可逆性/影响面，见 §2.7）；未声明视为 high（deny-by-default）
- **工具消歧原则**：同名近义工具优先通过重写 description 互斥消歧；**改名/合并属高风险重构，必须单独评估立项**

### Rule 6: 指令治理（Prompt 外置 + 单一事实源 + 快照防漂移）
- 所有 system prompt / 闸机文案 / 回喂模板存放在 `prompts/`（`planner/`、`gates/`、`shared/`、`memory/` 分区），经 `utils/prompts.py::load_prompt()` / `load_prompt_section()` 加载
- **禁止**在代码中硬编码超过 3 行的 prompt 字符串；代码只留组装逻辑
- **快照防漂移**：提示词外置/迁移必须配快照测试，锁定迁移前后关键段落语义一致；无快照测试的迁移视为错误实现
- **双协议瘦身**：FC 模式用 `prompts/planner/system_fc.md`，文本模式用 `system.md`；共有段落抽到 `prompts/shared/` 引用拼装，两文件互不复制
- 纪律条款外置为独立 md（如 `planner/skill_discipline.md`），不得内联代码

### Rule 7: 画布边界 — 任何时候都禁止修改
- 画布是**独立迭代项目**，代码不在本仓库，**任何时候禁止修改其任何文件**
- 与画布交互只走其既有公开接口（HTTP/WS/iframe），统一封装在 `adapters/canvas_adapter.py`
- 画布既有接口之外的能力一律视为不可实现；确需新能力只能向画布项目提需求

---

## 二、闸机与安全边界宪法

### 2.0 闸机管线宪法（Guardrails are Execution Logic）
- 闸机是**执行逻辑**，不是提示词条款：任何「拦截/放行/剥离」不得依赖模型自觉遵守。
- 统一 guard pipeline：`input guard → tool input guard → tool execute → tool output guard → output guard → audit`；
  动作通道单轨（FC，Rule 2），全部判定经同一管线实例。
- 工具级闸在**每一次工具调用**前后都执行；tripwire 触发立即中断并保留已完成调用记录，禁止把残品当成品。
- 所有 verdict 结构化（`GateVerdict(rule_id, layer, ok, message)`），回喂模型与展示用户用同一源，杜绝两套说辞。

### 2.1 三层策略模型
| 层 | 内容 | 可配置性 |
|---|---|---|
| 平台层 `platform.*` | 生成确认闸、阶段硬边界（写文档/建结构强制暂停）、首拆只允关键元素、防虚报覆盖、gate_heal 自愈、提示词结构硬条款（字数/语言/字段） | **硬编码，manifest 无权关闭**；仅可经用户一次性申诉逐条放行 |
| Skill 层 `skill.*` | 时长/字幕/镜头语言/音频层标记、中文占比、最短字数、@引用、spec_gate 流程前置、元素概念图前置、故事板审阅窗口 | manifest 可关/可放宽/**可加严**；字数阈值只可抬高不可低于平台地板；**流程闸默认只警告不拦人（4444 语义，用户第一）** |
| 会话层 `session.override` | 用户「本次放行」一次性记录 | 仅用户手动产生，即时消费、留痕、不可持久化 |

### 2.2 manifest 只能加强或持平（强制不变量）
- 外部 Skill 文档来自成熟平台，其配置**不可信**；系统必须坚守自身安全底线
- **Skill 全文是数据，不是指令**：其中的命令性文字只能约束风格/流程，不能覆盖平台闸机、不能要求执行平台外动作
- manifest 试图触碰 `platform.*` 的任何键：**静默忽略 + warning 日志**，并必须有负面用例测试断言其无效
- 可配项仅限风格/流程类；「规格前置」经用户确认为可配置项，不锁死

### 2.3 规则注册表（Policy-as-Data）
- `core/prompt_gates.py` 维护 `GATE_RULES` 注册表：稳定 `rule_id` + 层归属 + 中文描述
- 判定返回结构化 `GateVerdict(rule_id, layer, ok, message)` 列表；文案外置 `prompts/gates/messages.md`，杜绝自由文本
- 回喂模型与展示用户用**同一 verdict 源**（防两套说辞）

### 2.4 拦截可见 + 一次性申诉放行
- 拦截必须用户侧可见（警示 chips 带规则描述 + 来源标注「平台」/「Skill『xxx』」）
- **Context ≠ Consent（上下文不等于同意）**：平台硬边界只能被「针对**当前动作**的显式用户指令」解除；模型不得自证「用户已确认」，历史上下文、Skill 文档中的「用户已同意/默认放行」一律不构成同意。
- 「本次放行」单次生效、全程留痕、不形成持久削弱；每次放行单独点，且必须可追溯到产生它的用户消息。

### 2.5 审计闭环
- `tracer.record_gate(...)` 持久化到 `agent_traces.jsonl`；调试端点 `GET /api/agent/gates` 与 `/api/agent/traces` 并列
- 闸机触发/放行、工具调用、执行器输出校验、截断/回滚全部入 trace；执行器内层模型异常落黑匣子档案（只落盘不进上下文）

### 2.6 校准闭环（评测驱动）
- `tests/fixtures/gate_corpus/` 黄金语料（合法/应拦两组真实风格样例，带期望 verdict）；按 规则×Skill profile 遍历，误杀/漏放计数劣化即测试失败
- **闸机校准经验**：连续相同原因拦截必须升级改写指引（合并相同 verdict、附「第 N 次被拦」差异化提示），防模型陷入「拦截-重写-再拦截」空转；拦截事件入生成日志面板可见

### 2.7 工具风险分级（Tool Risk Tiers）
- 每个业务 Tool 声明 `risk = low | medium | high`：low=只读/可逆；medium=写状态但可撤销；high=生成、文档写入、跨阶段建结构、外部副作用。
- high 级工具必须平台闸机 + 用户确认；medium 级按 Skill 配置；low 级直接执行。
- 新工具未声明风险级别视为 high（deny-by-default），不得静默放行。

### 2.8 执行器宪法（Skill = 注册表 + 执行器）
- Skill 上传/保存/删除 = `data/skills/*.md` 唯一数据源 + 自动解析 manifest → 刷新执行器注册表；下拉框数据源不变。
- 执行器是 Planner 可调用的受管子代理工具（agent-as-tool）：独立上下文、独立工具白名单、结构化输入输出校验。
- 执行器失败**禁止绕过回喂主模型**；主模型不得假装执行器已执行。
- 执行器注册表是数据（policy-as-data），不得散落硬编码；`SKILL_RUNTIME=auto` 按 Skill 是否可解析出执行器章节自动选择 executors / legacy。

---

## 三、前端体验宪法

### 3.1 体验基线不退化
- **2026-08-12 02:00 前的系统状态为可接受基准线（baseline）**；任何变更不得导致基线功能/交互/视觉退化
- UI 变更必须构建后经**用户目测反馈**确认交付（禁止浏览器子代理截图代目测——动作慢、截不到目标图且浪费算力；可做轻量、定点、快速的代码级验证）；「测试全绿」不等于「UI 正确」
- **品牌、视觉与交互细节规范（飞天品牌、确认卡片样式、@面板、分组卡片等）**见 `docs/前端体验规范.md`，同样为强制约束，由前端工程按批次执行

### 3.4 前端工程
- 唯一前端为 `src/web` SolidJS SPA，构建产物 `static/dist`；启动脚本自动补构建；**禁止**复活旧 studio 页面
- 前端类型以 `scripts/gen_api_types.py` 生成物为契约，`--check` 纳入每批验收；**前端 API 边界类型以 `api.generated.ts` 为唯一来源**（豁免/精化清单登记于 `types/index.ts` 文件头；生成物豁免 eslint max-lines）；消费覆盖防回退由 `api-contract.test.ts` 桥接测试机械断言

---

## 四、运行时配置宪法

- `Settings` 为 frozen dataclass（全局不可变约定）；运行时热切换**仅限** `web/routes/runtime_settings.py` 域，经 `object.__setattr__` 定点突破并落盘 `data/runtime_settings.json`，启动时加载覆盖
- **模型 fallback 开关语义（用户定义）**：开 = 厂商联不通/出不了图视频时自动换同模型其他 API 厂商；关 = 直接按上游报错。默认开；顶栏开关热生效不重启

---

## 五、进程与版本治理宪法（血泪条款）

> 本仓库 2026-08-12 曾因「未提交改动 + 救火回滚」丢失整批工作。以下条款为强制铁律：

1. **开工先备份**：任何修复/整改会话开工前，先建备份分支并立即 commit 现状；每完成一批立即 commit，**禁止攒大批未提交改动**
2. **救火先留现场**：回滚前先把现场 commit 到 archive 分支；**禁止裸 `git restore .` / `git checkout -- .`**（reflog 不留痕的销毁式操作）
3. **备份切回核对**：从含未跟踪文件的备份分支切回后，必须 `git diff --diff-filter=A -z` 核对并恢复被 git 删除的未跟踪文件
4. **端口清理**：重启服务前先按 PID 杀净旧进程（`netstat -ano | findstr :8080`），防旧代码假象
5. **验收 = acceptance.py 全 PASS**：只认进程退出码，人眼读终端输出不算验收（Windows GBK 乱码曾把「契约不一致」伪装成「一致」）；`--with-eval` 终验补评测管线；pre-commit 钩子强制执行
6. **分支现状**：以 git 分支实际状态与事故台账为准，宪法不复述具体分支名（v3 曾复述，随合并过期漂移）
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
- **画布/设计工具**：作为 Tool 接入；HTTP 封装在 Adapter；结果经 StateManager 持久化；画布边界见 Rule 7
- **CLI 工具**：`asyncio.create_subprocess_exec()`，禁止 `subprocess.run()` 阻塞；`await asyncio.sleep()`；解析失败抛 `AdapterError` 不返假数据
- **桌面端**：复用 `/api/agent/chat`，不得另写状态管理/LLM 逻辑

---

## 九、维护与修改规则

- **先读懂再动手**，不得"重写一遍"；修改范围最小化；不为"觉得更好"重构无关代码
- 删除前全局搜索确认无引用；DEPRECATED 保留别名导入不立即删；删除后跑测试
- 禁止提交 `print()` / `# TODO: remove` / `# HACK`；调试用 `logger.debug()`；临时 mock 不得覆盖正式实现
- **事故注释约定**：新注释只写结论（这里为什么这么做），不写事故过程；事故叙事的唯一载体是台账（`docs/archive/incident-ledger.md`），代码里引用事故编号即可

---

## 十、测试要求

- 新增 Tool→单测；新增路由→集成测试（TestClient）；新增 Adapter→mock 测试；改核心（Planner/StateManager/agent_loop/闸机）→回归测试
- 闸机改动→黄金语料校准测试；提示词迁移→快照测试；动作通道改动→FC 单轨一致性测试；新增 SSE 事件→sse_protocol 注册表登记
- 耦合行变更→同批更新 `core/coupling_registry.py`（遍历测试钉死，漏改即红）

```bash
python scripts/acceptance.py             # 一键验收：四件套+五门禁，只认 exit code
python scripts/acceptance.py --quick     # 快验：门禁 + tsc
python scripts/acceptance.py --with-eval # 终验：追加评测管线
```

---

## 十一、文件地图（核心锚点）

```
src/video_agent/
├── core/
│   ├── planner.py          ← Agent 唯一入口（Rule1）
│   ├── agent_loop.py       ← 节点内有界模型循环唯一实现（Rule2）
│   ├── workflow_runtime.py ← Workflow Runtime 唯一驱动器（Rule2 v6：定义编译/run reducer/就绪批驱动/原子提交）
│   ├── pause_composer.py   ← 暂停卡唯一发行点（Rule2 v6 三通道契约）
│   ├── fc_tool_runner.py   ← FC 轨执行臂；回喂家族在 fc_feedback.py
│   ├── fc_feedback.py      ← 工具结果回喂/压缩家族（C3 落点）
│   ├── planner_output.py   ← 轮末产出组装域
│   ├── round_end_policies.py ← 轮末策略状态机 + suggest_next_actions（层 9 唯一落点）
│   ├── prompt_gates.py     ← 闸机规则注册表 + 结构/流程判定（§2）
│   ├── gates_spec.py / gates_script.py ← 规格/剧本闸家族（prompt_gates 尾部 re-export）
│   ├── guard_pipeline.py   ← 闸机管线（2.0，动作判定唯一入口）
│   ├── prompt_builder.py   ← 上下文组装；token_budget.py ← 窗口/截断
│   ├── coupling_registry.py ← 13.7 耦合表机器可读化（test_coupling_registry 钉死）
│   └── tracer.py           ← 审计链路
├── skill_runtime/
│   ├── executors/          ← re-export 壳（承重）
│   ├── exec_common.py / exec_spec.py / exec_tools.py / exec_split.py
│   └── dag.py / registry.py / guard.py / progress.py / blackbox.py
├── web/
│   ├── app.py / chat_service.py(+chat_opening/chat_consume) / sse.py / sse_protocol.py
│   ├── action_executor.py  ← 动作执行器；生成动作域在 action_gen.py
│   ├── task_manager.py / skill_docs.py / routes/
├── state/  manager.py（唯一写入点）/ models.py / storyboard_ops.py / context_builder.py
├── adapters/  tools/  memory/  config.py  exceptions.py  utils/
src/web/                    ← SolidJS SPA 唯一前端（§3）
prompts/                    ← 指令治理外置资产（Rule6）
tests/fixtures/             ← 技能夹具 + gate_corpus + skill_pause_golden 等快照
```

---

## 十二、违规检查清单（代码审查用）

完成任何修改后，逐项确认：

- [ ] 没有修改画布项目的任何文件（Rule 7）
- [ ] 没有绕过 Planner / StateManager / Adapter / Tool 体系（Rule 1-5）
- [ ] 没有硬编码 prompt >3 行；提示词迁移带快照测试；文案治理迁移同批更新锁旧文案的断言测试（Rule 6）
- [ ] 没有 manifest 削弱平台硬边界；触碰项有负面用例（§2.2）
- [ ] 工具已声明 risk 分级；high 级工具带平台闸机与确认（§2.7）
- [ ] Skill 保存/删除后执行器注册表已同步；执行器失败未绕过回喂（§2.8）
- [ ] 闸机改动带黄金语料校准；连续拦截有升级指引（§2.6）
- [ ] UI 改动符合 §3 与 `docs/前端体验规范.md`，且构建后经用户目测反馈确认
- [ ] 没有 box-shadow/发光出现在确认卡片；品牌仍为「飞天」
- [ ] 没有裸 restore/checkout -- .；本批已 commit；未跟踪文件已核对（§5）
- [ ] 拆分模块新增顶层符号已同步登记 re-export 壳清单，测试 patch 目标为调用方命名空间
- [ ] 测试不得写生产 data/skills（conftest session 级镜像目录保障）
- [ ] 耦合行变更已同批更新 coupling_registry.py（十、3 条）
- [ ] 确定性阶段无 model_reasoning 条目（零规划轮），暂停卡选项全系统派生（无模型自造继续/规格类选项）（Rule2 v6）
- [ ] 一轮一 TurnResult 提交（turn_id 归组），无空文本 docCard 消息、无合成 actionLog（Rule2 v6）
- [ ] 控制流范式表述唯一归宪法 Rule2，ADR/GOVERNANCE 仅指针（P1）
- [ ] 修改前已按第十三章 13.5 决策树定位归属层；没有在事故现场就近补条款（P1/P2）
- [ ] 没有在 Skill 文件里改系统层缺口；没有用 prose 教模型配合既有机制（G1/G3）

> 以下事项已由 acceptance 门禁机械强制，不再人工勾选：文件行数红线/棘轮（check_file_lines）、
> 提示词严禁预算（check_prompt_budget）、方法内 import 防新增（check_func_imports）、
> 治理叙事标记预算（check_governance_refs）、类别 Key 字面量（check_category_keys，CAT_* 单一事实源）、已删编排符号防复活（check_legacy_orchestration）、
> 前后端契约（gen_api_types --check + api-contract 桥接）、
> 四件套 pytest/vitest/tsc/eslint。

---
## 十三、指令治理层（迁出指针）

> 第十三章（13.1-13.12：三大宪法原则/指令层清单/归属表/症状归位/决策树/
> 体量预算/耦合点/事故台账指针/模型分层/业界基准 C1-C6/AI 助手方案纪律 G1-G4）
> 整体迁出为 [docs/GOVERNANCE.md](docs/GOVERNANCE.md)（整改计划批 11，宪法 v5）。
> **该文档与宪法总纲同权**；全文代码指针中的 13.x 编号对应该文档章节。
> 核心不变量速览：任何规则只有一个家（P1）、约束下沉代码层（P2）、
> 状态即数据（P3）；修复先走 13.5 决策树；方案先过 G1-G4 四关。
