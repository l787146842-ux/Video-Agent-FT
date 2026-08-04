# 架构铁律 — AI 协作开发强制约束

> **本文档是所有 AI 工具（Cursor / Codex / Claude / Gemini / Qoder 等）在本项目中工作的最高优先级约束。**
> 任何代码生成、修改、重构都必须遵守以下规则。违反即视为错误实现。

---

## 一、不可违反的核心规则

### Rule 1: Planner 唯一入口
- `src/video_agent/core/planner.py` 中的 `Planner` 类是对话式 Agent 的**唯一入口**
- routes 层（`web/routes/agent.py`）必须通过 `Planner.handle_message()` 或 `Planner.handle_message_stream()` 处理用户消息
- **禁止**在 route 中直接调用 LLM Adapter 或自行实现多步循环

### Rule 2: 多步循环唯一实现
- `core/agent_loop.py` 中的 `run_agent_loop()` 是多步循环的**唯一实现**（原 web/agent_loop.py 已下沉，旧路径仅为 DEPRECATED 兼容壳）
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
│   ├── agent_loop.py        ← DEPRECATED 兼容壳，re-export core.agent_loop
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
