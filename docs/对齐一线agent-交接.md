# 对齐一线 Agent：循环与工具改造 — 交接文档

> 本文档是下个窗口续做的唯一入口（计划文件 §十）。第 0 步先写骨架，最后回填实际状态。
> 计划文件路径见 §8。

## 1. 背景与目标

把本项目的**智能体循环**（`core/agent_loop.py` / `fc_tool_runner.py`）与**工具接口层**（`tools/`）对齐一线 agent 实践。依据两份代码级审计，共 12 条差距（循环 4 + 工具 8）。

项目真正的护城河是"可控性"（闸机/确认/审计/唯一写入点）。本次改造**全部走"约束下沉代码层"（P2）**，只硬化接口与执行安全，**不新增任何运行时闸机或验收门禁**（§13.14(f) 冻结），不动 `data/skills/*`（G1），不改画布项目（Rule 7）。

### 12 项差距决策表

| # | 差距 | 决策 | 理由 |
|---|---|---|---|
| T6 | 描述引用失效工具名 `write_document` | **改** | 纯文案，零风险 |
| T7 | `generate_video` 描述裸奔 | **改** | 高危工具需传达使用时机+确认预期 |
| T1 | 双生图工具歧义 | **改描述，不改名** | 宪法 Rule 5：改名属高风险须单独立项；先互斥消歧 |
| T8 | 画布读工具无截断/分页 | **改** | 对齐项目输出预算哲学 |
| T3 | 枚举未进 Schema | **改** | 闭集改 Literal；混合集 `target` 改校验+结构化报错 |
| T5 | 错误无结构化轴 | **改** | `ToolResult` 加 `error_code`/`retryable`（带默认值） |
| T2 | 写类入参无类型+静默丢弃 | **改（两步走）** | 先"错误可见"，评测通过后再 `extra="forbid"` |
| T4 | 无幂等键 | **改（轻量）** | 写工具加可选 `idempotency_key`，轮内去重账本 |
| L1 | 批级事务/回滚缺失 | **改（检查点+条件回滚）** | 真实缺陷（取消留半截态），但保守回滚条件+走 StateManager |
| L3 | 工具批串行 | **改（受限、默认开关）** | 仅连续 risk=low 只读并行，闸机仍按序，后置批 |
| L2 | 无显式反思 | **不改** | 已有三重机械审计；新增 critic 触 prompt 预算；登记未清偿清单 |
| L4 | 静态步预算 6 | **不改默认值** | `settings.max_steps` 已可 env 覆盖，撞限有"继续完成"按钮；属成本刻意取舍 |

## 2. 本窗口实际完成情况

| 批次 | 内容 | 状态 | commit | 验收 | 备注 |
|---|---|---|---|---|---|
| 第 0 步 | 交接文档骨架 | ✅ | `bed84d9` | pre-commit 通过 | |
| 批 1 | 工具表面修正（T6/T7/T1/T8） | ✅ | `464e0b3` | 定点 136 passed；`--quick` 退出码 0 | 新增 `canvas_read_prompt_max_chars`(2000)/`canvas_asset_page_size`(50) 入 config |
| 批 3 | 结构化错误轴（T5） | ✅ | `83940db` | 定点 159 passed；`--quick` 退出码 0；`gen_api_types --check` 退出码 0 | 见下方批 3 完成说明 |
| 批 2（可选） | 闭集枚举最小子集（T3） | 未启动 | — | — | 仅当余量 <75 次且批 1/3 全绿 |

### 批 3 完成说明（T5 结构化错误轴）

**立轴**：`tools/base.py::ToolResult` 新增 `error_code: str = ""`、`retryable: bool = False`（带默认值，既有构造零影响）。口径集：`validation`/`exception`/`upstream`/`timeout`/`canvas`/`other`，与 `core/fc_feedback.classify_tool_failure` 对齐；空串=未标注，消费端回落文本分类。

