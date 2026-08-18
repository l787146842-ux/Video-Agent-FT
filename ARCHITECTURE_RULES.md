# 架构宪法 — AI 协作开发强制约束（v4 · 2026-08-16）

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder / CodeBuddy 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
> 本版为宪法 v4：v3 主干不动，执行「治理层瘦身」——已机械化事项改指针、债务表归台账（八轮 B8）。
> 历史版本归档：`docs/archive/recovery-sources-20260813/qoder-history/ARCHITECTURE_RULES-pre-damage-20260811.md`。
>
> **治理总纲：按业界最高标准执行，禁止走捷径。** 具体含义：
> 1. **策略即数据（Policy-as-Data）**：所有闸机/安全规则以注册表数据表达，带稳定 `rule_id`、层级归属、外置文案；禁止散落硬编码。
> 2. **单一事实源（Single Source of Truth）**：状态写入归 StateManager、循环归 agent_loop、入口归 Planner、提示词归 `prompts/`、前端类型归 `gen_api_types` 生成物、耦合行归 `core/coupling_registry.py`。
> 3. **评测驱动（Evaluation-Driven）**：闸机行为由黄金语料库校准，误杀/漏放计数劣化即测试失败；提示词迁移由快照测试锁语义。
> 4. **deny-overrides 分层合并**：平台硬边界永远优先，Skill 配置只能加强或持平，不能削弱。
> 5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批未提交改动（本仓库已因此丢过整批工作，见 §5）。
> 6. **验收 = 一键脚本 + 用户目测**：`python scripts/acceptance.py` 全 PASS（五门禁 + 四件套，**只认进程退出码**——Windows 终端乱码曾把契约门禁失败伪装成通过；`--with-eval` 补评测管线）；UI 变更必须构建后由**用户目测反馈**确认（不派浏览器子代理截图代目测，可做轻量定点代码级验证），缺一项不算完成。
> 7. **第十三章（指令治理层）与本总纲同权**：任何规则只有一个家（P1）、约束下沉代码层（P2）、状态即数据（P3）；修改前必须按 13.5 决策树定位归属层，禁止在事故现场就近补条款。

---

## 一、核心架构铁律

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` / `handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: 多步循环唯一实现 + 双轨一致
- `core/agent_loop.py::run_agent_loop()` 是多步循环的**唯一实现**；`MAX_STEPS` 读 `settings.max_steps`
- **双轨执行**：FC 轨（`core/fc_tool_runner.py`）与文本轨（`web/action_executor.py`）必须对同一请求使用**同一 guard pipeline 实例**（`core/guard_pipeline.py`，见 §2.0）与同一动作语义，判定逐字节一致；新增判定逻辑必须双轨同测
- **动作语义唯一实现**：故事板增删改查领域逻辑统一在 `state/storyboard_ops.py`，双轨必须委托，禁止各自重写查找/字段白名单/类别映射
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
  FC 轨与文本轨使用**同一管线实例**，同一请求判定逐字节一致（Rule 2）。
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
- 闸机改动→黄金语料校准测试；提示词迁移→快照测试；双轨改动→双轨一致性测试；新增 SSE 事件→sse_protocol 注册表登记
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
│   ├── agent_loop.py       ← 多步循环唯一实现（Rule2）
│   ├── fc_tool_runner.py   ← FC 轨执行臂；回喂家族在 fc_feedback.py
│   ├── fc_feedback.py      ← 工具结果回喂/压缩家族（C3 落点）
│   ├── planner_output.py   ← 轮末产出组装域
│   ├── round_end_policies.py ← 轮末策略状态机 + suggest_next_actions（层 9 唯一落点）
│   ├── prompt_gates.py     ← 闸机规则注册表 + 结构/流程判定（§2）
│   ├── gates_spec.py / gates_script.py ← 规格/剧本闸家族（prompt_gates 尾部 re-export）
│   ├── guard_pipeline.py   ← 双轨共用闸机管线（2.0）
│   ├── prompt_builder.py   ← 上下文组装；token_budget.py ← 窗口/截断
│   ├── coupling_registry.py ← 13.7 耦合表机器可读化（test_coupling_registry 钉死）
│   └── tracer.py           ← 审计链路
├── skill_runtime/
│   ├── executors/          ← re-export 壳（承重）
│   ├── exec_common.py / exec_spec.py / exec_tools.py / exec_split.py
│   └── dag.py / registry.py / guard.py / progress.py / blackbox.py
├── web/
│   ├── app.py / chat_service.py(+chat_opening/chat_consume) / sse.py / sse_protocol.py
│   ├── action_executor.py  ← 文本轨执行器；生成动作域在 action_gen.py
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
- [ ] 修改前已按第十三章 13.5 决策树定位归属层；没有在事故现场就近补条款（P1/P2）
- [ ] 没有在 Skill 文件里改系统层缺口；没有用 prose 教模型配合既有机制（G1/G3）

