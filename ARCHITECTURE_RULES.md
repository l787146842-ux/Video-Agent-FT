# 架构宪法 — AI 协作开发强制约束（v2 · 2026-08-13）

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder / CodeBuddy 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。
>
> **治理总纲：按业界最高标准执行，禁止走捷径。** 具体含义：
> 1. **策略即数据（Policy-as-Data）**：所有闸机/安全规则以注册表数据表达，带稳定 `rule_id`、层级归属、外置文案；禁止散落硬编码。
> 2. **单一事实源（Single Source of Truth）**：状态写入归 StateManager、循环归 agent_loop、入口归 Planner、提示词归 `prompts/`、前端类型归 `gen_api_types` 生成物。
> 3. **评测驱动（Evaluation-Driven）**：闸机行为由黄金语料库校准，误杀/漏放计数劣化即测试失败；提示词迁移由快照测试锁语义。
> 4. **deny-overrides 分层合并**：平台硬边界永远优先，Skill 配置只能加强或持平，不能削弱。
> 5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批未提交改动（本仓库已因此丢过整批工作，见 §5）。
> 6. **验收四件套 + 浏览器目测**：`pytest` + `vitest` + `tsc --noEmit` + `gen_api_types --check` 全绿，UI 变更必须浏览器实测截图对照，缺一项不算完成。

---

## 一、核心架构铁律

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` / `handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: 多步循环唯一实现 + 双轨一致
- `core/agent_loop.py::run_agent_loop()` 是多步循环的**唯一实现**；`MAX_STEPS` 读 `settings.max_steps`
- **双轨执行**：FC 轨（`core/fc_tool_runner.py`）与文本轨（`web/action_executor.py`）必须对同一请求使用同一闸机策略实例与同一动作语义，判定逐字节一致；新增判定逻辑必须双轨同测
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

