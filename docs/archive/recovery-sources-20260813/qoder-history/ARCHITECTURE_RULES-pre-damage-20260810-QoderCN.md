# 架构铁律 — AI 协作开发强制约束

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
> **第一至八节管代码结构；第十节「指令治理」管模型行为规则的存放与修改——任何涉及提示词/闸机/Skill/铁律/规格/执行器的改动，必须先读第十节再动手。**

---

## 一、不可违反的核心规则

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` 或 `Planner.handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: 多步循环唯一实现
- `core/agent_loop.py` 中的 `run_agent_loop()` 是多步循环的**唯一实现**（web/agent_loop.py 兼容壳已于 2026-08 修复批次移除）
- Planner 非流式路径委托给它，不得在其他地方复制循环逻辑
- `MAX_STEPS` 从 `config.py settings.max_steps` 读取
- **层级例外（已收敛）**：`web/action_executor.py`（StudioActionExecutor）因依赖 web 层生成管线暂留 web 层；core.planner 已通过构造注入消除顶层依赖（`executor_factory` / `skill_docs` 参数由 web 层装配传入，缺省时延迟导入兼容旧调用方）。新增 core→web 顶层 import 一律禁止
- **动作语义唯一实现**：故事板增删改查的领域逻辑统一在 `state/storyboard_ops.py`，FC Tool（tools/storyboard_tools.py）与文本 executor（web/action_executor.py）必须委托它，禁止各自重写查找/字段白名单/类别映射

### Rule 3: StateManager 唯一写入点
- `state/manager.py` 中的 `StateManager` 是状态的**唯一写入点**
- 简单路径更新使用 `StateManager.update(path, value)`
- 复杂嵌套操作（列表追加/分组遍历修改）允许直接操作 `StateManager.state_dict`，
  但操作完成后**必须调用 `StateManager.save()`** 持久化
- **禁止**在 routes / tools / adapters 中直接写 JSON 文件（atomic_write_text）
- **禁止**绕过 StateManager 单例自建状态实例

### Rule 4: 外部调用必须走 Adapter
- 所有外部 API 调用（LLM 对话、图片生成、视频生成）必须通过 Adapter 层
- Chat → 继承 `adapters/base_chat.py::BaseChatAdapter`
- Image → 继承 `adapters/base.py::BaseImageAdapter`
- Video → 继承 `adapters/base.py::BaseVideoAdapter`
- **禁止**在 route / tool / planner 中直接写 `httpx.post()` 或 `requests.get()`

### Rule 5: Tool 统一注册
- 新增业务 Tool 必须继承 `tools/base.py::BaseTool`
- 必须实现 `get_input_schema()` 返回 Pydantic Model
- 必须实现 `aexecute()` 异步方法
- 通过 `ToolManager.register()` 注册
- **禁止**在 route 中内联实现业务逻辑来绕过 Tool 体系

### Rule 6: Prompt 外置管理
- 所有 system prompt 存放在 `prompts/` 目录
- 通过 `utils/prompts.py::load_prompt()` 加载
- **禁止**在代码中硬编码超过 3 行的 prompt 字符串

### Rule 7: 画布（画布）边界 — 任何时候都禁止修改
- 画布（画布）是**独立迭代的项目**，其代码不在本仓库内，**任何时候都禁止修改其任何文件**
- 双向独立：本项目扩展功能**不得要求改动画布**；画布更新也**不应影响**本项目
- 与画布的所有交互（读素材、写节点、在线检测等）只能走其**既有公开接口**（HTTP API / WebSocket / iframe 嵌入），统一封装在 `adapters/canvas_adapter.py`
- 画布既有接口能力之外的需求（例：读取画布内选中状态）一律视为**不可实现**，**禁止**通过修改画布源码、注入脚本、读取其本地文件等方式补齐
- 如确需画布侧新能力，只能向画布项目提需求，由其独立迭代发布后再对接

### Rule 8: 工作流范式分工（4.6 收敛）
- **主路径**：对话式 Agent（`core/planner.py` 多步循环 + Skill 阶段纪律），新能力一律在此迭代
- **CLI 批处理**：`cli.py` 使用 `workflows/engine.py` 的 DAG 阶段调度，是引擎的唯一积极使用方
- **遗留一键流水线**：`web/routes/workflow.py` 已冻结（只维护不新增），不得在其中新建与主路径重叠的能力