> 以下事项已由 acceptance 门禁机械强制，不再人工勾选：文件行数红线/棘轮（check_file_lines）、
> 提示词严禁预算（check_prompt_budget）、方法内 import 防新增（check_func_imports）、
> 治理叙事标记预算（check_governance_refs）、类别 Key 字面量（check_category_keys，CAT_* 单一事实源）、已删编排符号防复活（check_legacy_orchestration）、
> 前后端契约（gen_api_types --check + api-contract 桥接）、
> 四件套 pytest/vitest/tsc/eslint。

---

## 十三、指令治理层

> **本节背景**：2222/3333/4444/5555/6666/7777/8888 系列事故的复盘显示同一模式——
> 每次出事就在“出事的那一层”补一条条款，同一条规则最终散落在 5+ 个层且各自表述，
> 思考模型把大量推理时间花在调解层间冲突上，补丁越多分歧越大。
> **本节目标：任何规则只有一个家；任何修复只动规则的家，不动症状现场。**

### 13.1 三大宪法原则

**P1 单一事实源（Single Source of Truth）**
每条规则只有一个**表述源**（归属见 13.3）。其他层需要提及该规则时，只能引用，**禁止复述条款内容**。复述即漂移，漂移即打架。一条规则允许同时存在“引导 + 校验”两个角色，但表述源唯一、校验实现唯一；引导与校验冲突时，以代码校验的客观结果为准并修表述。

**P2 约束下沉（Code over Prose）**
能被代码机械校验的规则，一律实现为工具/执行器层校验（拒收+报错回喂/自动修正），**禁止**用 prose（“严禁/必须”）说服模型。每一条“严禁”都是没能在工具层解决的债务；新增 prose 禁令前必须先回答：“这条为什么不能被代码校验？”
**校验作用域**：代码校验只裁定**模型产出的格式与客观状态**，永不拦截**用户意志**——用户指令永远优先，闸机对用户越流程的操作只警告不拦人；拒收后的重试提示词也不得夹带新规则。

**P3 状态即数据（State as Data）**
注入给模型的状态/工具结果必须是纯客观数据。引导语独立且极短，**禁止**把说教嵌入数据体。

### 13.2 指令层全量清单（共 12 层）

修改任何模型可见文本前，先在此表定位它属于哪一层：

