# 交接文档 · run_subagent 正宗子代理执行

> 用途：在新窗口执行《run_subagent 正宗子代理实施计划书》。本文自包含，不必回读历史对话。
> 计划书原文：`C:\Users\ASUS\AppData\Roaming\Qoder\SharedClientCache\cache\plans\run_subagent_子代理计划书_task-ddd.md`
> 状态：**计划书已审定、批准执行**。从 **B1** 起，一批一验、独立 commit。**未开始的批不抢跑。**

---

## 0. 开工前先读的硬约束（违反即返工）
1. **执行模式保持 `ai_decide`**：不改默认档、不加机械工作流驱动（C1b 裁决仍有效）。
2. **思考必须展示**：不关 SSE `reasoning_delta`、不折叠思考。`llm_reasoning_passthrough` 默认已关（展示≠回喂），保持不动。
3. **不碰 `SKILL.md`**（用户自持），不做两形态切换参数（流程归 Skill）。
4. **不改宪法、不复活机械执行器**：`exec_*`/`executors`/`blackbox`/`drive_turn`/`parse_actions_from_reply` 等**永远禁**（`check_legacy_orchestration` 会 FAIL）。
5. **子代理先跟随主模型**（不挂便宜模型）；**步数不进前端**（用 env/config 默认）。
6. **B1 只做 one-shot 一次性子代理**，不做 dsh 的 continuable/background 后台子系统。
7. 交付纪律（AGENTS.md）：小批 commit、独立验收、只认进程退出码（Windows GBK 乱码曾把失败伪装成通过）、UI 变更须构建后用户目测确认。

---

## 1. 一句话目标与根因（8888 诊断收口）
把"拆解剧本 / 写提示词"这段重活交给**一个由模型经 FC 发起、复用 `run_agent_loop`、走同一闸机链、只回摘要、跑在自己隔离上下文里的子代理**连续跑完 → 同时拿住：**稳态缓存 ~90-95%（同会话内前缀单调 + 不 yield 用户）+ 不中断 + 反应快 + 逐单元流式落盘**；主线程只收 append-only 摘要，不再被中间步灌爆（顺带修 63.7% 读数）。
- 63.7% = 近 20 次调用 `Σcached/Σprompt`，被冷启动首调 + 跨轮 TTL 失效拉低（剔后≈90%，见 `scripts/cache_hit_report.py` 稳态口径）。

---

## 2. 设计定稿（落点与子级契约）
### 2.1 落点＝`core/ports` 端口注入（已定，勿改成"散装回调"）
- `run_subagent` 是**控制流伪工具**（同 `workflow_pause`），**不进 `tools/` 业务层**（否则 `tools → core.planner` 反向 import 成环）。
- 在 `core/ports.py` 声明一个子代理启动端口 `subagent_launcher`，由 **planner 在装配点注入实现**（与 `workflow_pause`/宪法"层级例外 `core/ports.py` 端口 + web 装配点注入"同套路）。
- `FCToolRunner.execute` 命中工具名 `run_subagent` → **只经端口调用**拿子摘要、当普通 tool result 回喂父循环；**绝不 import planner / agent_loop**。
- 镜像物证：`fc_tool_runner.py` 里 `if name == "workflow_pause" ...` 与 `st.scope_auto_pause` 分支（约 L402/L441）就是"模型发工具、core 侧拦截"的现成范式。

### 2.2 子级契约（对齐 dsh，见 §5 行号）
- **固定权限范围**：子级启动即定工具集与审批策略，会话内不可扩权。
- **审批 = never**：子级**不发确认卡**、需确认操作确定性拒绝 → 执行不中断。
- **撞闸不重试**：被拒/超范围**不原地重试**，在摘要里说明限制交回主线程（防 8888 式反复重试拖慢）。
- **深度单调**：`child = parent + 1`，持久化、恢复态不得归零；B1 深度上限 = 1（子级工具集剔除 `run_subagent`）。
- **继承父档**：provider/model/reasoning 默认继承父级。
- **append-only 摘要回父**：结果作为父级"仅追加"通知，落在其可复用前缀之后 → 不打碎父前缀缓存。
- **独立子会话**：子代理落**自己的隐藏会话**（携 `parentSession` / `delegationDepth` 血缘），主会话不被灌中间步。

### 2.3 子代理工具白名单（B1 先窄，已认可）
`storyboard_create_group` / `storyboard_add_draft` / `storyboard_patch_draft` / `read_state_group` / `read_skill` / `read_uploaded_doc` / `document_write`。
> **故意不含花钱生成**（`image_generate`/`generate_video`）——生成留主线程受确认闸管。
> 注：`structure_integrity_gate` 在建镜时卡 `title 非空 + sceneRefs 非空并覆盖标题点名元素 + 阶段边界`，**不卡提示词**；故"建镜带全 refs→后补提示词"不被拒。