---

## 二、代码组织约束

### 路径与配置
| 需求 | 正确做法 | 禁止做法 |
|------|----------|----------|
| 引用项目目录 | `from src.video_agent.utils.paths import ASSETS_DIR` | `Path(__file__).resolve().parent...` |
| 读取可调参数 | `from src.video_agent.config import settings` | 硬编码数字如 `timeout=120` |
| 状态类别 Key | `from src.video_agent.state.models import CAT_SHOTS` | 硬编码 `"shots"` 字符串 |

### 异常处理
- 业务异常必须继承 `exceptions.py::VideoAgentError`
- Adapter 调用失败 → 抛 `AdapterError`
- 生成管线失败 → 抛 `GenerationError`
- 状态操作失败 → 抛 `StateError`
- **禁止**用 `return False` / `return {"error": ...}` 代替异常

### Import 规范
- 所有 import 放在文件顶部（标准库 → 第三方 → 项目内部）
- **禁止**在方法内部 `from datetime import datetime`（应放顶部）
- **禁止**循环导入：routes 不得被 tools 导入，tools 不得被 adapters 导入

### 类定义
- **禁止**在同一文件中定义两个同名类（后者会覆盖前者）
- **禁止**在文件末尾追加 Mock/临时类来覆盖已有实现
- 修改已有类时，必须原地修改，不得"新建一个覆盖它"

---

## 三、新增功能标准流程

### 3.1 新增一个 Tool
```
1. 在 tools/ 下新建或追加到已有文件
2. 定义 Input Schema（继承 BaseModel）
3. 定义 Tool 类（继承 BaseTool）
4. 实现 get_input_schema() + aexecute()
5. 在 register 函数中调用 ToolManager.register()
6. 写单元测试验证
```

### 3.2 新增一个 API 路由
```
1. 在 web/routes/ 下新建 xxx.py
2. 创建 APIRouter()
3. 在 app.py 中 include_router(xxx_router, prefix="/api")
4. 路由内部通过 StateManager / ToolManager / Planner 操作
5. 异常用 VideoAgentError 体系
6. 写集成测试验证
```

### 3.3 新增一个 Adapter（接入新平台）
```
1. 在 adapters/ 下新建 xxx.py
2. 继承对应基类（BaseChatAdapter / BaseImageAdapter / BaseVideoAdapter）
3. 实现所有抽象方法
4. 在 AdapterFactory 中注册（或通过 register_from_config 动态注册）
5. 在 data/api_providers.json 中添加供应商配置
6. 写单元测试（mock HTTP 响应）
```

### 3.4 修改状态模型
```
1. 在 state/models.py 中修改 Pydantic 模型
2. 如需新字段，提供 default 值（向后兼容）
3. 如需新类别常量，加到 models.py 顶部（CAT_XXX）
4. 更新 StateManager 的相关辅助方法
5. 确保 to_frontend_dict() 输出兼容前端
6. 跑全量测试
```

---

## 四、接入外部平台专项规则

### 4.1 接入新 LLM 供应商（如 Claude API / 通义千问 / 本地 Ollama）
- **必须**实现 `BaseChatAdapter` 接口
- **必须**支持 `chat()` + `chat_stream()` 两个方法
- 如果供应商不支持 function calling，`supports_function_calling` 返回 False
- 流式响应中 `tool_calls[].function.arguments` 是 JSON 字符串，**必须 json.loads() 解析**
- 超时从 `settings.llm_timeout` / `settings.llm_stream_timeout` 读取
- 错误抛 `AdapterError`，不得静默吞掉

### 4.2 接入画布/设计工具（如 Canvas / Figma API）
- 作为 Tool 接入（继承 BaseTool），不作为 route 内联逻辑
- 外部 HTTP 调用封装在 Adapter 中
- 操作结果通过 StateManager 持久化
- **边界**：画布画布代码任何时候禁止修改（Rule 7），只能消费其既有公开接口