| # | 层 | 位置 | 注入时机 | 唯一职责 | 禁止承载 |
|---|----|------|---------|---------|---------|
| 1 | 平台协议 | `prompts/planner/system.md`（FC 用 `system_fc.md`） | 主模型每轮 | 动作格式/暂停通道/输出纪律/工具使用法 | 业务领域规则 |
| 2 | 文本协议 | `prompts/planner/text_actions.md` | 仅非 FC 通道 | studio-actions 全量动作定义 | 流程/业务规则 |
| 3 | Skill 文档 | `data/skills/*.md` | planner 章节/执行器内章节 | 该 Skill 的阶段内创作引导（产出规范/创作要求），纯散文 | 流程顺序与暂停点（已归平台编排+sidecar 声明）；模型能力参数 |
| 4 | 执行铁律文档 | 项目内「执行铁律.md」（`spec_rules` 模板） | Skill 激活时全文注入 | 项目级可编辑生产契约 | 平台协议、流程步骤 |
| 5 | 制片规格文档 | 项目内规格文档（Final_Video_Spec.md 等） | 执行器显式注入/按需 read | 本项目参数事实（画幅/分辨率/渠道/时长） | 任何规则性表述 |
| 6 | 执行器提示词 | `skill_runtime/executors.py`（_TASK/_BOUNDARY/自检词） | 执行器独立调用 | 单一任务的输出格式与边界 | 跨阶段流程规则 |
| 7 | 闸机 | `core/prompt_gates.py` + `core/guard_pipeline.py` | 工具裁剪/警告/回喂 | 客观状态校验与阶段门禁 | prose 说服（闸机只裁定，不说教） |
| 8 | 回喂话术 | `agent_loop.py`/`planner.py`/`fc_tool_runner.py` | 轮间 | 客观回报上轮结果 + 单句下一步；允许当轮短期指令 | 持久性规则条款 |
| 9 | 系统兜底卡 | agent_loop/planner/chat_service + `round_end_policies.py` | 轮末 | 客观状态 → 确定性交互，不依赖模型自觉 | 无（代码行为，非指令） |
| 10 | Tool description | `tools/*.py` 的 description 字段 | FC 通道每轮随 schema | 该工具做什么、参数含义 | 跨工具流程规则 |
| 11 | 状态上下文 | `state/context_builder.py` | 每轮 | 客观工作台数据 | 说教性引导语 |
| 12 | 记忆与解除引导 | `memory/` 注入；chat_service 消费函数 | 按需 | 项目历史偏好；暂停窗口的回应语义 | 新规则 |

> **层 8 特别条款**：代码里硬编码的运行时回话模板是每轮强制喂给模型的动态指令，属于受治理对象：
> ① 措辞不得自相矛盾；② 修改此类模板必须走与文件规则相同的登记+审查流程并记入台账；
> ③ 季度“严禁审计”的 grep 范围必须包含这些模板文件。

### 13.3 规则归属表（Single Source of Truth 落地）

| 规则类型 | 唯一定义层 | 禁止出现在 |
|---------|-----------|-----------|
| 平台对话协议 | 层 1 system.md / system_fc.md | Skill、铁律、执行器 |
| 项目级生产契约 | 层 4 铁律文档 | system.md 硬编码、执行器常量 |
| 阶段顺序与暂停点 | 平台状态计算（`core/pipeline_orchestrator.py`）+ sidecar 声明（`data/skills_manifests/<slug>.json` 的 flow/pause） | Skill 散文、system.md、回喂话术 |
| 单一执行器的输出格式与边界 | 层 3 Skill 对应章节是唯一表述源；层 6 只承载任务目标与格式锚点 | system.md |
| 模型能力参数（分辨率/时长/渠道） | 层 5 制片规格（运行时动态注入）+ 全局设置 | Skill 硬编码数值、执行器写死数值 |
| 可机械校验的约束 | 层 7/9 代码校验（拒收或修正） | 任何 prose 层重复表述 |
| 通用提示词规范 | 层 3 Skill 的提示词章节 | system.md |
| Skill 的平台行为开关 | sidecar 声明 `data/skills_manifests/<slug>.json`（声明唯一源，引擎默认最小闸） | Skill 散文、平台通用层硬编码 |
| 规格向导/剧本闸启停 | sidecar 声明（registry.spec_wizard_active / script_required_active 纯读 sidecar）；sidecar 显式逃生门 | 文本启发式扫描 |
| 阶段内创作引导 | 层 3 Skill 散文（纯散文，只管阶段内怎么写） | 平台层排序条款、sidecar |

**冲突裁决顺序（模型可见优先级）**：用户最新指令 > 铁律文档 + 制片规格 > Skill > 平台协议默认。代码校验层不参与裁决——它是客观事实，只对结果裁定并回报。

### 13.4 症状归位表（不走捷径的核心）

修复任何模型行为问题前，先在下表找到症状对应的正确归位层；**禁止在“捷径层”动手**。