---

## 3. 宪法安全性（结论：不改宪法）
- 宪法"无**执行器**子代理"禁的是"运行时替模型机械直跑阶段 + 绕闸 + 非-FC 通道"；本方案由**模型经 FC 发起 + 复用 `run_agent_loop` + 走 `guard_pipeline`**，三条全不犯，且"模型永远是唯一行动主体"仍成立。
- `check_legacy_orchestration` 的 FORBIDDEN 无 `subagent/run_subagent/子代理`，扫不到（叫法+机制均不同）。
- §并发契约（ARCHITECTURE_RULES L44-45）已允许"同项目多对话并行、共享状态、后写生效、系统不自动合并" → 子代理落自己会话合法。
- 必做：代码处加一句注释 + `CHANGELOG.md` 记一条裁决，区分"执行器子代理（机械·永禁）"与"`run_subagent`（模型 FC 发起·许可）"。

---

## 4. 分批与每批验收
### B1 · 纵向切片（无 UI）
改动：
- 新增 `core/subagent.py`：`launch_subagent(...) -> str` 薄封装 `run_agent_loop`（one-shot）：深度单调断言、子工具 `restrict` 裁剪、审批=never、独立子会话绑定（携 parentSession/delegationDepth）、"固定范围/撞闸不重试"声明注入、复用父 `cancel_token`。
- `core/ports.py`：加 `subagent_launcher` 端口声明。
- `fc_tool_runner.py`：execute 命中 `run_subagent` 经端口调用、结果当 tool result；`__init__` 持可空端口引用（不 import planner）。
- `planner.py`：装配点注入端口实现；子请求复用同 `StateManager`（父挂起等待，无并发冲突）。
- 注册模型可见工具 `run_subagent({task: string})`（description 写清"何时该委派/不能扩权/超范围回报不重试"）。
- 注释 + `CHANGELOG` 裁决记录。
测试（脚本假模型）断言：①父收 append-only 摘要；②子工具走 `guard_pipeline`；③子落自己会话、主会话不被灌中间步；④子级审批=never、被拒操作不重试只在摘要说明；⑤深度恢复态不归零；⑥`check_legacy_orchestration`/`check_layer_imports` PASS、无 FORBIDDEN 符号；⑦子内再发 `run_subagent` 被剔/拒。
验收：`python -m pytest tests/unit/<新增+planner/fc_runner 相关> -q -n 8 --dist loadfile` → `python scripts/acceptance.py --quick`（只认退出码 0）。

### B2 · 模型档 + 死配置改名（不动前端新增控件）
- 子代理默认跟随主模型：`resolve_role("subagent")` 空即回落主模型。
- `model_policy` 死角色 `executor`→`subagent`、标签"执行器机械"→"子代理"（仅 `summary` 行现存活消费者）：改 `core/model_policy.py`（ROLES/DEFAULT/文档串）、`web/routes/runtime_settings.py`（老 `executor` 条目读入时迁 `subagent`）、`ModelPolicySection.tsx`（标签+提示）、重跑 `scripts/gen_api_types.py`、`test_model_policy`。
- 步数：子循环显式传 `max_steps = settings.subagent_max_steps`（新增 **env/config** 默认 `SUBAGENT_MAX_STEPS`，`MAX_STEPS_RANGE` 钳制；**不进设置页**）。

### B3 · 左栏流式 + 只读记录（前端）
- 子级 `on_event` → 主 SSE 转发轻量"子任务状态"事件；子会话落流。
- `LeftPanel.tsx`（现为 Tab 容器，加第 3 个 Tab）+ 新组件 `SubagentRail.tsx`（读 `/conversations` 过滤 `kind=subagent` + 状态）；点卡片 → 只读 `ChatFeed`（隐藏 `ChatInput`，按 `conversation_id` 装载）。
- UI 变更构建后经用户目测确认（宪法 §3.1）。

### B4 · 账本合流
- 确认子代理真实写工具落 `StateManager` 后，主线程 `workflow_runtime.sync_run`/`commit_turn` 客观探针认账、不虚报（探针读工作台状态，天然认；B4 主要加断言/回归，发现时序缺口再补最小接线）。

---