### 4.3 接入 CLI 工具（如 Codex CLI / Gemini CLI）
- 参考 `adapters/agy_cli.py` 的模式
- 用 `asyncio.create_subprocess_exec()` 调用，**禁止** `subprocess.run()` 阻塞
- 用 `asyncio.sleep()` 而非 `time.sleep()`
- 输出解析失败时抛 `AdapterError`，不得返回假数据

### 4.4 接入桌面端（如 Claude Desktop / Electron）
- 本项目作为后端服务，通过 HTTP API 对接
- **不得**为桌面端单独写一套状态管理或 LLM 调用逻辑
- 复用已有 `/api/agent/chat` 端点

---

## 五、维护与修改规则

### 5.1 修改已有功能
- **先读懂**现有实现再动手，不得"重写一遍"
- 修改范围最小化：只改必须改的行
- 不得因为"觉得可以更好"而重构不相关的代码
- 修改后必须跑 `python -m pytest tests/ -q` 确认 0 失败

### 5.2 删除代码
- 删除前确认无其他模块引用（全局搜索）
- DEPRECATED 模块保留别名导入，不立即删除
- 删除后跑测试

### 5.3 调试与临时修改
- **禁止**提交带有 `print()`、`# TODO: remove`、`# HACK` 的代码
- 调试用 `logger.debug()`，不用 print
- 临时 mock 不得覆盖正式实现

---

## 六、测试要求

### 必须写测试的场景
- 新增 Tool → 至少 1 个单元测试
- 新增路由 → 至少 1 个集成测试（用 TestClient）
- 新增 Adapter → 至少 1 个 mock 测试
- 修改核心逻辑（Planner / StateManager / agent_loop）→ 补充回归测试

### 测试运行
```bash
python -m pytest tests/ -q          # 全量
python -m pytest tests/unit/ -q     # 仅单元
python -m pytest tests/integration/ -q  # 仅集成
```

---

## 七、文件地图（快速定位）

```
src/video_agent/
├── core/planner.py          ← Agent 唯一入口（Rule1）
├── core/agent_loop.py       ← 多步循环唯一实现（Rule2）
├── web/
│   ├── actions.py           ← studio-actions 解析执行（re-export 入口）
│   ├── app.py               ← FastAPI 主应用 + 路由注册
│   └── routes/              ← API 端点（薄层，不放业务逻辑）
├── state/
│   ├── manager.py           ← 唯一写入点（Rule3）
│   └── models.py            ← Pydantic 模型 + 常量
├── adapters/
│   ├── base_chat.py         ← Chat Adapter 基类（Rule4）
│   ├── base.py              ← Image/Video Adapter 基类
│   ├── factory.py           ← 适配器工厂 + 注册
│   └── openai_compat.py     ← OpenAI 兼容实现（参考范例）
├── tools/
│   ├── base.py              ← Tool 基类（Rule5）
│   ├── manager.py           ← Tool 注册表
│   └── storyboard_tools.py  ← 故事板 Tool（参考范例）
├── config.py                ← 集中配置（Settings）
├── exceptions.py            ← 统一异常层次
└── utils/
    ├── paths.py             ← 路径常量
    └── prompts.py           ← Prompt 加载器
```

---

## 八、AI 工具使用本文档的方式

| 工具 | 使用方法 |
|------|----------|
| **Cursor** | 将本文件命名为 `.cursorrules` 放在项目根目录 |
| **Claude Desktop** | 在 Project Knowledge 中上传本文件 |
| **Codex / Copilot** | 在对话开头贴入"一、二"两节 |
| **Qoder / Windsurf** | 放入项目根目录，工具会自动读取 |
| **通用** | 每次对话第一条消息贴入本文档 |

---

## 九、违规检查清单（代码审查用）

完成任何修改后，逐项确认：

- [ ] 没有修改画布（画布）项目的任何文件（Rule 7）
- [ ] 没有在 routes/ 中直接调用 httpx/requests
- [ ] 没有绕过 Planner 直接处理用户消息
- [ ] 没有绕过 StateManager 直接写状态文件
- [ ] 没有新建与已有类同名的类
- [ ] 没有在方法内部 import（应放文件顶部）
- [ ] 没有硬编码路径（应用 paths.py）
- [ ] 没有硬编码数字（应用 config.py）
- [ ] 没有硬编码状态 Key 字符串（应用 CAT_XXX 常量）
- [ ] 没有使用 `datetime.utcnow()`（应用 `datetime.now(timezone.utc)`）
- [ ] 没有使用 `time.sleep()`（应用 `await asyncio.sleep()`）
- [ ] 全量测试通过：`python -m pytest tests/ -q`

