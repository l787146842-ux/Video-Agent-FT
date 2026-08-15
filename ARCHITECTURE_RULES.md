# 架构宪法 — AI 协作开发强制约束（v3 · 2026-08-13）

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder / CodeBuddy 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
> 本版为宪法 v3：保留 v2 主干，融合 2026-08-11 原版宪法 §10「指令治理层」（第十三章）。
> 原文件归档：`docs/archive/recovery-sources-20260813/qoder-history/ARCHITECTURE_RULES-pre-damage-20260811.md`。
>
> **治理总纲：按业界最高标准执行，禁止走捷径。** 具体含义：
> 1. **策略即数据（Policy-as-Data）**：所有闸机/安全规则以注册表数据表达，带稳定 `rule_id`、层级归属、外置文案；禁止散落硬编码。
> 2. **单一事实源（Single Source of Truth）**：状态写入归 StateManager、循环归 agent_loop、入口归 Planner、提示词归 `prompts/`、前端类型归 `gen_api_types` 生成物。
> 3. **评测驱动（Evaluation-Driven）**：闸机行为由黄金语料库校准，误杀/漏放计数劣化即测试失败；提示词迁移由快照测试锁语义。
> 4. **deny-overrides 分层合并**：平台硬边界永远优先，Skill 配置只能加强或持平，不能削弱。
> 5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批未提交改动（本仓库已因此丢过整批工作，见 §5）。
> 6. **验收四件套 + 浏览器目测**：`pytest` + `vitest` + `tsc --noEmit` + `gen_api_types --check` 全绿，UI 变更必须浏览器实测截图对照，缺一项不算完成。
> 7. **第十三章（指令治理层）与本总纲同权**：任何规则只有一个家（P1）、约束下沉代码层（P2）、
>    状态即数据（P3）；修改前必须按 10.5 决策树定位归属层，禁止在事故现场就近补条款。

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
- **工具消歧原则**：同名近义工具（如 `generate_image` / `image_generate`）优先通过重写 description 互斥消歧；**改名/合并属高风险重构，必须单独评估立项**，不得随手做