## 5. dsh 源码引用（`E:\07 天问\dsh-latest`，MIT，小段移植·标出处）
主文件 `packages/subagent/subagent/src/child-agent.ts`：
- `SUBAGENT_DELEGATION_CONTEXT`（L171-175）：固定范围声明原文（"…cannot be widened… operations that require approval are rejected automatically… **do not retry the denied operation; state the limitation**…）→ 译中用作子级注入文案。
- `resolveChildDepth`（L49-58）/ `depth.ts::delegationDepthOf`（持久单调、恢复不归零、`SubagentDepthError`）。
- `resolveChildAgentOptions`（L98-119）：子级继承父级 provider/model/reasoning/maxTokens。
- `childSessionMeta`（L138-156）：`parentSession` / `origin:'subagent'` / 持久 `delegationDepth`。
- `applyChildComposition::tools.restrict`（L217）：子工具裁剪与父链求交。
- `captureDelegatedPolicyOverrides`（L242-247）：子级 `approvalPolicy = 'never'`。
- README `packages/subagent/subagent/README.zh.md`「结算通知·KV Cache 影响」：结果 append-only、不失效父前缀。
> 服务分包结构：`packages/subagent/*`（服务=提供方注册表）+ `dsh-tool-subagent`（模型看到的静态工具）+ provider 后端；能力靠 `ctx.get(...)` 按需取、never hard dep——即"注入不 import"的权威同构。
> **不抄**：continuable/background（`continuation.ts`、后台邮箱、Steer、sendMessage）。

---

## 6. 关键既有代码坐标（省搜索）
- 唯一循环：`core/agent_loop.py::run_agent_loop(user_text, *, llm_call, context_builder, executor, history, max_steps, on_event, stream_hook, stop_scope, session_conversation_id, state_event_content)`；`AgentLoopResult.text` 即摘要。
- 单轮执行/FC 消费：`core/turn_executor.py`；FC 执行与 workflow_pause 拦截：`core/fc_tool_runner.py`。
- planner 入口/装配：`core/planner.py`（`PlannerContext`、`handle_message`、`_STUDIO_STATE_TOOLS`、`_compute_excluded_tools`、注入 adapter 于 `web/chat_service.py` 构造 Planner 处）。
- 隔离上下文参照：`web/adjust_scope.py`（`_active_adjust_scope`/`_scope_history_from_thread`/并发上限）、`state/context_builder.py`（scope 裁剪：子对话只看对应元素）。
- 多会话：`web/routes/conversations.py`（`GET /conversations`、`GET /conversations/{id}/messages`、`POST /conversations/thread` get_or_create）；`state/manager.py::create_conversation`（实现在 `conversation_ops`）；写入定向 `svc.bound_conversation_id`。
- 配置：`config.py`（`max_steps`、`MAX_STEPS_RANGE=(1,30)`、`EXECUTION_MODE_*`、`EXECUTION_PREFERENCE_*`、`llm_reasoning_passthrough`、`model_policy`、`executor_fast_model`）；热更新 `web/routes/runtime_settings.py`（"agent" 白名单组）。
- 模型分层：`core/model_policy.py`（ROLES 编排/生成/摘要/执行器；仅 `summary` 活跃）。
- 前端：`src/web/components/left-panel/LeftPanel.tsx`（Tab 容器）、右栏 `ChatFeed`/`ChatInput`/`ChatMessageItem`；`locale.ts`（`rp.ctx.cacheHit`='平均缓存命中率'）。
- 门禁/验收：`scripts/acceptance.py`（GATES/SUITES/RATCHETS 唯一事实源）、`scripts/check_legacy_orchestration.py`、`scripts/check_layer_imports.py`、`scripts/cache_hit_report.py`；提交钩子 `python scripts/install_hooks.py`。

---

## 7. 下个窗口"开工前自查"清单
- [ ] `git status` 干净；`python scripts/acceptance.py --quick` 基线绿（记下开工前状态）。
- [ ] 精确定位**工具 schema 注册处**（本轮未逐字核实）：找到 `workflow_pause` 的模型可见 schema 声明点 + `planner.tools_schema()` 下发口，照它注册 `run_subagent`。
- [ ] 确认 `cancel_token`/`stop_scope` 绑定接口（`bind_cancel_token`/`current_stop_id`），让子循环复用父停止信号。
- [ ] 确认服务端创建子会话的**确切调用**（`create_conversation`/get_or_create thread + 如何写 parentSession/delegationDepth 元数据；conversation 是否支持自定义 kind/origin 字段，无则加最小元信息）。
- [ ] 子级 `context_builder` 的具体注入形态：角色 system（含 dsh 固定范围声明中文化）+ 不注入主状态/Skill。
- [ ] 全程不引 `exec_*`；改完必跑 `check_legacy_orchestration` + `check_layer_imports` 至 PASS。

## 8. 不做 / 冻结（防翻案）
不改执行模式默认档、不加机械工作流、不做形态切换参数、不加子代理步数 UI、不把子代理挂便宜模型、不改 SKILL.md、不抄 dsh 后台子系统、不复活任何机械执行器符号。