**指令治理项（涉及模型行为规则的修改时额外确认，见第十节）**：

- [ ] 已在 10.3/10.4 定位规则的唯一定义层，没有在症状现场就近补条款
- [ ] 新规则没有在其他层留下分身（全局搜关键词确认只有一处表述）
- [ ] 能用代码校验的约束已下沉层 7/9，没有新增不必要的“严禁/必须”
- [ ] 已按 10.7 同步点清单核验联动文件
- [ ] 事故类修复有带事故编号的回归用例，且 10.8 台账已记一行

---

## 十、指令治理层（模型行为规则的宪法）

> **本节背景**：2222/3333/4444/5555/6666/7777/8888 系列事故的复盘显示同一模式——
> 每次出事就在“出事的那一层”补一条条款，同一条规则最终散落在 5+ 个层且各自表述，
> 思考模型把大量推理时间花在调解层间冲突上，补丁越多分歧越大。
> **本节目标：任何规则只有一个家；任何修复只动规则的家，不动症状现场。**
> 对齐业界成熟编码 Agent（Claude Code / Codex / Qoder 类）的四条第一性原理：
> 指令单一来源、约束下沉工具层、状态即数据、模型分层。

### 10.1 三大宪法原则

**P1 单一事实源（Single Source of Truth）**
每条规则只有一个**表述源**（归属见 10.3）。其他层需要提及该规则时，
只能引用（“按 Skill『何时暂停』执行”），**禁止复述条款内容**。
复述即漂移，漂移即打架——这是本项目全部“层间冲突”事故的唯一来源。
细化：一条规则允许同时存在“引导（prose 告诉模型怎么写）+ 校验（代码裁定写没写对）”
两个角色，但**表述源唯一、校验实现唯一**（如 no subtitles：Skill 表述 + 质量闸校验）；
引导与校验冲突时，以代码校验的客观结果为准并修表述。

**P2 约束下沉（Code over Prose）**
能被代码机械校验的规则，一律实现为工具/执行器层校验（拒收+报错回喂/自动修正），
**禁止**用 prose（“严禁/必须”）说服模型。prose 只允许描述工具功能与任务目标。
每一条“严禁”都是没能在工具层解决的债务；新增 prose 禁令前必须先回答：
“这条为什么不能被代码校验？”
**校验作用域（与铁律第 0 条/4444 决策对齐）**：代码校验只裁定**模型产出的格式与客观状态**
（缺字段/超时长/越阶段），永不拦截**用户意志**——用户指令永远优先，
闸机对用户越流程的操作只警告不拦人；拒收后的重试提示词也不得夹带新规则。

**P3 状态即数据（State as Data）**
注入给模型的状态/工具结果必须是纯客观数据。引导语（该做什么）独立且极短，
**禁止**把说教嵌入数据体（如状态 JSON 内部写“请先做 X”）。

### 10.2 指令层全量清单（共 12 层）

修改任何模型可见文本前，先在此表定位它属于哪一层：

