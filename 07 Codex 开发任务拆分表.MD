# Video Agent v1 — Codex 开发任务拆分表

> 为确保项目高质量、分阶段落地，将 `Video Agent v1` 的开发过程由下至上（Bottom-Up）与由上至下（Top-Down）结合进行拆分。同时包含单元测试（Unit Test）与集成测试（Mock Adapter Test）的配套建设。
> 后续 Codex 可以在交互中，以这里定义的**任务编号 (如 Task 1.1)** 逐步开展具体代码的自动生成和测试编写。


* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）

---

## 阶段一：基础骨架与核心状态（State & Base）
📍 **目标**：搭建代码仓库骨架，实现统一的状态容器机制，确保 Agent 运行过程中的所有数据都有标准定义。

* **Task 1.1：初始化工程结构与基础设施**
  * 建立 Python 目录结构（`src/`, `tests/`, `tools/`, `skills/` 等）。
  * 配置依赖管理工具环境（如 Poetry/Pipenv，或 requirements.txt）及环境变量隔离方案。
* **Task 1.2：开发 State 核心数据模型 (Pydantic)**
  * 参照 `02 State JSON 规范`，实现 `AgentState`、`TaskContext`、`AssetItem` 等核心 Pydantic Model 数据类。
* **Task 1.3：开发 StateManager 状态管理器**
  * 实现基于本地文件（JSON/SQLite）的状态持久化机制。
  * 提供 `save_state`, `update_task_status`, `add_asset` 等状态变更的安全接口。


* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）

---

## 阶段二：底层外接适配层（Adapter Layer）
📍 **目标**：隔离外部调用环境，提供一致的模型和 API 接口封装。

* **Task 2.1：实现 Adapter 抽象层与注册树 (Factory)**
  * 根据 `06 Adapter 接口规范` 编写 `BaseVideoAdapter`, `BaseImageAdapter` 抽象类。
  * 实现单例模式或依赖注入环境的 `AdapterFactory`。
* **Task 2.2：开发具体的云端视频模型 Adapter**
  * 实现 `KlingVideoAdapter`（集成鉴权、API封装、结果轮询 `fetch_result` 功能）。
  * [可选] 实现 `RunwayVideoAdapter` 等其他模型提供商适配。
* **Task 2.3：开发具体的图片/音频模型 Adapter**
  * 实现基础的图像 API 适配（如 FLUX API / local ComfyUI WebSocket 接口等）。
  * 实现通用的长耗时任务统一 Wait 轮询协助函数。


* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）

---

## 阶段三：工具执行与管理池（Tool & ToolManager）
📍 **目标**：提供 LLM 或 Skill 调用的原子执行单元，屏蔽底层逻辑仅暴露 JSON Schema。

* **Task 3.1：搭建 BaseTool 系统**
  * 根据 `05 Tool 接口规范`，完成 `BaseTool`、`ToolResult` 基类及其 Schema 自动生成方法。
* **Task 3.2：开发 Tool Manager（工具总线）**
  * 实现对 `tools/` 目录中工具的动态扫描与注册。
  * 重点实现 `export_schemas_for_llm()`，转出供 OpenAI 调用的 Function definitions。
  * 提供安全校验屏障，拦截异常崩溃，转至统一错误码。
* **Task 3.3：开发核心业务 Tool**
  * 开发 `AudioGenerateTool`, `VideoGenerateTool`。
  * 开发文件操作辅助 Tool（如 `ReadAssetTool`, `CreateFolderTool`）。


* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）

---

## 阶段四：能力原子与技能池（Skill System）
📍 **目标**：打造 Prompt + Tool 业务场景闭环组合，作为 Workflow 里的执行单元。

* **Task 4.1：搭建 Skill Registry 与描述规范**
* **Task 4.2：核心 Skill Prompt 开发（剧本阶段）**
  * 编写 story_generation, character_design 等前置 Skill
* **Task 4.3：核心表现 Skill 开发建设**
  * 编写 storyboard_generation, ideo_prompt_conversion 等转化环节 Skill
  * 参考 `04 Skill 系统规范`，实现 Skill 的 JSON 清单扫描逻辑，支持热重载。
* **Task 4.4：开发 Skill Executor（技能执行器）**
  * 实现 Prompt 渲染引擎（如 Jinja2 或 Python 纯文本替换）。
  * 将输入上下文、Prompt 结合送入内部 LLM，执行所需的结构化解析或 Tool 调用环节，直至任务成功/重试失败返回结果。


* **Task 5.3：实现 Memory 系统 (短期/长期记忆)**
  * 提供 ShortTermMemory（单次任务上下文窗口）
  * 提供 LongTermMemory（基于 RAG 检索的跨项目向量库片段等）

---

## 阶段五：工作流引擎与规划大脑（Workflow & Planner）
📍 **目标**：完成项目顶层业务逻辑封装。

* **Task 5.1：实现基础 Workflow 引擎**
  * 解析符合 `03 Workflow 定义规范` 的 JSON/YAML 配置。
  * 实现有向无环图（DAG）或简单的流式（顺序）图执行。
  * 保障节点（Step）之间的数据状态（context）流转与继承。
* **Task 5.2：开发 Planner 模块（主控 Agent 大脑）**
  * 对接核心 LLM，使 Planner 具备 Goal 目标理解能力。
  * 开发"根据需求挑选适用 Workflow "、"中途干预并更改下一步 Workflow "的关键决策逻辑。

---


## 阶段_新：Planner 与 API 交互层（主控大脑）
📍 **目标**：补充缺失的大脑决策规范和向外暴露的接口定义。
* **Task P.1: 补充 Planner 行为规范**
  * 定义 Planner 如何接收目标，拆解 Phase。
* **Task P.2: API 和 Security 规范机制**
  * 定义标准鉴权和暴露的 HTTP Router 列表。

## 阶段六：集成与交付（Integration & Interface）
📍 **目标**：为最终用户提供入口，让系统跑出第一个完整的“文本到视频”飞轮。

* **Task 6.1：开发交互入口层（CLI / FastAPI）**
  *CLI: 能够解析用户命令行文本，初始化 `State` 并触发 Planner。
  *API: 提供 HTTP RESTful接口供外部前端调用。
* **Task 6.2：端到端整合联调 (End-to-End Test)**
  * 提供一个最小完备用例：输入一句话（如“生成一个宇航员在火星喝茶的3秒视频”），观察 Agent 的完整运作路径：
    `User -> Planner -> 调起单步 Workflow -> 调用分镜 Skill -> 调用 GenerateVideoTool -> Kling Adapter -> 写回 State -> 回复用户。`