**生产端标注**：
- `tools/manager.py`：入参校验失败=`validation`；未捕获异常兜底=`exception`。
- `tools/vision/generate_image.py`：未配置供应商=`validation`；上游明确失败=`upstream`+retryable=True；异常兜底=`upstream`。
- `tools/video/generate_video.py`：未配置供应商=`validation`；跨厂商降级链耗尽/不可重试错误=`upstream`+retryable=False。
- `tools/document_tools.py`（image_generate 生成段）：开关关闭/无可用供应商=`other`；目标未命中草稿=`validation`。
- `tools/canvas_tools.py`（写路径）：update/delete 节点不存在=`canvas`。

**消费端接入（做到哪一步）**：
- ✅ `core/fc_feedback.compose_failure_feedback` 新增可选参 `error_code`/`retryable`（旧签名兼容）：已标注时 error_code 直接作分类前缀，按 validation/可重试/canvas/other 微调重试建议；二次失败升级逻辑不变。`fc_tool_runner` 失败分支已透传（getattr 兼容测试 stub）。
- ⏩ **顺延**：`core/recovery_policy.py` 未接入——分派表只认循环级失败类型键（bad_output/tool_failure/…），不认单工具 error_code，无自然消费位置，强行接入会扩大耦合。待批 6（检查点/回滚）需要按错误码判定回滚条件时一并接入更自然。
- ⏩ **顺延**：`format_tool_results` 回喂消息体未携带 error_code（仅经 compose_failure_feedback 间接生效），前端/回喂面如需展示再补。

**坑与修法**：
1. hint 分支初版把「不宜盲重试」给了除 exception 外所有已标注码，撞既有断言 `test_adapter_stream_protocol.py`（文本分类 output_format 首败必须仍可给「重试一次」提示）——收窄为仅 `canvas`/`other` 生效。
2. **措辞微变风险点**：文本分类回落码 `other` 现在也走「不宜原参盲重试」文案（旧为「可调整参数后重试一次」）；下个窗口跑 `--with-eval` 若发现模型重试行为异常，把该分支退回默认文案即可（单点改动）。
3. `document_tools.py` 编辑时曾误删/重复 if 行，已当场修复并经 `--quick` 全绿；修改该文件时注意 image_generate 的多个 `if not provider_id` 链。

## 3. 未完成批次操作手册

**依赖顺序**：批4 依赖批2/3 → 批5 依赖批3/4 → 批6 依赖批3/5 → 批7 依赖批6。
开工前先补批 0 基线：建备份分支 + `python scripts/acceptance.py --with-eval`（本窗口未跑，省预算）。

### 批 2 · 闭集枚举进 Schema（T3）

1. `src/video_agent/tools/storyboard_tools.py` 约 L24：`group_type` 入参 → `Literal["keyElement","shot","audio"]`。
2. `src/video_agent/tools/canvas_tools.py` 约 L32 与 L298（`CanvasAddNodeInput.node_type`、`CanvasBatchNodeInput.node_type`）→ Literal 四值 `"smart-image" | "smart-prompt" | "text" | "image"`。
3. 混合集 `target`（image_generate 的 target 参数）**不动**，留给批 4 连同写类入参硬化一起做成"校验+结构化报错"。
4. 注意拒收语义变化：枚举拒收属行为变化，须跑 `python scripts/run_eval_pipeline.py` 核对黄金语料。
5. 验收：定点测试 + `acceptance.py --quick`；独立 commit。

### 批 4 · 写类入参硬化两步走（T2）— 第一步"错误可见"

1. 定位写类工具入参 Schema（`tools/storyboard_tools.py` / `tools/document_tools.py` / `tools/canvas_tools.py` 的写类 Input）。
2. 第一步只做**未知字段可见报错**：Pydantic v2 校验失败路径在 `tools/manager.py` 验证失败分支填 `error_code="validation"`（批 3 已铺路），错误信息列出被丢弃字段名。
3. **不要**本步加 `model_config = ConfigDict(extra="forbid")`——那是第二步，须先过 `run_eval_pipeline.py` 评测核对，评测通过后再收紧。
4. 混合集 `target` 的校验+结构化报错在此批完成（复用批 3 的 `error_code`）。
5. 验收：定点测试 + `--quick` + `run_eval_pipeline.py`；独立 commit。

### 批 5 · 幂等键（T4，轻量）