| # | 层 | 位置 | 注入时机 | 唯一职责 | 禁止承载 |
|---|----|------|---------|---------|---------|
| 1 | 平台协议 | `prompts/planner/system.md` | 主模型每轮 | 动作格式/暂停通道/输出纪律/工具使用法 | 业务领域规则（拆解粒度/提示词质量等） |
| 2 | 文本协议 | `prompts/planner/text_actions.md` | 仅非 FC 通道 | studio-actions 全量动作定义 | 流程/业务规则 |
| 3 | Skill 文档 | `data/skills/*.md` | planner 章节/执行器内章节 | 该 Skill 的流程步骤、暂停点、产出规范；`skill_manifest` 声明块（闸机开关/流程开关，S1） | 模型能力参数（时长/分辨率数值）；平台通用层硬编码其专属流程 |
| 4 | 执行铁律文档 | 项目内「执行铁律.md」（spec_rules 模板） | Skill 激活时全文注入（主模型 + 执行器，D2 已实现） | 项目级可编辑生产契约 | 平台协议、流程步骤 |
| 5 | 制片规格文档 | 项目内「制片规格.md」 | 执行器显式注入/按需 read | 本项目参数事实（画幅/分辨率/渠道/时长） | 任何规则性表述 |
| 6 | 执行器提示词 | `skill_runtime/executors.py`（_TASK/_BOUNDARY/自检词） | 执行器独立调用 | 单一任务的输出格式与边界 | 跨阶段流程规则 |
| 7 | 闸机 | `core/prompt_gates.py` | 工具裁剪/警告/回喂 | 客观状态校验与阶段门禁 | prose 说服（闸机只裁定，不说教） |
| 8 | 回喂话术 | `agent_loop.py`/`planner.py`（fc_feedback/阶段提醒等） | 轮间 | 客观回报上轮结果 + 单句下一步；允许当轮短期指令（如“再跑一轮自检”） | 持久性规则条款 |
| 9 | 系统兜底卡 | agent_loop/planner（规格暂停注入/出口引导卡/总结兜底） | 轮末 | 客观状态 → 确定性交互，不依赖模型自觉 | 无（代码行为，非指令） |
| 10 | Tool description | `tools/*.py` 的 description 字段 | FC 通道每轮随 schema | 该工具做什么、参数含义 | 跨工具流程规则 |
| 11 | 状态上下文 | `state/context_builder.py` | 每轮 | 客观工作台数据（骨架/清单/预览） | 说教性引导语 |
| 12 | 记忆与解除引导 | `memory/` 注入；`chat_service._consume_pending_confirmation` | 按需 | 项目历史偏好；暂停窗口的回应语义 | 新规则 |

### 10.3 规则归属表（Single Source of Truth 落地）

| 规则类型 | 唯一定义层 | 禁止出现在 |
|---------|-----------|-----------|
| 平台对话协议（动作格式/暂停通道/输出纪律） | 层 1 system.md | Skill、铁律、执行器 |
| 项目级生产契约（拆解粒度/回复精简/流程覆盖开关） | 层 4 铁律文档 | system.md 硬编码、执行器常量 |
| 流程步骤与暂停点（先做什么/何时暂停） | 层 3 Skill 的 `<planner>` 与「何时暂停」 | system.md、runtime 块条款、回喂话术 |
| 单一执行器的输出格式与边界 | 层 3 Skill 对应章节是规范唯一表述源；层 6 执行器任务词只承载任务目标与格式锚点，禁止复述章节规范（以执行器为校验方） | system.md |
| 模型能力参数（分辨率/时长/渠道） | 层 5 制片规格（运行时动态注入） | Skill 硬编码数值、执行器写死数值 |
| 可机械校验的约束（字段/格式/时长上限/阶段边界） | 层 7/9 代码校验（拒收或修正） | 任何 prose 层重复表述 |
| 通用提示词规范（no subtitles 等不变的格式要求） | 层 3 Skill 的 `<write_the_prompt>` | system.md |
| Skill 的平台行为开关（结构闸启停/规格向导/阶段裁剪/渠道块） | 层 3 Skill 的 `skill_manifest` 声明块（引擎默认最小闸：业务闸全关、流程闸不注入） | 平台通用层硬编码（prompt_gates/agent_loop/fc_tool_runner/prompt_builder/planner） |

**冲突裁决顺序（模型可见优先级，与铁律一致）**：
用户最新指令 > 铁律文档 + 制片规格 > Skill > 平台协议默认。
代码校验层（闸机/执行器拒收）不参与裁决——它是客观事实，只对结果裁定并回报。

### 10.4 症状归位表（不走捷径的核心）

**修复任何模型行为问题前，先在下表找到症状对应的正确归位层；
禁止在“捷径层”动手——捷径层都是历史事故验证过的错误路径。**