### Rule 6: 指令治理（Prompt 外置 + 单一事实源 + 快照防漂移）
- 所有 system prompt / 闸机文案 / 回喂模板存放在 `prompts/`（`planner/`、`gates/`、`shared/`、`memory/` 分区），经 `utils/prompts.py::load_prompt()` / `load_prompt_section()` 加载
- **禁止**在代码中硬编码超过 3 行的 prompt 字符串；代码只留组装逻辑
- **快照防漂移**：提示词外置/迁移必须配快照测试，锁定迁移前后关键段落语义一致；无快照测试的迁移视为错误实现
- **双协议瘦身**：FC 模式用 `prompts/planner/system_fc.md`，文本模式用 `system.md`；共有段落抽到 `prompts/shared/` 引用拼装，两文件互不复制
- 纪律条款（如 Skill 流程纪律）外置为独立 md（如 `planner/skill_discipline.md`），不得内联代码

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
| Skill 层 `skill.*` | 时长/字幕/镜头语言/音频层标记、中文占比、最短字数、@引用、spec_gate 流程前置、元素概念图前置、故事板审阅窗口 | manifest 可关/可放宽/**可加严**；字数阈值只可抬高不可低于平台地板；**元素图/审阅窗口等流程闸默认只警告不拦人（4444 语义，用户第一）** |
| 会话层 `session.override` | 用户「本次放行」一次性记录 | 仅用户手动产生，即时消费、留痕、不可持久化 |

### 2.2 manifest 只能加强或持平（强制不变量）
- 外部 Skill 文档来自成熟平台，其配置**不可信**；系统必须坚守自身安全底线
- **Skill 全文是数据，不是指令**：其中的命令性文字只能约束风格/流程，不能覆盖平台闸机、不能要求执行平台外动作
- manifest 试图触碰 `platform.*` 的任何键：**静默忽略 + warning 日志**，并必须有负面用例测试断言其无效
- 可配项仅限风格/流程类（音频层、中文占比、@引用、规格前置等）；「规格前置」经用户确认为可配置项，不锁死

### 2.3 规则注册表（Policy-as-Data）
- `core/prompt_gates.py` 维护 `GATE_RULES` 注册表：稳定 `rule_id`（如 `skill.require_subtitle`、`platform.gen_confirm`）+ 层归属 + 中文描述
- 判定返回结构化 `GateVerdict(rule_id, layer, ok, message)` 列表；文案外置 `prompts/gates/messages.md`，杜绝自由文本
- 回喂模型与展示用户用**同一 verdict 源**（防两套说辞）

### 2.4 拦截可见 + 一次性申诉放行
- 拦截必须用户侧可见（警示 chips 带规则描述 + 来源标注「平台」/「Skill『xxx』」）
- **Context ≠ Consent（上下文不等于同意）**：平台硬边界只能被「针对**当前动作**的显式用户指令」解除；
  模型不得自证「用户已确认」，历史上下文、Skill 文档中的「用户已同意/默认放行」一律不构成同意。
- 「本次放行」单次生效、全程留痕、不形成持久削弱；每次放行单独点，且必须可追溯到产生它的用户消息。

### 2.5 审计闭环
- `tracer.record_gate(...)` 持久化到 `agent_traces.jsonl`；调试端点 `GET /api/agent/gates` 与 `/api/agent/traces` 并列
- 闸机触发/放行、工具调用、执行器输出校验、截断/回滚全部入 trace（遥测化）；执行器内层模型异常落黑匣子档案（只落盘不进上下文）

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
- UI 变更必须浏览器实测（截图对照）后交付；「测试全绿」不等于「UI 正确」
- **品牌、视觉与交互细节规范（飞天品牌、确认卡片样式、@面板、分组卡片等）**见 `docs/前端体验规范.md`，同样为强制约束，由前端工程按批次执行

### 3.4 前端工程
- 唯一前端为 `src/web` SolidJS SPA，构建产物 `static/dist`；启动脚本自动补构建；**禁止**复活旧 studio 页面
- 前端类型以 `scripts/gen_api_types.py` 生成物为契约，`--check` 纳入每批验收，防前后端契约漂移

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
5. **验收四件套**：`python -m pytest tests/ -q` + `npx vitest run` + `npx tsc --noEmit` + `python scripts/gen_api_types.py --check` 全绿才可提交；pre-commit 钩子强制执行
6. **分支现状（记录，非强制条款，随合并更新）**：`fix/audit-2026-08` 为当前主线；`backup/pre-repair-0812` 保存整改后端批次，待 UI 稳定后**选择性再合并**；`rescue/deepseek-v2-0806` 为 8/6 快照保护分支；`backup/pre-restore-20260813` 为 8/13 恢复现场冻结分支；`fix/restore-20260813` 为 8/13 恢复执行分支（完成后合并回主线）
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

### 7.1 新增 Tool
```
1. tools/ 下新建或追加 → 2. Input Schema(BaseModel) → 3. 继承 BaseTool
4. get_input_schema()+aexecute() → 5. ToolManager.register() → 6. 单元测试
```
### 7.2 新增 API 路由
```
1. web/routes/xxx.py → 2. APIRouter() → 3. app.py include_router(prefix="/api")
4. 内部走 StateManager/ToolManager/Planner → 5. VideoAgentError 体系 → 6. 集成测试
```
### 7.3 新增 Adapter
```
1. adapters/xxx.py → 2. 继承对应基类 → 3. 实现全部抽象方法
4. AdapterFactory 注册 → 5. data/api_providers.json 配置 → 6. mock 单测
```
### 7.4 修改状态模型
```
1. state/models.py 修改 → 2. 新字段给 default（向后兼容）→ 3. 新类别常量 CAT_XXX
4. 更新 StateManager 辅助方法 → 5. to_frontend_dict() 兼容 → 6. 全量测试
```

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

---

## 十、测试要求

- 新增 Tool→单测；新增路由→集成测试（TestClient）；新增 Adapter→mock 测试；改核心（Planner/StateManager/agent_loop/闸机）→回归测试
- 闸机改动→黄金语料校准测试；提示词迁移→快照测试；双轨改动→双轨一致性测试
```bash
python -m pytest tests/ -q      # 全量
npx vitest run                  # 前端
npx tsc --noEmit                # 类型
python scripts/gen_api_types.py --check  # 契约
```

---

## 十一、文件地图（快速定位）

```
src/video_agent/
├── core/
│   ├── planner.py          ← Agent 唯一入口（Rule1）
│   ├── agent_loop.py       ← 多步循环唯一实现（Rule2，含推理轮时间线事件）
│   ├── fc_tool_runner.py   ← FC 轨执行臂（闸机接入、工具时间线）
│   ├── prompt_gates.py     ← 闸机规则注册表（§2）
│   ├── prompt_builder.py   ← 上下文/纪律条款组装（外置加载）
│   ├── token_budget.py     ← 窗口表/估算/截断
│   └── tracer.py           ← 审计链路（含 record_gate）
├── web/
│   ├── app.py              ← FastAPI 主应用 + 路由注册 + 静态缓存策略
│   ├── chat_service.py     ← 聊天业务（SSE worker）
│   ├── sse.py              ← SSE 推送（断连转后台，刷新不中断 Agent）
│   ├── task_manager.py     ← 生成任务 + 生成日志（成败均记录）
│   ├── routes/             ← 薄层端点（含 runtime_settings 热配置）
│   └── skill_docs.py       ← Skill 解析（manifest 解析入口）
├── state/
│   ├── manager.py          ← 唯一写入点（Rule3）
│   ├── models.py           ← Pydantic 模型 + CAT_ 常量
│   └── storyboard_ops.py   ← 故事板领域逻辑唯一实现（Rule2）
├── adapters/  tools/  config.py  exceptions.py  utils/
src/web/                    ← SolidJS SPA 唯一前端（§3）
prompts/                    ← 指令治理外置资产（Rule6）
tests/fixtures/             ← 技能夹具 + gate_corpus 黄金语料
```

---

## 十二、违规检查清单（代码审查用）

完成任何修改后，逐项确认：

- [ ] 没有修改画布项目的任何文件（Rule 7）
- [ ] 没有绕过 Planner / StateManager / Adapter / Tool 体系（Rule 1-5）
- [ ] 没有硬编码 prompt >3 行；提示词迁移带快照测试（Rule 6）
- [ ] 没有 manifest 削弱平台硬边界；触碰项有负面用例（§2.2）
- [ ] 工具已声明 risk 分级；high 级工具带平台闸机与确认（§2.7）
- [ ] Skill 保存/删除后执行器注册表已同步；执行器失败未绕过回喂（§2.8）
- [ ] 闸机改动带黄金语料校准；连续拦截有升级指引（§2.6）
- [ ] UI 改动符合 §3 交互规范表，且浏览器实测截图对照
- [ ] 没有 box-shadow/发光出现在确认卡片；品牌仍为「飞天」
- [ ] 没有裸 restore/checkout -- .；本批已 commit；未跟踪文件已核对（§5）
- [ ] 没有硬编码路径/数字/状态 Key；没有方法内 import；没有同名类覆盖
- [ ] 没有 `datetime.utcnow()` / `time.sleep()` / `print()`
- [ ] 验收四件套全绿：pytest + vitest + tsc + gen_api_types --check
- [ ] 修改前已按第十三章 10.5 决策树定位归属层；没有在事故现场就近补条款（P1/P2）
- [ ] 没有在 Skill 文件里改系统层缺口；没有用 prose 教模型配合既有机制（G1/G3）

---

## 十三、指令治理层（融合 2026-08-11 原版宪法 §10）

> **本节背景**：2222/3333/4444/5555/6666/7777/8888 系列事故的复盘显示同一模式——
> 每次出事就在“出事的那一层”补一条条款，同一条规则最终散落在 5+ 个层且各自表述，
> 思考模型把大量推理时间花在调解层间冲突上，补丁越多分歧越大。
> **本节目标：任何规则只有一个家；任何修复只动规则的家，不动症状现场。**
> 对齐业界成熟编码 Agent（Claude Code / Codex / Qoder 类）的第一性原理：
> 指令单一来源、约束下沉工具层、状态即数据、模型分层。

### 13.1 三大宪法原则

**P1 单一事实源（Single Source of Truth）**
每条规则只有一个**表述源**（归属见 13.3）。其他层需要提及该规则时，只能引用（如“按 Skill『何时暂停』执行”），**禁止复述条款内容**。复述即漂移，漂移即打架。一条规则允许同时存在“引导（prose 告诉模型怎么写）+ 校验（代码裁定写没写对）”两个角色，但表述源唯一、校验实现唯一；引导与校验冲突时，以代码校验的客观结果为准并修表述。

**P2 约束下沉（Code over Prose）**
能被代码机械校验的规则，一律实现为工具/执行器层校验（拒收+报错回喂/自动修正），**禁止**用 prose（“严禁/必须”）说服模型。每一条“严禁”都是没能在工具层解决的债务；新增 prose 禁令前必须先回答：“这条为什么不能被代码校验？”
**校验作用域**：代码校验只裁定**模型产出的格式与客观状态**（缺字段/超时长/越阶段），永不拦截**用户意志**——用户指令永远优先，闸机对用户越流程的操作只警告不拦人；拒收后的重试提示词也不得夹带新规则。

**P3 状态即数据（State as Data）**
注入给模型的状态/工具结果必须是纯客观数据。引导语（该做什么）独立且极短，**禁止**把说教嵌入数据体（如状态 JSON 内部写“请先做 X”）。

### 13.2 指令层全量清单（共 12 层）

修改任何模型可见文本前，先在此表定位它属于哪一层：

| # | 层 | 位置 | 注入时机 | 唯一职责 | 禁止承载 |
|---|----|------|---------|---------|---------|
| 1 | 平台协议 | `prompts/planner/system.md`（FC 用 `system_fc.md`） | 主模型每轮 | 动作格式/暂停通道/输出纪律/工具使用法 | 业务领域规则（拆解粒度/提示词质量等） |
| 2 | 文本协议 | `prompts/planner/text_actions.md` | 仅非 FC 通道 | studio-actions 全量动作定义 | 流程/业务规则 |
| 3 | Skill 文档 | `data/skills/*.md` | planner 章节/执行器内章节 | 该 Skill 的流程步骤、暂停点、产出规范；`skill_manifest` 声明块（闸机/流程开关，S1） | 模型能力参数（时长/分辨率数值）；平台通用层硬编码其专属流程 |
| 4 | 执行铁律文档 | 项目内「执行铁律.md」（`spec_rules` 模板） | Skill 激活时全文注入（主模型 + 执行器） | 项目级可编辑生产契约 | 平台协议、流程步骤 |
| 5 | 制片规格文档 | 项目内规格文档（Final_Video_Spec.md 等） | 执行器显式注入/按需 read | 本项目参数事实（画幅/分辨率/渠道/时长） | 任何规则性表述 |
| 6 | 执行器提示词 | `skill_runtime/executors.py`（_TASK/_BOUNDARY/自检词） | 执行器独立调用 | 单一任务的输出格式与边界 | 跨阶段流程规则 |
| 7 | 闸机 | `core/prompt_gates.py` + `core/guard_pipeline.py` | 工具裁剪/警告/回喂 | 客观状态校验与阶段门禁 | prose 说服（闸机只裁定，不说教） |
| 8 | 回喂话术 | `agent_loop.py`/`planner.py`/`fc_tool_runner.py`（fc_feedback/阶段提醒/工具结果回话等） | 轮间 | 客观回报上轮结果 + 单句下一步；允许当轮短期指令 | 持久性规则条款 |
| 9 | 系统兜底卡 | agent_loop/planner/chat_service（规格暂停注入/出口引导卡/总结兜底） | 轮末 | 客观状态 → 确定性交互，不依赖模型自觉 | 无（代码行为，非指令） |
| 10 | Tool description | `tools/*.py` 的 description 字段 | FC 通道每轮随 schema | 该工具做什么、参数含义 | 跨工具流程规则 |
| 11 | 状态上下文 | `state/context_builder.py` | 每轮 | 客观工作台数据（骨架/清单/预览/analysis/流程事件账本） | 说教性引导语 |
| 12 | 记忆与解除引导 | `memory/` 注入；`chat_service._consume_pending_confirmation` / `_consume_spec_wizard` | 按需 | 项目历史偏好；暂停窗口的回应语义 | 新规则 |

> **层 8 特别条款（888 事故）**：代码里硬编码的运行时回话模板（如 fc_feedback、format_tool_results 首句）是每轮强制喂给模型的动态指令，属于受治理对象：① 措辞不得自相矛盾；② 修改此类模板必须走与文件规则相同的登记+审查流程，并在 13.8 台账记录；③ 季度“严禁审计”的 grep 范围必须包含这些模板文件，同时人工复查模板是否自相矛盾。

### 13.3 规则归属表（Single Source of Truth 落地）

| 规则类型 | 唯一定义层 | 禁止出现在 |
|---------|-----------|-----------|
| 平台对话协议（动作格式/暂停通道/输出纪律） | 层 1 system.md / system_fc.md | Skill、铁律、执行器 |
| 项目级生产契约（拆解粒度/回复精简） | 层 4 铁律文档 | system.md 硬编码、执行器常量 |
| 流程步骤与暂停点（先做什么/何时暂停） | 层 3 Skill 的 `<planner>` 与「何时暂停」 | system.md、runtime 块条款、回喂话术 |
| 单一执行器的输出格式与边界 | 层 3 Skill 对应章节是规范唯一表述源；层 6 执行器任务词只承载任务目标与格式锚点 | system.md |
| 模型能力参数（分辨率/时长/渠道） | 层 5 制片规格（运行时动态注入） | Skill 硬编码数值、执行器写死数值 |
| 可机械校验的约束（字段/格式/时长上限/阶段边界） | 层 7/9 代码校验（拒收或修正） | 任何 prose 层重复表述 |
| 通用提示词规范（no subtitles 等） | 层 3 Skill 的提示词章节 | system.md |
| Skill 的平台行为开关（结构闸启停/阶段裁剪/渠道块） | 层 3 Skill 的 `skill_manifest` 声明块（引擎默认最小闸：业务闸全关） | 平台通用层硬编码（prompt_gates/agent_loop/fc_tool_runner/prompt_builder/planner） |
| 规格向导启停 | 客观流程特征检测（`registry.spec_wizard_active`）；manifest `spec_wizard: false` 显式逃生门 | 纯声明制（有规格流程未声明的 Skill 向导漏弹） |

**冲突裁决顺序（模型可见优先级，与铁律一致）**：用户最新指令 > 铁律文档 + 制片规格 > Skill > 平台协议默认。代码校验层（闸机/执行器拒收）不参与裁决——它是客观事实，只对结果裁定并回报。

### 13.4 症状归位表（不走捷径的核心）

修复任何模型行为问题前，先在下表找到症状对应的正确归位层；**禁止在“捷径层”动手**——捷径层都是历史事故验证过的错误路径。

| 症状 | 正确归位层 | 禁止的捷径（历史事故） |
|------|-----------|---------------------|
| 模型该暂停时没暂停 | ①层 9 客观状态兜底注入；②层 3 Skill「何时暂停」加暂停点 | 在多层同时加“必须暂停”（5555） |
| 模型输出缺字段/格式错 | 层 6 执行器拒收+重试+格式锚点 | 只在 prose 加“必须携带 X 字段”（8888） |
| 模型虚报完成 | 层 7 客观状态核验 + 只警告不拦人 | 硬拦截没收暂停（4444） |
| 产出数量失控 | 铁律+Skill+执行器任务词三处**同步**写比例约束，自检限轮数 | 单向穷举表述与克制条款并存（8888） |
| 工具成果用户看不见（总结/卡片） | 层 9 系统兜底拼入正文/即时 SSE 事件 | 只加“必须展示”prose（2222/3333） |
| 参数与生成能力不符 | 层 5 规格收集 + 执行器运行时注入 | Skill/执行器硬编码数值 |
| 模型继续推进了不该推进的阶段 | 层 7 工具裁剪 + 层 9 兜底卡 | 在回喂话术里加长段告诫（5555） |
| Skill 流程与平台行为不符 | 系统层：平台闸启用条件 + 执行器冲突裁决注入 + 适配层填参 | 修改 Skill 文件或其 manifest 声明（S2） |
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
  └─ Q5 按 13.7 同步点清单核验；在 13.8 台账记一行
```

**捷径禁令（违者视为错误实现）**：禁止在事故现场就近补条款而不查归属层；禁止同一条规则在两层以上新增表述；禁止新增 prose 禁令前不回答“为什么不能被代码校验”；禁止修改铁律模板/Skill/协议时不同步检查另两处的同义条款；禁止用“模型不听话”作为结论——先查是否层间冲突；禁止给确定性任务出题给模型。

**确定性三问判别法（每次决定“某个细节交给模型还是系统”前必问）**：
1. 正确答案能不能从已有数据里算出来？（如 @引用 ← sceneRefs、时长 ← 分组字段、渠道/分辨率 ← 规格）
2. 对错能不能被机器一眼判定？（有/没有、数字对不对）
3. 有没有创作空间？（多个合理答案 = 创作题）

判定：**1+2 都是 → 收归系统自动做**；只有 2 是 → 模型写、系统验收（验收标准跟 skill_manifest 声明走，不写死）；3 是 → 留给模型，人审阅，机器闸不得卡创作质量。同类验收声明必须落在 skill_manifest（如 require_at_ref），未声明的 Skill 一律放行（S1 同源）。

### 13.6 指令体量预算（防反弹的量化红线）

| 项 | 预算 | 超限处理 |
|----|------|---------|
| system.md / system_fc.md | ≤ 7KB（纯协议） | 继续压缩或拆分按需注入 |
| 全链路“严禁/不得/禁止”总数 | ≤ 8 处 | 逐条审计（13.6 命令），可机械校验者下沉；**CI 门禁 `scripts/check_prompt_budget.py`（B1 落地：md 全文 + 代码字符串字面量，排除 docstring/注释/正则白名单）** |
| 单执行器 system+user 提示词 | ≤ 25K 字符（含剧本/状态注入） | 缩减注入而非删任务词 |
| 回喂话术单条 | ≤ 3 句 | 超出说明在回喂里写规则，迁回归属层 |
| 同一规则的定义处数量 | 恒等于 1 | 立即清理分身 |

每季度（或每 3 个事故后）做一次“严禁审计”：`grep -rn "严禁\|不得" prompts/ src/video_agent/core/ src/video_agent/skill_runtime/ data/skills/`，逐条回答“能否下沉/是否重复”，结果记入 13.8 台账。

### 13.7 已知耦合点清单（改 A 必须同步检查 B）

| 修改点 | 必须同步检查 |
|--------|------------|
| Skill 章节 tag 改名/拆分执行器 | `SECTION_TAG_STAGES` 映射 + system.md/system_fc.md 动作清单 + 存量 Skill 旧标签 |
| 铁律模板（spec_rules._IRON_RULES_DOC_BODY） | 只影响新建项目；老项目需手动同步或删文档重建；闸机读取逻辑 |
| 规格文档改名/字段 | `prompt_gates._SPEC_NAME_HINTS` + provider_prefs 解析 + 执行器参数回退链 |
| 执行器输出格式 | action_executor 兜底链 + 自检去重键（去重依赖标题有效，8888 事故） |
| 新增暂停点 | Skill「何时暂停」+ 层 9 兜底注入（Skill 管引导，兜底管强制） |
| 新增 SSE 事件 | 工具层 emit → planner 白名单 → chat_service 透传 → 前端 handler（四段缺一即静默失效） |
| doc_written 即显（B0 恢复） | fc_tool_runner/agent_loop 发射（按名称去重）→ planner 白名单 → chat_service 透传 → 前端 docWritten + done 双通道去重（前端 renderedDocCards） |
| 模型策略表角色（B8） | core/model_policy.resolve_role/thinking_for；消费点 chat_service._resolve_summary_adapter、executors._resolve_cascade_fast/_executor_thinking、planner._make_summarize_fn；写入点 runtime_settings PUT/GET；UI 全局设置页 |
| 快照/分支（B11） | routes/snapshots.py + conversations 创建 + _meta.branched_from + 前端 RightPanel 分支按钮 |
| 窗口表元数据（B6/F52） | api_providers.json chat_models_meta.context_window → token_budget.context_window_for_model(provider_id) → planner 传递 chat_provider |
| 新增 FC 工具 | tool description（层 10）+ 阶段裁剪集 + 测试 |
| skill_manifest 白名单键 | 消费点：prompt_gates.parse_gate_rules/validate_prompt_write、agent_loop、fc_tool_runner、planner._compute_excluded_tools、prompt_builder、action_executor._spec_gate_ok；pause 节另由 guard.skill_requires_stage_pause 与 lint 消费；同步 test_skill_manifest.py 快照登记；**spec_wizard 例外：统一走 registry.spec_wizard_active；script_required 同模式统一走 registry.script_required_active（814H9）** |

### 13.8 事故台账（规则漂移的活证据，只增不删）

| 事故 | 症状 | 根因层 | 修复落点 |
|------|------|--------|---------|
| 2222/3333 | 总结不可见 | 回喂链路丢 payload | 工具结果带 detail + 层 9 状态兜底 |
| 4444 | 硬拦截误伤合法暂停 | 闸机越权 | 改“只警告不拦人”，裁决权归用户 |
| 5555 | 规格写完不暂停直冲拆解 | 层 9 缺失 + 回喂推波 | 规格暂停兜底注入（双轨） |
| 6666 | 文档卡片延迟渲染 | SSE 透传白名单断链 | 四段链路补齐 |
| 7777 | 提示词覆盖/超时 | 批量单次全量输出 | 分批断点续写 |
| 8888 | 默认标题×20、元素爆炸、253s | 执行器验收缺失 + 单向穷举 + 层间冲突 | 拒收重试 + 克制条款 + 本节 |
| 9999 | 总结正文两遍；规格参数「待确认」放行；参数栏无分辨率；拆解零产出 | 层 9 判重/兜底/补印/预算 | 归一化判重 + 规格参数向导兜底 + 分辨率补印 + 拆解预算 16384/重试翻倍 |
| 1111 | 总结后不停顿直冲规格；模型自造向导选项无法落盘 | 层 3 无暂停点 + 层 9 无总结闸 | Skill 步骤1 加暂停点 + 双轨总结闸 + merge_spec_param_wizard 选项标准化 |
| 6666（二轮） | 「确认总结」暂停多余；向导缺渠道；规格先于交互写入 | 层 9 闸设置与预期不符；向导维度不全 | 总结闸改规格收集闸；向导恒定含渠道组；渠道按供应商模型客观落盘；spec_collected 标记防重复 |
| 99 | 规格写完后正文又拼剧本总结；收集向导重复弹出 | 层 9 总结兜底无阶段边界；spec_collected 双重消费 | 总结兜底限解析阶段注入；系统注入审阅卡后同批跳过 merge |
| 9999（二轮） | 1197 字微剧本时长候选到 7 分钟；画幅候选自造电影规格（无 16:9）；关键元素拆解后暂停卡混回规格向导 | 层 6 上限公式用旁白速率（3 字/秒）；画幅确定性题出题给模型；层 9 向导渲染不看规格文档客观状态、只靠一次性标记 | 剧情速率上限（600 字/分钟）+ 超限确定性梯度兜底；画幅标准白名单归一；向导只渲染规格文档未定稿维度（客观闸门，双轨同入口） |
| 8888（二轮） | 切换项目旧单例全量回写抹掉任务数据；拆解阶段被接管换回「确认规格」卡且规格卡不弹；收集卡开发者腔/总结「见上」；2 分钟≈120 秒重复候选；角标泛化「关键元素」；下一步黑盒 | 层 9 切换保存用内存全量回写（任务级隔离后单例过期）；拒收接管缺客观闸门；层 9/8 文案开发者视角；层 6 收卷不按值去重；角标无校验 | 切换/新建改 flush + save 版本账本闸（磁盘账本新于已知号即放弃写入）；spec_doc_finalized 客观闸门双轨；机械落盘补发 docCard；收集卡 {summary} 模板；时长按值去重归一；角标 desc 锚点归一；审阅卡/阶段卡选项客观具体 |
| 888 | 推理模型万字思考；截断残品当成品；@引用缺失；删图复活；只拆 4 个却被删了重拆 | 层 8 模板自相矛盾 + 预算/截断/确定性任务/版本双账本 | 回话模板纳入治理；工具结果回执+对账；流程事件账本；批次提额/缩批/撞线扩额；@引用按 sceneRefs 补写；版本账本统一；黑匣子存档 |
| S1 | 切换 Skill 指令打架 | 违反 P1：测试 Skill 规则复述进五层 | skill_manifest 声明块（层 3）：业务闸默认全关，流程闸/裁剪/渠道块按声明启停，暂停卡文案中立化，16 存量 Skill 迁移 + 快照回归 |
| S2 | AI 助手方案连续走捷径 | 违 P1/P2/13.5 | 设立 13.12 方案纪律；配套修复（executor_thinking_level 降档、截断保险全局化、边界自适应、规格覆盖注入、向导客观检测） |
| 2026-08-13 恢复 | Qoder 损坏回退 8/6，整套执行器运行时丢失 | 未提交改动 + 救火回滚 | 现场冻结 + Qoder/QoderCN 历史快照归档恢复 + 宪法 v3 融合（本行即台账续记） |
| 814R1 | 双协议瘦身/include 加载/feedback 外置/text_protocol 全部断线（8/14 深度审核发现，快照取证证实为 8/12 回退丢失接线） | 层 1/层 8 接线丢失，md 幸存但代码无人读 | 从 Qoder 快照恢复：{{include}} 展开 + load_prompt_section + fc_mode 双协议选择 + 回喂模板外置 + 窗口感知压缩 + text_protocol 闭环（test_814_prompt_protocol_restore 钉死） |
| 814R2 | §2.0 统一闸机管线空心化：prompt_write_verdict 无调用方，双轨各自内联组装判定；闸机文案硬编码；无闸机审计 | 接线丢失 + 语义漂移风险（死代码版硬拦与活路径只警告并存） | guard_pipeline.evaluate_prompt_write 成双轨唯一组合实现（4444 只警告不拦人对齐）；messages.md 文案外置（现行为准）；GATE_RULES 注册表 + tracer.record_gate + /api/agent/gates 审计闭环（test_814_gate_pipeline_restore 钉死） |
| 814R3 | flow_gates.py（Skill 声明式流程检查点）整体无调用；会话层 gate_overrides 消费链断线 | 8/12 回退丢失 planner/agent_loop/fc_tool_runner 三处接线 | 从 8-04 快照恢复三处接线（FC 拦截+文本剔除+强制补发暂停）；恢复 interaction.gate_overrides 单次消费（按钮化输入端待 814 批次7）；正则意图识别作兜底；用户坚持 scope=all 旁路硬门禁（test_flow_gates 9+2 钉死） |
| 814R4 | _prepend_script_summary 有定义有测试无生产调用（1111 台账「总结强制入正文」断线）；重复 pop；开场编排双份复制；session_compact 无人消费 | 回退丢失接线 + 重构残留 | FC 轨 llm_call 与文本轨暂停补拼双接线；_prepare_chat_opening 单一实现；会话级 compaction 恢复（阈值配置默认关，摘要缓存于 interaction）（test_814_summary_and_chatservice 钉死） |
| 814F3 | skill_baseline.md 与 skill_discipline.md 九条同构但语义相反并存（P1 隐患）；settings.skill_runtime 开关无消费点；workflows 引擎已批准下线但 4 处残留引用 | 恢复残留 + 死配置 + 债务未落地 | baseline 归档 docs/archive（禁重接线）；skill_runtime auto/executors/legacy 三态落地 prompt_builder；workflows/ + routes/workflow + core/agent + cli.py + workflow_step 工具整体移出主线（备份分支可捞，实现体仍在 backup 分支）；README/配置说明/契约同步 |
| 814F6 | 阶段完成卡显示正文（与前端体验规范打架）；左栏页签文字竖排；窄视口顶栏重叠/右栏不可达；ConfirmActions 硬编码中文 | 实现与规范漂移 + 样式缺陷 | 阶段卡只留标题+徽标，确认文案转正文气泡（判重防双显），操作明细归时间线；页签 white-space:nowrap；工作台 min-width 940 + 横向滚动兜底；i18n 补齐 rp.confirm.*；浏览器实测截图验证（verify-*.png） |
| 814F7 | 会话层「本次放行」无输入端（§2.4 只靠正则猜意图）；warnings 不落消息；system prompt 组装无可观测性 | 设计未闭环 | ChatRequest.gate_overrides 字段 + interaction 登记 + Planner 单次消费；拦截警告附「本次放行」按钮（gateWarningTargetIdx 挂载，e2e 钉死）；finishStream 落 warnings；prompt_builder 组装超阈预警（60000 字符） |
| 814E1 | 执行器家族固定 7 个白名单，自定义章节 Skill 只能走全文兜底 | 架构弹性不足 | skill_section_run 通用章节执行器（stage key/flova tag/标题关键字/任意 <tag> 四级解析）注册为平台级工具 |
| 814E2 | Skill <planner> 依赖关系声明无人消费，执行顺序全靠模型自觉 | P2 违例（可计算调度交给模型） | skill_runtime/dag.py 解析步骤+依赖→拓扑并行批次；skill_pipeline_plan 客观返回下一可执行批次 |
| 814E3 | 风格偏好无跨会话连续性 | 记忆系统未分层 | summarize.md 约定「风格偏好：」前缀抽取；执行器 system prompt 注入项目风格记忆块（按项目隔离） |
| 814E5 | 黄金语料无校准测试（宪法 §2.6 宣称存在但实际缺失）；语料期望停在前 S1 语义 | 评测驱动空心化 | scripts/run_eval_pipeline.py（语料回归+管线可解析性，退出码入 CI Job5）；语料按 S1 语义重校准（6 条）；test_gate_corpus_calibration 钉死 |
| 814E6 | 多用户无归属链路；json 后端并发安全弱 | 扩展基础缺失 | state_backend 默认 sqlite（STATE_BACKEND=json 可回退，测试基线钉 json）；ChatRequest.user_id → trace 审计；完整鉴权另行立项 |
| 814F3b | 核查发现：CLI 下线后 models_legacy re-export 与 _set_path_pydantic 仍残留（兼容层计划 §4/§5 未随动）；前端 WorkflowPhaseInfo 死类型；.env.example 缺新配置项 | 连锁债务 | models_legacy 降为 models.py 私有导入（仅兼容旧 state.json）；state/__init__ 停止对外 re-export legacy 枚举；_set_path_pydantic 删除、_set_path_dict 非 dict 显式 StateError；死类型删除；.env.example 补 STATE_BACKEND/HISTORY_COMPACT_THRESHOLD；兼容层计划文档标已执行 |
| 814G | 9999 实测 12 条体验回退：阶段卡不可展开；时间线 live/持久化不同构（无走秒/顺序反/运行中无展开）；规格拒收先报错后交互；向导选项天书；规格未定稿就拆结构；写规格无卡片无交代；慢（历史膨胀+压缩默认关+主模型满档思考）；提示词不流式亮卡；深度思考窗不可滚；正文过少 | 8/13 重建丢的体验层接线 + 814F6 照过期规范改 + 814R4 压缩默认关 | G1 阶段卡恢复可展开（规范同步修订）；G2 规划条目入 trace+子挂父后+走秒+前奏 live 事件；G3 规格拒收静默（只喂模型，用户只看向导卡）；G4 选项 display 去维度名+说明差异化白话；G5 FlowGateSet.ensure_spec_gate 执行侧强制（拦 agent 不拦用户，override/坚持旁路）；G6 写文档正文交代系统保证；G7 compaction 默认 12+反馈压缩 0.35+主模型思考默认 low；G8 bind_progress_emitter 循环级双轨绑定；G9 思考窗 overflow-y:auto+底部跟随；G10 输出纪律改结构化短交代 |
| 814Gb | 核查发现两处半吊子：文本轨 executor._spec_gate_ok 仍向用户追加 SPEC_GATE_ERROR ⚠（与 G3 静默语义打架）；ensure_spec_gate 只认 wizard 不认 manifest spec_gate 声明（两种声明风格强制不对齐） | 双轨语义漂移 | _spec_gate_ok 改只记日志（用户侧静默，恒 True 不硬拦）；ensure_spec_gate 条件扩为 wizard 客观启用 OR manifest spec_gate；3 个旧 warn 语义测试更新为静默断言 |
| 814H7 | 推理档位不可选：全局 low 一刀切（814G7）既压主模型质量又不尊重端点原生；用户要求 Codex 式按会话选档 | 档位治理缺 UI 层 | 对话栏模型胶囊改两节下拉（模型+推理等级 高/中/低/默认，默认=原生不下发字段，localStorage 持久化，随 ChatRequest.thinking_level 透传主模型）；全局设置页新增「推理档位」卡（执行器机械调用/辅助摘要两档，runtime_settings 热生效）；主模型全局默认回空（原生）；适配器 400 优雅降级（端点不认 reasoning_effort 自动去字段重试，流式/非流式双路径）；浏览器实测两节下拉与设置卡通过 |
| 814H8 | 前端路由硬敲/刷新（如 /global-settings）404：服务端只把 index.html 绑死在 /、/canvas、/settings，无 SPA fallback | 部署层缺兜底 | app.py 末尾加 catch-all（注册于全部 API 路由与静态 mount 之后）：未识别非 /api GET 路径一律返回 index.html；/api 排除保持 JSON 404；test_spa_fallback 四条集成测试钉死 |
| 814H9 | 1111 实测：剧本缺失是客观事实却出题给模型——27.8s 规划轮"发现"没剧本+必错的 read_uploaded_doc+空输出重试；无剧本仍被引导进下游流程 | 违 13.5 确定性三问（可算/可判/无创作空间却交模型）+ 层 9 缺原料闸 | registry.script_required_active（manifest 优先+客观特征，同 spec_wizard 模式）；prompt_gates 剧本闸助手（script_present/豁免意图/短路准入/提醒卡文案外置 messages.md）；planner 编排：S7 零思考直出提醒卡（推进意图且非提问）、「我去上传」秒回等待回执、提问落回 LLM+轮末强制提醒卡（反复提醒）、豁免记账 script_waived；FlowGateSet.ensure_script_gate 执行侧拦越阶结构操作（双轨同条件，不拦用户，override/坚持旁路）；GATE_RULES 注册 skill.script_required + record_gate 审计；test_814_script_gate 八条钉死 |
| B0-B12 整改 | 2026-08-15 全面审核暴露的全部问题（P0 接线四件、提示词预算违约与分身漂移、交互体验漂移、前端双轨资产、测试桩污染、臃肿七型）+ 用户裁决（模型能力参数唯一权威源=全局设置）+ 五新功能 | 补丁沉积 + 双轨复制 + 8/13 回退接线未恢复 + 台账宣称≠代码事实 | 一次性整改（19 commits，docs/修复改进计划书-2026-08-15.md 附录记录批次→commit→验收）：P0 接线四件（doc_written 四段链/轮间注入/FC 警告外发/fallback 载荷）；提示词治理（system.md 14.3KB→774B、模型可见严禁 45→0、预算 CI 门禁）；交互整改（阶段卡可展开默认展开、闸机 chips 结构化、toast 收敛、真实性六项）；前端一致性（i18n 全量、Tailwind 摘除、api-settings 入 SPA 退役 iframe）；流程与 Skill（无技能路径、Skill 暂停点运行时消费、三本账收敛、测试桩迁 fixtures、dag 声明化）；速度（compaction 预热、请求体瘦身）；工程卫生（死代码 8 文件、归档出库、数据 TTL、窗口表元数据化、记忆分桶）；模型参数治理（注入优先级草稿>全局设置、Skill lint、迁移脚本）；模型分层策略表；视频批量队列/断点续跑/时间线回画布；成本看板；对话分支/快照 |
| B13（登记未清） | 存量 38 处 `except Exception: pass` 静默站点；executors/prompt_gates/chat_service 大文件拆分；OTLP 可选导出；事故编号测试命名归档（保留编号=§13.5 溯源约定，重命名反而破坏溯源，故不动） | 整改批次内风险评估后延后（改动面大收益边际） | ① `grep -rn "except Exception:" src/video_agent | grep -A1 pass` 逐条 logger 化；② 拆分按新增「文件行数红线」机制立项；③ OTLP env 导出按 B10 设计补齐；④ 命名归档以本台账行清偿 |

### 13.9 模型分层原则（速度治理）

- 流程编排类决策（暂停/推进/选工具）是简单决策，优先用轻模型或低思考预算；
- 生成类任务（拆解/提示词编写/自检）才用强模型；
- 深度思考模型的推理时长与指令冲突度正相关：**模型变慢首先怀疑层间冲突，而不是换更大的模型**。

### 13.10 存量债务清单（清一条删一条）

已清偿（保留记录供审计）：D1 system.md 内嵌铁律（已归位）、D2 铁律未全文注入（已注入）、D3 runtime 块 5 条款重复（已压至 3 条）、D5 执行器任务词复述章节（已只留目标+锚点）、D6 工具描述带流程暗示（已纯功能化）、D7 system.md 超预算（已达标）、阶段边界 prose（已下沉代码校验）、S1 通用层被单一 Skill 污染（已 skill_manifest 清偿）、814 批次：双协议/统一闸机/flow_gates/总结接线/compaction 恢复（R1-R4），baseline 归档/skill_runtime 落地/workflows 移除（F3）。

未清偿：

| 编号 | 债务 | 违反条款 | 清偿动作 |
|------|------|---------|---------|
| D4 | 全链路“严禁/不得”数量偏多 | P2 | 逐条审计（13.6 命令），可机械校验者继续下沉 |
| D8 | 老项目铁律文档无“体量相称/宁缺毋滥”条款 | 层 4 | 用户手动同步或删文档重建 |

### 13.11 业界基准六模式（C1-C6）

对照 OpenAI Model Spec（指令层级由平台执行、模型不仲裁）、Anthropic context engineering（compaction/tool-result clearing）、arXiv 2607.14167（结构化拒因回喂）、arXiv 2603.04445（快模型级联）、Electric CRDT peers（读不触发写）。每个模式只有一个代码落点，改动必须同步本表与回归测试：

| # | 模式 | 唯一代码落点 | 禁止的捷径 |
|---|------|-------------|-----------|
| C1 | 语言单一事实源：注入句与 PromptGate 读同一份 parse_gate_rules | `executors._prompt_language_rule` + `prompt_gates` 语言闸 | 仲裁条款里写「从其要求」类例外 |
| C2 | 结构化拒因回喂：纠正重试携带闸门拒因原文逐条修复 | `_write_prompt_batch(corrective_reasons=…)` | 只给「不得留空」式笼统纠正 |
| C3 | 轮内 compaction：旧轮对折叠成摘要，最近两轮保留原文 | fc_tool_runner 惰性反馈压缩 + 旧轮图片剥离（planner 接线；原「agent_loop 历史压缩」落点为死代码，B6 已删） | 每轮全量重发旧轮原文 |
| C4 | 读不触发写：未变更不保存 + 内容级脏检查 | 前端编辑 handler + 保存基线 | blur/查看调度整板 PUT |
| C5 | 模型级联：誊写批快模型先试，零进展/拒收升级推理模型 | `executors._resolve_cascade_fast` + 纠正升级 | 硬换模型无升级保险 |
| C6 | 铁律最小化 + 暂停语义唯一源 = Skill 文本 | `spec_rules._IRON_RULES_DOC_BODY`；planner 提醒只留执行器失败禁令/总结强展 | 把可校验约束或暂停条款写回铁律/平台提醒 |

**卡片面纪律（C1/C6 延伸）**：draft label ≤12 字短语、提示词正文必须相对分组描述增加增量信息、前端卡片定宽 + 描述 2 行 clamp。

### 13.12 AI 助手方案纪律（反捷径自查，S2 事故设立）

**本节约束对象：在本项目提出修复/改进方案的 AI 助手。**方案产出前必须过以下四关，任一不过即方案作废重拟：

**G1 Skill 只读关**：方案不得包含对 `data/skills/*` 的任何修改（含 manifest 声明、章节文字、写死参数）。Skill 要求与系统行为不符时，修平台层。**禁止以降低 Skill 要求的方式迁就系统缺陷**。

**G2 既有机制审计关**：出方案前必须先 grep 代码与 13.8 台账，回答“这个能力是否已存在”。已存在的机制优先**启用/扩展**，禁止凭空设计平行新机制；禁止把方案说成“需要在 N 个文件新增内容”而实际只需改一处启用条件。

**G3 Prose 禁令关**：方案不得包含“往任何文档/提示词里写一句话让模型配合某个机制”。机制能用代码机械执行就沉代码层（P2）；优先级链（用户指令 > 铁律+制片规格 > Skill）已由系统执行，不得要求通过在低优先级层加 prose 来“提醒”模型。

**G4 全局化关**：事故修复必须覆盖**同类全部调用路径**，不许只修出事的那条。交付物三件套 = 统一策略 + 带事故编号的钉死回归测试 + 13.8 台账登记。方案若只改单一路径，必须书面说明其余路径为何豁免。

**捷径禁令（追加，违者视为错误实现）**：禁止以“改动面小/省事”作为方案排序理由（排序标准只有：归属层正确性 > 复用既有机制 > 改动面）；禁止被用户纠正一次后只修当前点——必须回溯检查同一思维模式是否污染了方案的其他部分。