1. 写类工具入参加**可选** `idempotency_key: str = ""`（默认空=不去重，向后兼容）。
2. 去重账本放轮内（新模块，勿塞进 `fc_tool_runner.py`）：同轮同键重复调用直接返回首次结果。
3. 单一事实源纪律：账本生命周期随轮，不持久化进 StateManager 状态。
4. 验收：定点测试 + `--quick`；独立 commit。

### 批 6 · 批级检查点+条件回滚（L1）

1. 新模块实现（`fc_tool_runner.py` 已近行数棘轮，禁止继续膨胀）。
2. 批执行前经 **StateManager**（Rule 3 唯一写入点）打状态检查点；批内失败按**保守条件**回滚。
3. **不得沿用** `turn_commit` L108/L153-154 的 `state.clear(); state.update()` 直接字典改法。
4. 回滚边界：外部副作用（生成任务/画布写入/文件落盘）**不可回滚**，回滚条件须排除已产生外部副作用的批。
5. 须配集成测试（高风险批）；验收：定点 + `--quick` + 批末全量；独立 commit。

### 批 7 · 只读受限并行（L3，后置）

1. 仅连续 `risk=low` 只读工具批内并行；闸机仍按序拦截；写类/高危仍串行。
2. 默认开关入 `config.py` settings（可一键关回串行）。
3. 依赖批 6 的检查点/回滚就位后再做。
4. 验收：定点 + `--quick` + 批末全量；独立 commit。

## 4. 已知坑点清单

1. `fc_tool_runner.py` 已 687 行，逼近行数棘轮，且 L458-473 消费原始 args dict——批级新逻辑一律落新模块，不要在此文件加逻辑。
2. 字段白名单唯一事实源 = `state/storyboard_ops.py::ALLOWED_DRAFT_FIELDS/GROUP_FIELDS`（L25-35），校验器只能**引用**，禁止复制（P1）。
3. `turn_commit` L108/L153-154 是 `state.clear(); state.update()` 直接字典改法，批 6 的回滚**不得沿用**，必须走 StateManager 接口。
4. T2 两步走纪律：先"错误可见"并跑评测，通过后才允许 `extra="forbid"` 收紧；不得一步到位。
5. 批 6 回滚边界：外部副作用（生成/画布写/文件）不可回滚，保守回滚条件必须排除。
6. `document_write`（工具）与 `write_document`（action_executor 的动作名）是两个不同名字，T6 只改 `read_project_doc` 描述里的失效引用，别把两者混淆。

## 5. 治理红线速查

- **零新增**闸机/门禁/注册表（GOVERNANCE §13.14(f) 门禁冻结，现有 18 条）。
- 规则只有一个家（P1）：不在事故现场就近补条款。
- 约束下沉（P2）：能代码机械校验的不写 prose；拒收/枚举/幂等走 Pydantic/工具层，**不进 `gate_registry`**。
- 提示词外置（Rule 6）；不动 `data/skills/*`（G1）；不改画布项目文件（Rule 7）。
- 可调参数一律入 `config.py` settings，禁止硬编码；禁止方法内新增 import（顶部 import）。
- 状态写入归 StateManager（Rule 3）；每批独立 commit、独立过 `--quick`；回退用 `git revert`，禁裸 restore/checkout（宪法 §5）。

## 6. 验证命令

```bash
# 定点（只跑受影响文件）
python -m pytest tests/unit/<相关> -q -n 8 --dist loadfile

# 日常验收（唯一依据，只认进程退出码 0，不人眼读输出）
python scripts/acceptance.py --quick

# 批末全量（四件套）
python scripts/acceptance.py

# 拒收类改动（批 2/批 4）加跑
python scripts/run_eval_pipeline.py

# 批 3 契约核对
python scripts/gen_api_types.py --check
```

## 7. 续做第一步

1. 建备份分支（宪法 §5：开工先备份）。
2. 补跑批 0 基线：`python scripts/acceptance.py --with-eval`（本窗口省预算未跑）。
3. 从**批 4**开始（若批 2 未做，连同批 2 未做部分一起）；依赖顺序见 §3。

## 8. 计划文件路径索引

`C:\Users\ASUS\AppData\Roaming\Qoder\SharedClientCache\cache\plans\对齐一线_Agent_循环与工具_25e98abd.md`