| 症状 | 正确归位层 | 禁止的捷径（历史事故） |
|------|-----------|---------------------|
| 模型该暂停时没暂停 | ①层 9 客观状态兜底注入；②层 3 Skill「何时暂停」加暂停点 | 在多层同时加“必须暂停”（5555：Skill/提示词/铁律都说暂停，模型仍幻觉已暂停） |
| 模型输出缺字段/格式错 | 层 6 执行器拒收+重试+格式锚点 | 只在 prose 加“必须携带 X 字段”（8888：20 组全落默认标题） |
| 模型虚报完成 | 层 7 客观状态核验 + 只警告不拦人 | 硬拦截没收暂停（4444：误伤合法暂停） |
| 产出数量失控（太多/太少） | 铁律+Skill+执行器任务词三处**同步**写比例约束，自检限轮数 | 单向穷举表述（“宁可多建”）与克制条款并存（8888：50 元素） |
| 工具成果用户看不见（总结/卡片） | 层 9 系统兜底拼入正文/即时 SSE 事件 | 只加“必须展示”prose（2222/3333：总结丢失两连击） |
| 参数与生成能力不符 | 层 5 规格收集 + 执行器运行时注入 | Skill/执行器硬编码数值（Seedance 时长矛盾） |
| 模型继续推进了不该推进的阶段 | 层 7 工具裁剪 + 层 9 兜底卡 | 在回喂话术里加长段告诫（5555：“请继续完成任务”推着模型直冲拆解） |
| 确认卡选项渲染异常 | 层 12 前端归组启发式（option_groups） | 改模型输出格式迁就前端 bug（5555：误归组分页向导） |

### 10.5 修复决策树（每次修改前的强制思考流程）

```
问题出现
  │
  ├─ Q1 这是什么规则失效？按 10.4/10.3 定位它的唯一定义层
  │     └─ 找不到归属 → 它是一条新规则，按 10.3 选层安家，而不是在症状现场造新家
  ├─ Q2 这条规则能被代码机械校验吗？
  │     ├─ 能 → 在层 7/9 实现校验（拒收/修正/兜底），不加 prose
  │     └─ 不能（主观判断类）→ 改 prose，但只改唯一定义层
  ├─ Q3 该规则在其他层已有分身？
  │     ├─ 有 → 删除分身或改引用，禁止留下两个各自表述的版本
  │     └─ 无 → 继续
  ├─ Q4 实施修改 + 回归测试（每个事故必须有一个回归用例，用例名带事故编号）
  └─ Q5 按 10.7 同步点清单核验；在 10.8 台账记一行
```

**捷径禁令（违者视为错误实现）**：
- 禁止在事故现场就近补条款（哪个文件爆出来就改哪个文件）而不查归属层；
- 禁止同一条规则在两层以上新增表述（“多点加固”是冲突的主要来源）；
- 禁止新增 prose 禁令前不回答“为什么不能被代码校验”；
- 禁止修改铁律模板/Skill/协议时不同步检查另两处的同义条款；
- 禁止用“模型不听话”作为结论——先查是否层间冲突导致模型无法判断。

### 10.6 指令体量预算（防反弹的量化红线）

| 项 | 预算 | 现状（2026-08-09 二轮彻底清理后实测） | 超限处理 |
|----|------|---------------------|---------|
| system.md | ≤ 7KB（纯协议） | **7.0KB 达标**（输出纪律/执行优先/画布/媒体段均已清分身或压缩） | 继续压缩或拆分按需注入 |
| 全链路“严禁/不得/禁止”总数 | ≤ 8 处 | ~40 处（system.md 仅 2；剩余集中在各层自身表述源内，债务 D4） | 逐条审计（见 10.6 命令） |
| 单执行器 system+user 提示词 | ≤ 25K 字符（含剧本/状态注入） | ≈ 24.7K（含铁律 ~700 字，贴线） | 缩减注入而非删任务词 |
| 回喂话术单条 | ≤ 3 句 | 合规（SELF_CHECK_FEEDBACK 已改铁律引用） | 超出说明在回喂里写规则，迁回归属层 |
| 同一规则的定义处数量 | 恒等于 1 | 拆解粒度/回复精简/执行优先均已收敛单一表述源 | 立即清理分身 |