| 症状 | 正确归位层 | 禁止的捷径（历史事故） |
|------|-----------|---------------------|
| 模型该暂停时没暂停 | 编排器阶段边界机械暂停（pipeline_orchestrator）+ sidecar pause 声明 | 在多层同时加“必须暂停”prose（5555） |
| 模型输出缺字段/格式错 | 层 6 执行器拒收+重试+格式锚点 | 只在 prose 加“必须携带 X 字段”（8888） |
| 模型虚报完成 | 层 7 客观状态核验 + 只警告不拦人 | 硬拦截没收暂停（4444） |
| 产出数量失控 | 铁律+Skill+执行器任务词三处**同步**写比例约束，自检限轮数 | 单向穷举表述与克制条款并存（8888） |
| 工具成果用户看不见 | 层 9 系统兜底拼入正文/即时 SSE 事件 | 只加“必须展示”prose（2222/3333） |
| 参数与生成能力不符 | 层 5 规格收集 + 执行器运行时注入 + 全局设置 | Skill/执行器硬编码数值 |
| 模型继续推进了不该推进的阶段 | 阶段顺序由平台状态计算（编排器）裁定，模型不参与排序 | 在回喂话术里加长段告诫（5555） |
| Skill 流程与平台行为不符 | 系统层：平台闸启用条件 + 执行器冲突裁决注入 + 适配层填参 | 修改 Skill 文件或其 manifest 声明（S2；T16/T17 类清理须用户显式裁决） |
| 模型产出不达标 | 查系统约束：输出预算/思考预算/截断处置，修管线 | 放宽 Skill 要求迁就系统缺陷（S2） |

### 13.5 修复决策树（每次修改前的强制思考流程）

```
问题出现
  ├─ Q1 这是什么规则失效？按 13.4/13.3 定位它的唯一定义层
  │     └─ 找不到归属 → 它是一条新规则，按 13.3 选层安家，而不是在症状现场造新家
  ├─ Q2 这条规则能被代码机械校验吗？
  │     ├─ 能 → 在层 7/9 实现校验（拒收/修正/兜底），不加 prose
  │     └─ 不能（主观判断类）→ 改 prose，但只改唯一定义层
  ├─ Q3 该规则在其他层已有分身？有 → 删除分身或改引用，禁止两个版本并存
  ├─ Q4 实施修改 + 回归测试（每个事故必须有一个回归用例，用例名带事故编号）
  └─ Q5 查 coupling_registry.py 是否涉及耦合行；在台账记一行
```

**捷径禁令（违者视为错误实现）**：禁止在事故现场就近补条款而不查归属层；禁止同一条规则在两层以上新增表述；禁止新增 prose 禁令前不回答“为什么不能被代码校验”；禁止修改铁律模板/Skill/协议时不同步检查另两处的同义条款；禁止用“模型不听话”作为结论——先查是否层间冲突；禁止给确定性任务出题给模型。

**确定性三问判别法（每次决定“某个细节交给模型还是系统”前必问）**：
1. 正确答案能不能从已有数据里算出来？
2. 对错能不能被机器一眼判定？
3. 有没有创作空间？

判定：**1+2 都是 → 收归系统自动做**；只有 2 是 → 模型写、系统验收（验收标准跟 skill_manifest 声明走）；3 是 → 留给模型，人审阅，机器闸不得卡创作质量。

### 13.6 指令体量预算（防反弹的量化红线）

| 项 | 预算 | 超限处理 |
|----|------|---------|
| system.md / system_fc.md | ≤ 7KB（纯协议） | 继续压缩或拆分按需注入 |
| 全链路“严禁/不得/禁止”总数 | ≤ 8 处 | 逐条审计，可机械校验者下沉；CI 门禁 `scripts/check_prompt_budget.py` |
| 单执行器 system+user 提示词 | ≤ 25K 字符 | 缩减注入而非删任务词 |
| 回喂话术单条 | ≤ 3 句 | 超出说明在回喂里写规则，迁回归属层 |
| 同一规则的定义处数量 | 恒等于 1 | 立即清理分身 |

每季度（或每 3 个事故后）做一次“严禁审计”：`grep -rn "严禁\|不得" prompts/ src/video_agent/core/ src/video_agent/skill_runtime/ data/skills/`，逐条回答“能否下沉/是否重复”，结果记入台账。

### 13.7 耦合点清单（改 A 必须同步检查 B）— 已机器可读化

> 全部耦合行（R01-R26）以数据形式登记在 `src/video_agent/core/coupling_registry.py`，
> 每行带强制项（符号可导入/钉死测试存在/门禁已注册 acceptance）；
> `tests/unit/test_coupling_registry.py` 遍历钉死，漏同步/漏登记即红。
> 变更任何耦合行：先改注册表同批提交；prose 降级行必须给出理由。