### 2.1 三层策略模型
| 层 | 内容 | 可配置性 |
|---|---|---|
| 平台层 `platform.*` | 生成确认闸、阶段硬边界（写文档/建结构强制暂停）、故事板审阅窗口、首拆只允关键元素、防虚报覆盖、gate_heal 自愈 | **硬编码，manifest 无权关闭**；仅可经用户一次性申诉逐条放行 |
| Skill 层 `skill.*` | 时长/字幕/镜头语言/音频层标记、中文占比、最短字数、@引用、spec_gate 流程前置 | manifest 可关/可放宽/**可加严**；字数阈值只可抬高不可低于平台地板 |
| 会话层 `session.override` | 用户「本次放行」一次性记录 | 仅用户手动产生，即时消费、留痕、不可持久化 |

### 2.2 manifest 只能加强或持平（强制不变量）
- 外部 Skill 文档来自成熟平台，其配置**不可信**；系统必须坚守自身安全底线
- manifest 试图触碰 `platform.*` 的任何键：**静默忽略 + warning 日志**，并必须有负面用例测试断言其无效
- 可配项仅限风格/流程类（音频层、中文占比、@引用、规格前置等）；「规格前置」经用户确认为可配置项，不锁死

### 2.3 规则注册表（Policy-as-Data）
- `core/prompt_gates.py` 维护 `GATE_RULES` 注册表：稳定 `rule_id`（如 `skill.require_subtitle`、`platform.gen_confirm`）+ 层归属 + 中文描述
- 判定返回结构化 `GateVerdict(rule_id, layer, ok, message)` 列表；文案外置 `prompts/gates/messages.md`，杜绝自由文本
- 回喂模型与展示用户用**同一 verdict 源**（防两套说辞）

### 2.4 拦截可见 + 一次性申诉放行
- 拦截必须用户侧可见（警示 chips 带规则描述 + 来源标注「平台」/「Skill『xxx』」）
- 「本次放行」单次生效、全程留痕、不形成持久削弱；平台层规则同样可被用户显式意志逐条放行，但每次单独点

### 2.5 审计闭环
- `tracer.record_gate(...)` 持久化到 `agent_traces.jsonl`；调试端点 `GET /api/agent/gates` 与 `/api/agent/traces` 并列

### 2.6 校准闭环（评测驱动）
- `tests/fixtures/gate_corpus/` 黄金语料（合法/应拦两组真实风格样例，带期望 verdict）；按 规则×Skill profile 遍历，误杀/漏放计数劣化即测试失败
- **闸机校准经验**：连续相同原因拦截必须升级改写指引（合并相同 verdict、附「第 N 次被拦」差异化提示），防模型陷入「拦截-重写-再拦截」空转；拦截事件入生成日志面板可见

---

## 三、前端体验宪法

### 3.1 体验基线不退化
- **2026-08-12 02:00 前的系统状态为可接受基准线（baseline）**；任何变更不得导致基线功能/交互/视觉退化
- UI 变更必须浏览器实测（截图对照）后交付；「测试全绿」不等于「UI 正确」

### 3.2 品牌与视觉
- 品牌名正式为「**飞天**」：毛笔行楷笔形（Xingkai/华文行楷/KaiTi 字体栈）、白色、22px、垂直居中、不加人工斜切；**禁止**使用旧品牌名
- 顶部导航按钮（影视工作台/画布/API 配置）**绝对居中**，两侧内容增减不得使其偏移

### 3.3 交互规范（强制）
| 项 | 规范 |
|---|---|
| 发送/停止键 | Agent 运行时**只保留停止键**；发送键仅空闲态显示 |
| 交互确认卡片 | 亮橙色系（主色 `#fb923c`，边框 `rgba(251,146,60,0.6)`、底色 0.12），亮度档对齐阶段完成卡翡翠绿（`rgba(52,211,153,0.3)`）；**禁止** box-shadow/发光 |
| 阶段完成卡片 | 只显示大项（标题+操作数徽标），**不显示正文**；操作明细仅在「已处理 X 个操作」时间线展开 |
| 故事板微调框 | 仅悬停**草稿卡片** 300ms 后缓缓浮现（CSS transition，禁止瞬时弹出）；输入仅针对该卡片；列表其他位置不弹 |
| 分组卡片 | 左上标题纯中文（剥离 `Element_` 等英文前缀）；右上徽标=元素类型（人物/场景/道具…，扫描 tag 跳过「已上传/已确认」等状态值） |
| 上下文用量 | 纯圆圈（无进度条）+ K 数字 |
| 排队引导 | 点「引导」后该条**原位转圈圈**等待接管，禁止顶部 toast 提醒 |
| Skill 消息 | text 与 skillBlocks[0] 相同（trim 后）时仅渲染紫色图块，不重复文字 |
| @ 面板 | 宽 600px/高 560px；网格式卡片（缩略图在上名称在下）；顶部搜索框必须可点击聚焦；关键元素/分镜/音频页签 + 参考栏素材分区；**@ 故事板素材不自动加入参考素材栏** |
| 视频素材 | @ 弹层/提示词 chip/参考素材栏均显示**首帧缩略图 + 左上角 ▶ 角标** |
| 参考图上传 | 分镜面板不设数量上限 |
| 参数栏下拉 | 宽度跟随所选文字（`field-sizing: content`，含箭头占位） |

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
6. **分支格局（2026-08-13）**：`fix/audit-2026-08` 为当前主线；`backup/pre-repair-0812` 保存整改后端批次（compose_policy 策略引擎、CLI 下线、batch6 治理及其测试），待 UI 稳定后**选择性再合并**；`rescue/deepseek-v2-0806` 为 8/6 快照保护分支
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
- [ ] 闸机改动带黄金语料校准；连续拦截有升级指引（§2.6）
- [ ] UI 改动符合 §3 交互规范表，且浏览器实测截图对照
- [ ] 没有 box-shadow/发光出现在确认卡片；品牌仍为「飞天」
- [ ] 没有裸 restore/checkout -- .；本批已 commit；未跟踪文件已核对（§5）
- [ ] 没有硬编码路径/数字/状态 Key；没有方法内 import；没有同名类覆盖
- [ ] 没有 `datetime.utcnow()` / `time.sleep()` / `print()`
- [ ] 验收四件套全绿：pytest + vitest + tsc + gen_api_types --check