每季度（或每 3 个事故后）做一次“严禁审计”：`grep -rn "严禁\|不得" prompts/ src/video_agent/core/ src/video_agent/skill_runtime/ data/skills/`，
逐条回答“能否下沉/是否重复”，结果记入 10.8 台账。

### 10.7 已知耦合点清单（改 A 必须同步检查 B）

| 修改点 | 必须同步检查 |
|--------|------------|
| Skill 章节 tag 改名/拆分执行器 | `SECTION_TAG_STAGES` 映射 + system.md 动作清单 + 存量 Skill 旧标签（阶段一事故） |
| 铁律模板（spec_rules._IRON_RULES_DOC_BODY） | 只影响新建项目；老项目需手动同步或删文档重建；闸机读取逻辑（铁律优先/规格回落） |
| 规格文档改名/字段 | `prompt_gates._SPEC_NAME_HINTS` + provider_prefs 解析 + 执行器参数回退链 |
| 执行器输出格式 | action_executor 兜底链 + 自检去重键（去重依赖标题有效，8888 事故） |
| 新增暂停点 | Skill「何时暂停」+ 层 9 兜底注入（二者缺一不可：Skill 管引导，兜底管强制） |
| 新增 SSE 事件 | 工具层 emit → planner 白名单 → chat_service 透传 → 前端 handler（四段缺一即静默失效，3333/6666 事故） |
| 新增 FC 工具 | tool description（层 10）+ 阶段裁剪集（STORYBOARD_STAGE_TOOLS 等）+ 测试 |
| skill_manifest 白名单键（skill_docs._MANIFEST_*_KEYS） | 六个消费点：prompt_gates.parse_gate_rules/validate_prompt_write、agent_loop._flow_enabled、fc_tool_runner._spec_wizard_on、planner._compute_excluded_tools、prompt_builder（stage_note/渠道块）、action_executor._spec_gate_ok；pause 节另由 guard.skill_requires_stage_pause 与 lint 消费；同步 test_skill_manifest.py 快照登记 |

### 10.8 事故台账（规则漂移的活证据，只增不删）

| 事故 | 症状 | 根因层 | 修复落点 |
|------|------|--------|---------|
| 2222/3333 | 总结不可见 | 回喂链路丢 payload | 工具结果带 detail + 层 9 状态兜底 |
| 4444 | 硬拦截误伤合法暂停 | 闸机越权 | 改“只警告不拦人”，裁决权归用户 |
| 5555 | 规格写完不暂停直冲拆解 | 层 9 缺失 + 回喂推波 | 规格暂停兜底注入（双轨） |
| 6666 | 文档卡片延迟渲染 | SSE 透传白名单断链 | 四段链路补齐 |
| 7777 | 提示词覆盖/超时 | 批量单次全量输出 | 分批断点续写 |
| 8888 | 默认标题×20、元素爆炸、253s | 执行器验收缺失 + 单向穷举 + 层间冲突 | 拒收重试 + 克制条款 + 本节 |
| 9999 | 总结正文两遍；规格参数「待确认」放行；参数栏无分辨率；分镜拆解零产出 | 层 9 判重用裸子串；层 9 兜底卡无参数候选；建草稿不补印规格值；执行器输出预算不足 | 归一化判重（层 9）+ 规格参数向导兜底与机械定稿（层 9/12）+ 草稿分辨率补印（工具层）+ 拆解预算 16384/重试翻倍（层 6） |
| 1111 | 总结后不停顿直冲规格；模型自造向导选项无法落盘 | 层 3 步骤1 无暂停点 + 层 9 无总结闸；层 9 兜底仅覆盖模型未暂停路径 | Skill 步骤1 加暂停点 + 双轨总结闸（层 3/9 同步，10.7）+ merge_spec_param_wizard 选项标准化（层 9）+ pending_pause_kind 语义区分（层 12） |
| 6666（二轮） | 「确认总结」暂停被判定多余；规格向导缺出图/出视频渠道选择；规格文档先于交互写入 | 层 9 闸设置与用户预期流程不符；向导选项维度不全 | 总结闸改为规格收集闸（script_analyze 后、规格文档写入前弹向导）；向导恒定含出图/出视频渠道组（前端 ConfirmPicker 下拉，5555 能力复用）；渠道选择按供应商模型列表客观落盘（provider_config.apply_spec_channel_selections）；spec_collected 标记防重复向导；Skill 步骤1 暂停条款撤销（D4 严禁债 -2）、步骤2 改「先交互收集后写文档」 |
| 99 | 制片规格写完后正文又拼一遍剧本总结；规格收集向导（渠道下拉组）重复弹出 | 层 9 总结兜底无阶段边界（任何暂停轮都补）；spec_pause_card 与 merge_spec_param_wizard 同批双重消费 spec_collected，审阅卡被重新并入向导 | 总结兜底限解析阶段注入（本批 script_analyze 或 pause_kind=collect，层 9）；系统注入审阅卡后同批跳过 merge（层 9 双轨：fc_tool_runner + agent_loop） |
| S1 | 切换 Skill 指令打架：系统通用层把测试 Skill 的专属流程套到所有 Skill（语言闸冒用 Skill 条款、规格向导/阶段裁剪/暂停卡写死下一步） | 违反 P1：测试 Skill 规则复述进层 7/9/11/1 五层形成分身 | skill_manifest 声明块（层 3）：业务闸开关化默认全关，流程闸/裁剪/渠道块按声明启停，暂停卡文案中立化，流程基线随注外来工具名映射，16 存量 Skill 迁移声明 + 快照回归 |