### 13.8 事故台账

> 完整台账（2222 系列至八轮整改全部事故行）见 `docs/archive/incident-ledger.md`（只增不删）；
> 事故编号引用不变，按编号到归档文件检索。宪法不复述摘要（防双源漂移）。

### 13.9 模型分层原则（速度治理）

- 流程编排类决策（暂停/推进/选工具）是简单决策，优先用轻模型或低思考预算；
- 生成类任务（拆解/提示词编写/自检）才用强模型；
- 深度思考模型的推理时长与指令冲突度正相关：**模型变慢首先怀疑层间冲突，而不是换更大的模型**。

### 13.10 存量债务清单 — 已归台账

> 债务清单（清一条删一条）见 `docs/archive/debt-ledger.md`；清偿动作完成后同批删除条目。

### 13.11 业界基准六模式（C1-C6）

对照 OpenAI Model Spec、Anthropic context engineering、arXiv 2607.14167、arXiv 2603.04445、Electric CRDT peers。每个模式只有一个代码落点，改动必须同步本表与回归测试：

| # | 模式 | 唯一代码落点 | 禁止的捷径 |
|---|------|-------------|-----------|
| C1 | 语言单一事实源：注入句与 PromptGate 读同一份 parse_gate_rules | `executors._prompt_language_rule` + `prompt_gates` 语言闸 | 仲裁条款里写「从其要求」类例外 |
| C2 | 结构化拒因回喂：纠正重试携带闸门拒因原文逐条修复 | `_write_prompt_batch(corrective_reasons=…)` | 只给「不得留空」式笼统纠正 |
| C3 | 轮内 compaction：旧轮对折叠成摘要，最近两轮保留原文 | `core/fc_feedback.py`（惰性反馈压缩 + 旧轮图片剥离） | 每轮全量重发旧轮原文 |
| C4 | 读不触发写：未变更不保存 + 内容级脏检查 | 前端编辑 handler + 保存基线 | blur/查看调度整板 PUT |
| C5 | 模型级联：誊写批快模型先试，零进展/拒收升级推理模型 | `executors._resolve_cascade_fast` + 纠正升级 | 硬换模型无升级保险 |
| C6 | 铁律最小化 + 暂停语义唯一源 = Skill 文本/manifest 声明 | `spec_rules._IRON_RULES_DOC_BODY`；planner 提醒只留执行器失败禁令/总结强展 | 把可校验约束或暂停条款写回铁律/平台提醒 |

**卡片面纪律（C1/C6 延伸）**：draft label ≤12 字短语、提示词正文必须相对分组描述增加增量信息、前端卡片定宽 + 描述 2 行 clamp。

### 13.12 AI 助手方案纪律（反捷径自查，S2 事故设立）

**本节约束对象：在本项目提出修复/改进方案的 AI 助手。**方案产出前必须过以下四关，任一不过即方案作废重拟：

**G1 Skill 只读关**：方案不得包含对 `data/skills/*` 的任何修改（含 manifest 声明、章节文字、写死参数）。Skill 要求与系统行为不符时，修平台层。**禁止以降低 Skill 要求的方式迁就系统缺陷**。（例外：用户显式裁决的清理，如八轮 T16/T17，须记台账。）

**G2 既有机制审计关**：出方案前必须先 grep 代码与台账，回答“这个能力是否已存在”。已存在的机制优先**启用/扩展**，禁止凭空设计平行新机制。

**G3 Prose 禁令关**：方案不得包含“往任何文档/提示词里写一句话让模型配合某个机制”。机制能用代码机械执行就沉代码层（P2）。

**G4 全局化关**：事故修复必须覆盖**同类全部调用路径**，不许只修出事的那条。交付物三件套 = 统一策略 + 带事故编号的钉死回归测试 + 台账登记。方案若只改单一路径，必须书面说明其余路径为何豁免。

**捷径禁令（追加）**：禁止以“改动面小/省事”作为方案排序理由（排序标准只有：归属层正确性 > 复用既有机制 > 改动面）；禁止被用户纠正一次后只修当前点——必须回溯检查同一思维模式是否污染了方案的其他部分。