### 10.9 模型分层原则（速度治理）

- 流程编排类决策（暂停/推进/选工具）是简单决策，优先用轻模型或低思考预算；
- 生成类任务（拆解/提示词编写/自检）才用强模型；
- 深度思考模型的推理时长与指令冲突度正相关：**模型变慢首先怀疑层间冲突，
  而不是换更大的模型**（8888：95s 思考的主成分是调解五处穷举/克制条款的冲突）。

### 10.10 存量债务清单（宪法生效时的已知违宪项，清一条删一条）

已清偿（保留记录供审计）：
- ~~D1 system.md 内嵌业务铁律~~ → 2026-08-09 已删除三大铁律与时长规则，归位铁律文档 + Skill + 质量闸；
- ~~D2 铁律未全文注入~~ → prompt_builder 主模型与执行器 system 均已注入铁律全文；主模型注入已与 Skill 激活解耦（铁律文档存在即注入）；
- ~~D3 runtime 块 5 条款重复~~ → 已压至 3 条（执行方式/阶段边界与确认/工具白名单）；
- ~~D5 执行器任务词复述章节规范~~ → _KE_TASK/_KE_BOUNDARY/自检词只留目标+格式锚点，粒度规范以铁律为唯一表述源；
- ~~D6 工具描述带流程暗示~~ → workflow_pause / workflow_step description 均改为纯功能+参数；
- ~~D7 system.md 超预算~~ → 二轮清理后 7.0KB 达标：输出纪律 1/4（同铁律第 2 条）、执行优先（同铁律第 0 条）删除，画布/媒体段压缩；
- ~~阶段边界 prose~~（二轮新增清偿）→ 下沉为代码校验：执行器按 only_group_type 拒收越界分组，boundary 只留一句客观声明；回喂 SELF_CHECK_FEEDBACK 与阶段裁剪提示同步改铁律引用/纯客观。
- ~~S1 通用层被单一 Skill 污染~~ → 2026-08-10 skill_manifest 声明块清偿：引擎业务闸（时长/字幕/镜头语言/音频层）默认全关，规格向导/阶段裁剪/渠道注入块仅对声明 Skill 生效，暂停卡文案去写死下一步，流程基线随注外来工具名映射，16 存量 Skill 迁移声明；test_skill_manifest.py 快照回归防再犯。

未清偿：

| 编号 | 债务 | 违反条款 | 清偿动作 |
|------|------|---------|---------|
| D4 | 全链路 ~40 处“严禁/不得”（system.md 已只剩 2 处；Skill 15 / executors 12 / 其余），多数在自身表述源内但仍可下沉或删除 | P2 | 逐条审计（见 10.6 命令），可机械校验者继续下沉 |
| D8 | 老项目铁律文档无“体量相称/宁缺毋滥”条款（模板只影响新建项目） | 层 4 | 用户手动同步或删文档重建；如需自动迁移另行拍板 |
