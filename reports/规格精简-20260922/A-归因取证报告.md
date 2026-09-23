# A · 「为了效率」归因取证报告

- 取证对象：项目「9999」= `proj-1790055373-bf5a358b`（主会话 `workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl`）
- 取证问题：主会话第 6 行「其实为了效率，可以一次性问：①输出语言偏好。」这四个字的**归因**
- 取证方式：**只读**。未修改 `src\`、`prompts\`、`data\skills\` 或任何 Skill 文件；写入仅限 `reports\规格精简-20260922\`
- 报告日期锚点：9999 本轮时间戳 `1790055387.3075633` = **2026-09-22T05:36:27Z**（= 北京时间 13:36:27，与 `logs\agent-20260922.log` L139 的 `[AgentTask] created task_id=agt-1790055387-fe10a29c project=proj-1790055373-bf5a358b` 对齐）
- 检材完整性：`git status --porcelain` 仅 `?? .agent-teams/`、`?? reports/`，工作树干净；HEAD = `6b618d9`（2026-09-22 13:31:52 +0800）

---

## 0. 一句话结论（先给答案）

**「为了效率」属于候选④（模型自主裁决），且判为"模型自发口语化用语"而非"对某条指令的复述"。**

- `prompts\**` 与 `src\video_agent\**` 对「**效率**」「**一起问**」「**打包**」「**预收**」**四词全部零命中**（0 行 / 0 文件）；「一次性」46 行、「合并」67 行**全部是工程语义**，无一句是"合并向用户提问"的指令 → **候选①②③ 均不成立**。
- 该四字为**逐字节流生成**的产物：令牌流中「其实为了」与「效率，可以一次性问：」分属相邻两个 chunk，**任一 delta 内部都不含完整四字**；而拼接结果与 jsonl 落盘的 `reasoning_content` **长度与内容完全相等**（均 1627 字符）。
- 同一用语在 **20 个会话文件 / 17 个项目 / 2026-09-09 → 2026-09-22** 的推理过程里反复出现，语境各异（并行读章节、建组附带草稿、抽查 2–3 个、用 JSON 字符串传参…），**无任何共有指令可解释该分布**。
- **本条的实际因果恰恰相反**：该句所在的决策是「**减少**提问」——同段先写「不，保持简洁，按启动协议只问语言」；落地行为（`LINE 8` 的 `workflow_pause`）选项只有 **中文/英文/双语**，**没有**画幅/时长/风格。把它当作"平台下发了合并提问指令"的证据，会得到与行为相反的结论。

---

## a) 「为了效率」出现位置复核（原始 jsonl 逐行 + 逐字原文 + 上下文）

### a.1 出现位置（唯一两处，均在同一个 step 内）

| 序 | 文件 | 行号 | 记录类型 | 字段名 | 逐字原文（该句） |
|---|---|---|---|---|---|
| 1 | `workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl` | **第 6 行**（`seq=6`） | `assistant/partial` / `kind=reasoning` / `step=1` | `text`（len=471） | `其实为了效率，可以一次性问：①输出语言偏好。之后委派 script_analyze。` |
| 2 | 同上 | **第 8 行**（`seq=8`） | `assistant/message` / `step=1` | `reasoning_content`（len=1627） | 同上（同一自然段，偏移 1285..1327） |

在 `LINE 6.text` 内该句的字符偏移为 **129..171**；在 `LINE 8.reasoning_content` 内为 **1285..1327**。

**全库"这四个字"的写死位置（供反证，非注入证据）**：`prompts\**`、`src\video_agent\**`、`data\**`、`scripts\**`、`static\**` 全部 **0 命中**；全仓仅 3 处，且**均非注入源**：
- `tests\unit\test_prompt_relocation_batch3.py` **L139** —— 测试注释（自述留痕）
- `docs\指令混乱审计报告-20260920.md` **L74、L75、L193** —— 审计报告（自述留痕）

按验收口径 4，以上 3 处**不充当注入证据**，仅作线索；本报告所有结论均回到原始 jsonl / 运行时代码 / 运行时刻落盘的 SSE 捕获复核。

### a.2 前后各 ≥5 行上下文（原始 jsonl 第 1–11 行，字段级）

> 说明：jsonl 共 62 行；`LINE 1..11` = 第 1 个 turn（`turn=1`）全过程。

| 行号 | 类型 | 关键字段（逐字/摘要） |
|---|---|---|
| 1 | `log/imported` | `{"seq":1,"type":"log/imported","time":1790055387.3075633,"source":"chatMessages","count":0}` |
| 2 | `turn/start` | `{"seq":2,...,"turn":1}` |
| 3 | `user/message` | `source="user"`，`content="AI-短剧一站式生成"`（len=10） |
| 4 | `user/message` | **`source="state"`**，`content` len=1020：工作台状态 JSON + 执行偏好注 + UNAVAILABLE 段（**见 §d**） |
| 5 | `assistant/partial` | `step=1, kind="reasoning"`，`text` len=1156，**开头**：`用户上传了《三体简短版.md》并触发「AI-短剧一站式生成」Skill。当前工作台状态：没有 keyElements、shots、audioItems，只有上传的素材文档。` **结尾（未闭合）**：`另外也许可以同时确认其他启动信息，比如当前阶段（` |
| **6** | **`assistant/partial`** | **`step=1, kind="reasoning"`**，**`text` len=471，逐字全文见 §a.3** |
| 7 | `assistant/partial` | `step=1, kind="text"`，`text` len=57：`收到《三体简短版.md》素材，工作台当前为空，本片从零开始。按 Skill 启动协议，先与你确认最后一项启动参数：` |
| **8** | **`assistant/message`** | `step=1`；`content` len=57（同 LINE 7 逐字）；`tool_calls=[workflow_pause]`；**`reasoning_content` len=1627**；`usage={"prompt_tokens":10222,"cached_tokens":0,"completion_tokens":11358}` |
| 9 | `tool/result` | `name="workflow_pause"`，`content="（系统）本轮调用的工具已执行完毕，结果如下：\n- workflow_pause：执行成功"` |
| 10 | `step/feedback` | `step=1, tool_count=1` |
| 11 | `turn/end` | `turn=1, reason="done"` |

`LINE 8` 的 `tool_calls` 逐字：

```
{"header": "启动确认", "question": "本片的输出语言偏好用哪种？",
 "message": "已收到上传剧本《三体简短版.md》（1197 字），本片将从零开始推进：剧本分析 → 制片规格 → 故事板 → 生成。请先确认输出语言偏好，其余信息齐全后我会立即开始剧本分析。",
 "options": [{"label":"中文",...},{"label":"英文",...},{"label":"双语",...}]}
```

### a.3 `LINE 6` 的 `text` 字段逐字全文（471 字符）

```
从零开始，这个从工作台状态就能看出，不用问）。素材已有（已上传）。

所以只需问语言偏好。同时可以问一下是否有额外要求？不，保持简洁，按启动协议只问语言。

也许还可以问用户是否需要引导散文体识别——不，先问语言，然后委派 script_analyze。

其实为了效率，可以一次性问：①输出语言偏好。之后委派 script_analyze。

按 Skill 流程纪律第 6 条，暂停必须调用 workflow_pause。启动协议要求确认信息后再推进，所以现在应该 pause。

让我构造 workflow_pause：
- question: 「输出语言偏好是用中文还是英文？」
- options: 中文（成片与提示词以中文为主）、英文（遵循 Skill 档案声明，提示词默认英文）

其实提示词语言遵循档案声明（英文），用户选择优先。所以选项：中文 / 英文。

header: 「启动确认」
detail 简短说明：工作台当前为空，从零开始；已收到《三体简短版.md》。

然后等待用户回复后委派 script_analyze。
```

### a.4 `LINE 6`（思考流分片）与 `LINE 8`（思考全文）的关系 —— 已机械验证

**关系判定：`LINE 6.text` 是 `LINE 8.reasoning_content` 的一个"流式增量分片"，二者是同一段思考的"分片"与"拼接全文"，且切分点是任意的（不落在句界）。**

验证结果（脚本 `_probe_concat.py`）：

```
len(line5.text)      = 1156
len(line6.text)      = 471
len(line8.reasoning) = 1627
a+b == rc ?            True      # 1156 + 471 = 1627
rc.startswith(a) ?     True
rc.endswith(b) ?       True
「为了效率」出现在 raw LINE 6 与 raw LINE 8；全 jsonl 共 2 次
```

**更强一级的独立复核（运行时刻落盘的 SSE 捕获）**：

检材 = `data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl`
（文件名前缀 `1790055387` 即本轮时间戳；`__header__.ts=1790055387.3731172`，`model=deepseek-v4-flash-0731`，`messages_n=3`，`tools_n=24`）

| 检验项 | 结果 |
|---|---|
| 该文件全部 `delta.reasoning_content` 拼接长 | **1627** |
| 与 jsonl `LINE 8.reasoning_content` 长 | **1627** |
| **两者是否完全相等** | **True** |
| `LINE 5.text`(1156) 在拼接串中的范围 | `[0, 1156)`，切点落在 delta#206（`'比如当前阶段（'`）**内部** → 切分不落句界 |
| 「为了效率」在拼接串中的位置 | 下标 **1287** |
| 覆盖该四字的 delta | delta#233 = `'_analyze。\n\n其实为了'`（`[1274,1289)`）与 delta#234 = `'效率，可以一次性问：'`（`[1289,1299)`） |
| **任一 delta 内部是否含完整"为了效率"** | **0 个**（逐字节流生成，四字跨 delta 边界） |

**结论**：`LINE 6` 与 `LINE 8` 的关系是**「同一次 LLM 响应的思考流分片」与「该响应的最终思考全文」**：
- `assistant/partial`（`kind=reasoning`）由 `session_log` 在流式过程中按**固定字符阈值**切分落盘 —— `src\video_agent\core\session_log.py` **L505**：`PRUNE_THRESHOLD_CHARS = 8192   # 超过即修剪（合并文本码点数）`（此处为流式分片阈值族）；同理 `LINE 5`(1156)+`LINE 6`(471) 的合并即 `LINE 8`。故分片边界由**长度**决定（1156 与 471 都不是句子长度），不是语义切分。
- `LINE 8` 的 `reasoning_content` **不是**新的生成，而是把同一响应的全部思考 delta 拼接后**重复落一次**（`session_log.py` **L246-253** 迁移段记明 `reasoning_content 透传`）。
- 因此 **「为了效率」在同一 step 内只生成了一次**（不是模型说了两遍），两行只是同一事实的两种落盘形态。

---

## c) 全库（`prompts\` + `src\video_agent\`）逐词检索 —— 逐文件逐行

检索范围：`prompts\`（19 个文件）、`src\video_agent\`（含 `__pycache__` 以外全部 `.py`），扩展名 `.md/.py/.txt/.json/.yaml/.yml/.toml`，排除 `__pycache__/.git/node_modules`。

### c.1 逐词命中统计（精确）

| 检索词 | 命中行数 | 涉及文件数 |
|---|---|---|
| **效率** | **0** | **0** |
| 一次性 | 46 | 29 |
| **一起问** | **0** | **0** |
| **打包** | **0** | **0** |
| **预收** | **0** | **0** |
| 合并 | 67 | 33 |

### c.2 逐条：文件 + 行号 + 逐字行

**「一次性」在 `prompts\`（3 行，全部为工程/流程语义）**

| 文件 | 行号 | 逐字行 |
|---|---|---|
| `prompts\planner\adjust.md` | **8** | `5. 子对话内不发起确认，直接执行：不要调用暂停/确认类动作等待用户回应，按用户指令一次性完成调整并直接回复结果。` |
| `prompts\planner\skill_runtime.md` | **14** | `6. 多步任务按批次推进：…**思考同样分批**：每批只在思考里构思本批 3~5 张，随想随写，不要在思考里预先起草全部分镜提示词再逐批誊写（一次性巨量思考会拖慢第一批落盘，中断即全丢）。不要一次响应生成全部角色/场景/分镜的完整参数（单次输出体量过大会显著拖慢每步响应，且中断时没有已落盘的部分成果）。` |
| `prompts\planner\subagent.md` | **59** | `你是被委派的子代理（一次性任务）：你的权限范围在启动时已固定…` |

**「一次性」在 `src\video_agent\`（43 行，全部为工程语义）** —— 全部命中清单（文件 : 行号）：

```
src/video_agent/config.py : [374]
src/video_agent/core/agent_loop.py : [371]
src/video_agent/core/fc_tool_runner.py : [719]
src/video_agent/core/gate_registry.py : [31]
src/video_agent/core/guard_pipeline.py : [269]
src/video_agent/core/model_policy.py : [86]
src/video_agent/core/planner.py : [589, 775, 807, 1109]
src/video_agent/core/planner_gate_session.py : [3, 19, 34, 37]
src/video_agent/core/prompt_gates.py : [57]
src/video_agent/core/session_log.py : [246, 253]
src/video_agent/core/subagent.py : [5]
src/video_agent/core/workflow_runtime.py : [193, 304]
src/video_agent/state/context_builder.py : [219]
src/video_agent/state/manager.py : [458, 461]
src/video_agent/state/repository_sqlite.py : [11, 22, 67, 107, 246]
src/video_agent/state/save_ops.py : [173]
src/video_agent/tools/analysis_tools.py : [14]
src/video_agent/web/agent_task_manager.py : [29, 93]
src/video_agent/web/chat_opening.py : [319]
src/video_agent/web/chat_service.py : [134, 787]
src/video_agent/web/routes/agent.py : [101]
src/video_agent/web/routes/project.py : [396, 473]
src/video_agent/web/routes/runtime_settings.py : [283]
src/video_agent/web/skill_docs.py : [46]
src/video_agent/web/sse_conn_diag.py : [19]
src/video_agent/web/task_manager.py : [25, 57]
```

代表性逐字行（说明其语义域，均与"合并提问"无关）：

- `src\video_agent\state\save_ops.py` **L173**：`"""防抖任务：窗口过后把脏状态一次性落盘（失败仅记录，下次变更会再触发）"""`
- `src\video_agent\state\repository_sqlite.py` **L22**：`① 首次启用且 DB 为空 → _auto_migrate_from_json 一次性导入；`
- `src\video_agent\core\guard_pipeline.py` **L269**：`- 用户「本次放行」（gate_overrides 单次消费）= 一次性同意；`
- `src\video_agent\tools\analysis_tools.py` **L14**：`尾，对齐 flova「分析一次性使用 + 历史衰减」）：state.analysis 仅作探针/`
- `src\video_agent\web\skill_docs.py` **L46**：`# 它们的运行时把各节分别注入对应阶段的子工具；本系统把全文一次性注入单一编排模型，`

**「合并」在 `prompts\`（1 行）**

| 文件 | 行号 | 逐字行（节选，全文见源） |
|---|---|---|
| `prompts\planner\feedback.md` | **65** | `…不要逐字照抄，保留仍属实的事实、丢弃已过时内容，将新旧信息合并为单一摘要。` |

（该行属**历史压缩摘要**指令，与"合并向用户提问"无关。）

**「合并」在 `src\video_agent\`（66 行）** —— 全部命中清单（文件 : 行号）：

```
src/video_agent/adapters/factory.py : [92]
src/video_agent/adapters/infinite_canvas_backend.py : [811]
src/video_agent/core/action_descriptions.py : [109, 111]
src/video_agent/core/fc_response.py : [1, 3]
src/video_agent/core/fc_tool_runner.py : [606]
src/video_agent/core/gate_registry.py : [73]
src/video_agent/core/pause_composer.py : [211]
src/video_agent/core/planner.py : [860]
src/video_agent/core/planner_output.py : [4, 113]
src/video_agent/core/session_log.py : [505, 766, 767, 900]
src/video_agent/core/stage_probes.py : [41]
src/video_agent/core/turn_executor.py : [106]
src/video_agent/core/workflow_runtime.py : [270]
src/video_agent/state/board_merge.py : [2, 9, 11, 22, 105, 152, 174]
src/video_agent/state/conversation_ops.py : [274, 588]
src/video_agent/state/manager.py : [403, 515, 685]
src/video_agent/state/models.py : [220]
src/video_agent/state/save_ops.py : [4, 23, 85, 156]
src/video_agent/state/storyboard_ops.py : [48, 251]
src/video_agent/tools/base.py : [10]
src/video_agent/tools/document_tools.py : [211, 266, 274]
src/video_agent/tools/storyboard_tools.py : [44, 206, 218]
src/video_agent/tools/web_tools.py : [58, 207, 234]
src/video_agent/utils/provider_config_loader.py : [77, 87, 97]
src/video_agent/web/generation_submit.py : [311, 336]
src/video_agent/web/multimodal_builder.py : [273, 288]
src/video_agent/web/providers.py : [24]
src/video_agent/web/routes/assets_library.py : [192]
src/video_agent/web/routes/config.py : [59]
src/video_agent/web/routes/project.py : [406, 407, 418, 433]
src/video_agent/web/skill_docs.py : [100]
src/video_agent/web/task_manager.py : [182, 188, 190]
```

代表性逐字行（六个可归类的语义簇）：

- 落盘防抖合并：`state\save_ops.py` **L4** `防抖合并落盘（高频路径不阻塞事件循环）、磁盘账本读取与陈旧重载。`
- 故事板三向合并（G1）：`state\board_merge.py` **L174** `"""三向合并四类别；返回 (合并结果, 冲突清单)。冲突清单空 = 可直接落盘。"""`
- 结果/文本合并：`tools\web_tools.py` **L207** `"""多 query 结果合并（dsh mergeSearchResults 同构）：url 去重、`
- 文档节级合并：`tools\document_tools.py` **L211** `"""规格文档节级合并（R14，纯函数）：按 `## ` 标题切块后合并 old/new。`
- 事件卡展示合并：`core\action_descriptions.py` **L109** `用户不需要逐条看到每张卡片：连续同类操作合并为一条，`
- 闸机/裁剪集合并：`core\gate_registry.py` **L73** `# GATE_MESSAGE_SECTIONS 合并后覆盖 messages.md 全部 ## KEY 分节（消除孤儿），`

**另附：相邻近义指令词复核**（补强"平台未下发合并提问元指令"）

| 检索词 | `prompts\` 命中 | 说明 |
|---|---|---|
| `问全` / `一起问` / `一次问询` / `一并询问` / `批量问` | **仅** `prompts\planner\protocol.md` **L13** 的 `到规格阶段一并写入即可` | 指**落盘时机**（规格文档写到规格阶段一并写入），**不是**"把问题合并一次问用户" |
| `互相独立的委派放同一条消息一起发` | `prompts\planner\subagent.md` **L56** | 属**委派轴**（多个子代理同批发），非"向用户提问"轴 |
| `不跨阶段预收` | **0**（当前工作树） | 曾存在于 `prompts\shared\iron_rules_header.md` L3，已于 `4231a93`（2026-09-20）删除 |

### c.3 明确结论：平台侧是否存在「合并提问」指令？

> **不存在。**
> 1. 四个直接指向"合并提问"的词（**效率 / 一起问 / 打包 / 预收**）在 `prompts\` 与 `src\video_agent\` **合计 0 命中**。
> 2. 唯一被检索到的、曾经**显式允许**"合并问"的平台句 = `docs\冻结与暂缓清单.md` **第 16 条**（2026-09-08 用户裁决）里的「**平台侧以"缺项合并一次问询"收口**」；该句是**裁决留痕**（非注入文本），且已于 `4231a93`（2026-09-20）**部分翻案删除**（现文本见 `docs\冻结与暂缓清单.md` **L25**，保留"删句"说明）。
> 3. 唯一曾经**显式禁止**"合并问"的平台**注入**句 = `prompts\shared\iron_rules_header.md` **L3** 的「**不跨阶段预收**」，已于同一批删除（现 `L3` 逐字：`【冲突与缺信息处置】信息缺失且**该信息所属的产出阶段** Skill/流程要求询问 → 先问再做，不擅自补全；…`）。
> 4. 故 9999 运行时刻（2026-09-22，双删批之后）平台在"要不要合并问"这条轴上**两个方向都没有下发任何元指令**——本条的四个字因此不可能来自平台侧的写死文本。

---

## b) 四条候选来源逐条结论

### 候选① 平台提示词文件写死（`prompts\**`，含 planner/shared/gates）

**结论：不成立。**

| 证据 | 位置 | 内容 |
|---|---|---|
| 逐词零命中 | `prompts\` 全库 | 「效率」0 行 / 0 文件；「一起问」0；「打包」0；「预收」0 |
| 唯一「一次性」3 行均非提问轴 | `prompts\planner\adjust.md`:8、`prompts\planner\skill_runtime.md`:14、`prompts\planner\subagent.md`:59 | 分别指"一次性完成调整"、"一次性巨量思考"、"一次性任务（子代理）" |
| 唯一「合并」1 行非提问轴 | `prompts\planner\feedback.md`:65 | 历史压缩摘要合并 |
| 回复/提问纪律的正向表述 | `prompts\planner\protocol.md`:7 | 只规定"过程中的说明 = 1~2 句有信息的进展"，**不含**"合并提问" |
| 平台闸机文案 | `prompts\gates\messages.md`（全文 55 行） | 全部为拦截/暂停/配额文案，无一句涉及"合并提问" |
| 已退役/已删除的历史源 | `prompts\shared\iron_rules_header.md` L3（`4231a93^` 版本） | 曾写「不跨阶段预收」= **禁**合并，与本条方向**相反**；且该行在 9999 运行前已删 |

补充：`LINE 4`（`source=state`）作为**被本检材直接观测到的唯一注入文本**，其全文实测**不含**「效率」二字（见 §d 的逐项核对）。

### 候选② 运行时代码注入（`src\video_agent\**` 的注入器、状态尾消息、工具 description、闸机回喂文案）

**结论：不成立。**

| 注入面 | 代码位置（文件:行号） | 是否含"合并/一次性提问"指令 |
|---|---|---|
| 状态尾消息装配 | `src\video_agent\core\prompt_builder.py` **L162-242**（`build_state_tail_message`） | 否（构成见 §d） |
| 执行偏好 note 加载 | `src\video_agent\core\planner.py` **L760**、**L1124-1148**（`_load_execution_pref_note`）；文案源 `prompts\planner\execution_preference.md` | 否（逐字见 §d.3） |
| 轮首状态事件落流 | `src\video_agent\core\planner.py` **L766-768**（`_build_and_log_state_event`） | 否 |
| UNAVAILABLE 段渲染 | `src\video_agent\core\prompt_builder.py` **L216-239**；文案源 `prompts\shared\turn_excluded.md` | 否（逐字见 §d.4） |
| 铁律块 | `src\video_agent\core\prompt_builder.py` **L333-354**（`build_iron_rules_block`）；`prompts\shared\iron_rules_header.md` | 否（逐字见 §d.1） |
| 工具 description（`workflow_pause`） | `src\video_agent\tools\document_tools.py` **L920-923** | 否：`"暂停工作流并请求用户确认——真正的停 = 调用本工具（只在正文里写「请确认」不算暂停）。message 是给用户的补充说明（确认卡片由系统自动生成）。"` |
| 工具 description（`run_subagent`） | `src\video_agent\tools\document_tools.py` **L982-986** | 否：只讲委派契约 |
| 工具 description（`run_subagent.stage`） | `src\video_agent\tools\document_tools.py` **L47-56**（`_stage_hint`）、**L965-968** | 否：运行时拼阶段枚举 |
| 闸机回喂文案 | `src\video_agent\core\fc_gates.py` **L136-144**（`pause_window_error`） | 否，且方向**相反**：`"本轮已用 workflow_pause 请求用户确认，请等待用户回应后再继续执行；暂停窗口内仅允许读类工具（read_*）。"` |
| 闸机回喂文案族 | `src\video_agent\core\gate_registry.py` **L73**（分节覆盖表）→ `prompts\gates\messages.md` | 否 |
| 反向核验 | `src\video_agent\` 全库「效率」 | **0 行 / 0 文件** |

### 候选③ Skill 正文（`data\skills\AI-短剧一站式生成\SKILL.md`，只读）

**结论：不成立（但**是**本轮"输出语言偏好"这一问的直接来源——注意区分"问题来源"与"这四个字的来源"）。**

| 证据 | 位置 | 内容 |
|---|---|---|
| 四词零命中 | `data\skills\AI-短剧一站式生成\SKILL.md` 全文 281 行 | 无「效率」「一起问」「打包」「预收」 |
| 「一次性」零命中 | 同上 | 全文无「一次性」 |
| 启动协议原文（**这是"问语言"的源**） | 同上 **L6-L12** | `**启动协议**` / `用户触发本 Skill 时，按顺序确认以下信息后再推进：` / `1. 当前所处阶段（从零开始，还是已有部分产出？）` / `2. 已有素材（请用户上传或粘贴现有剧本 / 分镜 / 设定图）` / `3. 输出语言偏好（征询用户；提示词语言遵循档案声明（英文），用户选择优先）` |
| **关键**：协议规定「**按顺序**确认」 | 同上 **L8** | 是"顺序确认"而非"合并确认"——**方向相反** |
| 反向表述 | 同上 **L27** | `**关键暂停点：** 每个阶段完成后必须暂停，等待用户确认再继续。绝不一口气输出全部步骤——这会让纠错成本爆炸。` |
| 该文件未改动 | `git log -- data/skills/AI-短剧一站式生成/SKILL.md` | 最后一次改动 = `8f62db2`（2026-08-31），9999 本轮（2026-09-22）之前 22 天 |
| 同库其它 Skill 亦无 | `data\skills\**` 全库 | 「效率」「一起问」「打包」「预收」0 命中（其余 Skill 的「一次性」全部是"不要一次性运行所有步骤"= **禁**合并） |

### 候选④ 模型自主裁决 / 上游模型供应商侧默认偏好

**结论：成立（归入"模型自主裁决"）。其中"供应商侧默认偏好"部分标注为「不可观测、仅可推断」。**

**④-1 模型自主裁决 —— 成立（可观测证据 4 条）：**

1. **逐字节流生成**（最高强度）：`为了效率` 四字跨 delta#233/delta#234 边界产出，**任一 delta 内部不含完整四字**；拼接串与落盘 `reasoning_content` 完全相等（1627 = 1627）。→ 该四字是模型在生成过程中**当场组织**的措辞，不是从上下文复制粘贴的片段。
   - 检材：`data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl`
2. **跨项目独立复现**（分布证据）：全库 **20 个会话文件 / 17 个唯一项目**命中「为了效率」，时间跨度 **2026-09-09 → 2026-09-22**（14 天，跨 3 个平台治理批次、5 次以上提示词改动）。语境各异：

   | 项目 | 行号 | 上下文（节选） |
   |---|---|---|
   | `proj-1788943704-feea238d` | 70 | `为了效率可以每批 4-5 个：批1 = shot01-04（4个）…` |
   | `proj-1789128804-70253439` | 28 | `不过为了效率，可以把 keyElement 描述让子代理起草？` |
   | `proj-1789193562-de038b0c` | 18 | `为了效率，我可以把角色外貌作为一个 group…` |
   | `proj-1789222719-25a3c93d` | 15 | `不过为了效率，我可以一次读多个章节（同一批并行调用 read_skill）。` |
   | `proj-1789233869-aaae8f49` | 19/22 | `为了效率，我可以并行读取多个章节：script_analyze、…` |
   | `proj-1789270505-dd6fa847` | 12/14/22/25/84/94 | `但为了效率，也可以在启动确认时稍带` / `为了效率，我先读 script_analyze 和 storyboard 章节` |
   | `proj-1789295844-0e31d9f6` | 50/53 | `为了效率，建组时直接附带 draft（…）也行——draft 是合法参数。` |
   | `proj-1789354793-12313746` | 60/61 | `其实为了效率，一轮 5 个：…` |
   | `proj-1789383419-e9a093c5` | 72/75 | `不过为了效率与尊重用户参与感，也可以在拆完 shots 后统一暂停。` |
   | `proj-1789396735-85750d0f` | 40/43 | `为了效率：建组时同时给每个元素配一个带基础提示词的草稿？` |
   | `proj-1789575306-62266c0d` | 56/61 | `实际上，为了效率，我可以在这批同时读 audio 章节。` |
   | `proj-1789839470-bbbc8d91` | 12/15 | `但为了效率，可以在第一次暂停时一并征询制片规格关键参数（画幅、时长、风格）` |
   | `proj-1789905023-700e1014` | 5/8/11/14 | `为了效率，先读文档再说。` / `为了效率，我可以在启动确认里同时询问关键决策…` |
   | `proj-1790000744-854e9342` | 23/25 | `为了效率，先委派 script_analyze（不依赖画幅时长）…` |
   | `proj-1790001324-542fcdec` | 34/36 | `不过为了效率，也可以本批 document_write + run_subagent(key_elements)。` |
   | `proj-1790004483-ceefb1a0` | 11/19 | `为了效率与合规，我采用：角色 keyElement 卡的 desc 中附 Voice 段…` |
   | **`proj-1790055373-bf5a358b`（9999）** | **6/8** | **`其实为了效率，可以一次性问：①输出语言偏好。之后委派 script_analyze。`** |

   这些语境横跨"并行读章节 / 建组附带草稿 / 抽查 2-3 个 / 用 JSON 字符串传参 / 减少轮次 / 合并暂停"，**没有任何一条共有平台指令能解释这种分布**。
3. **平台侧检索反证**：若该用语来自平台，则必须在 `prompts\` 或 `src\video_agent\` 找到来源；实测「效率」**两处均 0 命中**（§c.1）。
4. **模型自述归因亦有漂移**（旁证模型在自行组织措辞与归属）：同一会话内，
   - `LINE 20/23` 把 `分析结论标注为待用户补充的项，须经确认卡片向用户追问取得，不得代为填写或虚构。` 记作「**按执行铁律**」——该句真实源 = `prompts\planner\protocol.md` **L7**（不在 `iron_rules_header.md`）。
   - `LINE 31/34` 把 `互相独立的委派放同一条消息一起发；…` 记作「**Skill 流程纪律说**」——该句真实源 = `prompts\planner\subagent.md` **L56**（不在 `skill_runtime.md` 的 `DISCIPLINE` 分节）。
   - `LINE 34` 把 `未确认的创作选择不得写成既定规格，须先向用户确认或标作待定。` 记作「**执行铁律③**」——真实源 = `prompts\planner\protocol.md` **L13**。
   → 说明模型引述平台文本时**会自行归类改写**；「其实为了效率」同属这类自组织措辞。

**④-2 供应商侧默认偏好 —— 「不可观测、仅可推断」。**

- **不可观测**：本 run 无任何可直证供应商侧系统提示词的检材 ——
  - 会话 jsonl 只有 8 种记录类型（`log/imported`/`turn/start`/`user/message`/`assistant/partial`/`assistant/message`/`tool/result`/`step/feedback`/`turn/end`），**无 `system` 字段、无请求体落盘**；
  - `data\sse_capture\sse-1790055387-*.jsonl` 只录**响应侧**（`__header__` 仅含 `model/base_url/messages_n=3/tools_n=24/max_tokens/stream`，其余 350 条为 `__chunk__`，末条 `__footer__`），**不含请求 payload**；
  - `src\video_agent\core\tracer.py` 只记 `prompt_fingerprints`（`fingerprint_messages`，L34/L528-546），**记指纹不记正文**；
  - `data\sse_capture` 中本轮只有一个文件 `sse-1790055387-442383df`，与 `messages_n=3` 一致，无第二份可交叉的请求快照。
- **仅可推断**：`__header__.base_url = "https://tokenrhythm.studio/v1"`、`model = "deepseek-v4-flash-0731"` —— 供应商侧是否附带系统提示词、附带何种措辞，**本仓库无检材可判**。任何把「为了效率」归到供应商默认偏好的断言，**只能标注"不可观测、仅可推断"，且本报告不采纳**：因为④-1 已用可观测证据（逐字节流 + 跨项目分布 + 平台零命中）充分解释，无需引入不可观测项。

---

## d) 9999 该轮模型**实际被注入的独立指令源**逐条清单（文件 + 行号），并与 `LINE 4` 逐条核对

### d.0 注入通道总览（代码事实）

`src\video_agent\core\prompt_builder.py` **L8-10**（模块 docstring）逐字：

```
逐轮变化的状态上下文（状态 JSON/工具边界说明/故事板客观进度）不占
system 段，经 build_state_tail_message 以 history 尾部消息（user 通道）
每步注入——system 段（含 Skill 块）成为跨步稳定前缀（供应商 KV-cache 友好）。
```

→ 本仓库存在**两条物理注入通道**（这是 §e 判据的基础）：

- **通道 A · system 段**：`build_system_prompt`（L93-160），按 `PROMPT_SECTIONS` 注册表（L721-740）按 `order` 逐段构建。
- **通道 B · history 尾部消息（role=user）**：`build_state_tail_message`（L162-242），由 `planner._build_and_log_state_event`（`core\planner.py` **L766-768**）在**轮首**落为一条 `source=state` 事件。

### d.1 通道 A 的段清单（9999 主代理轮，`subagent_depth=0`、`use_studio_context=True`）

| order | 段名 | builder（文件:行号） | 文案源（文件:行号） | 本轮是否注入 | `LINE 4` 是否含 |
|---|---|---|---|---|---|
| 10 | `protocol` | `prompt_builder.py`:569-590 | `prompts\planner\protocol.md`（全文 17 行） | 是（非子级） | **否** |
| 20 | `catalog` | `prompt_builder.py`:615-623 | `prompts\shared\skill_inject.md` + Skill manifest | 是 | **否** |
| 30 | `mcp_catalog` | `prompt_builder.py`:626-635 | 运行时 MCP 目录 | 是（无 MCP 时可能为空） | **否** |
| **40** | **`iron_rules`** | **`prompt_builder.py`:638-644 + 333-354** | **`prompts\shared\iron_rules_header.md` L1-4** | **是**（项目有《执行铁律》文档 → `build_iron_rules_block` 非空） | **否**（脚本核验 `iron_rules_header.md 全文 in LINE4 == False`） |
| 60 | `global_settings` | `prompt_builder.py`:663-677 | `prompts\shared\global_settings.md` | 是（无条件注入） | **否** |
| 65 | `session_summary` | `prompt_builder.py`:593-612 | `prompts\shared\session_summary.md` | 否（本轮无 compaction，`interaction.session_summary` 不存在） | 否 |
| 80 | `adjust_discipline` | `prompt_builder.py`:651-660 | `prompts\planner\adjust.md` | **否**（`adjust_scope` 为空，核验 False） | 否 |
| 90 | `subagent` | `prompt_builder.py`:688-700 | `prompts\planner\subagent.md` **`## SUBAGENT_POLICY`（L51-56）** | 是（`subagent_enabled` 默认 `True`，见 `config.py` **L104**；`subagent_deny/depth` 为空） | **否** |
| **100** | **`selected_skill`** | **`prompt_builder.py`:680-685 + 415-455** | **`shared\skill_inject.md` 分节 + Skill 元数据头 + `prompts\planner\skill_runtime.md` `## DISCIPLINE`（L6-15）+ `data\skills\AI-短剧一站式生成\SKILL.md` `<planner>` 段（L5-37）+ 章节目录** | **是** | **否** |

`DISCIPLINE` 的**唯一注入面**（代码逐字）：`prompt_builder.py` **L441-447**

```python
# 《Skill 流程纪律》全文随选中 Skill 注入（原注入点已退役，此处为唯一注入面）
discipline = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
```

### d.2 通道 B 的构成（`LINE 4` 逐条核对 —— 这是**唯一可逐字直证**的注入文本）

`LINE 4` 的 `content` 实测由 5 段按序拼接（`prompt_builder.build_state_tail_message` L182-242 的内部次序）：

| # | 段 | 文案源（文件:行号） | `LINE 4` 核对结果（逐字） |
|---|---|---|---|
| 1 | 状态 JSON | `prompt_builder.py` **L184**（`"当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + state_json`） | ✅ 命中：`当前工作台状态 JSON 如下（每轮自动刷新）：\n\n{"keyElements":[],"shots":[],"audioItems":[],…"interaction":{"awaiting_confirmation":false,…}}` |
| 2 | 降级引导段 | `prompt_builder.py` **L185-188 / 244-268**；`prompts\shared\degradation.md` | ⬜ 本轮未注入（状态 JSON 无 `degraded`/`compacted` 标志位） |
| 3 | 执行偏好 note | `prompt_builder.py` **L193-197**；加载端 `core\planner.py` **L760/L1124-1148**；文案源 **`prompts\planner\execution_preference.md` L12** | ✅ **逐字命中（不改一字节）**：`当前执行偏好：生成前确认——首次生成图片/视频前，先用 workflow_pause 向用户呈现提示词草案并请求确认；用户接受后重提的生成本轮内视为已确认，不会重复拦截。制片规格等文档与故事板/画布写入已按 2026-09-07 裁决降为 medium，直接执行、不设确认闸。也可在工作台把目标草稿标「已确认」。`<br>（档位 = `settings.execution_preference` 默认 `"confirm_before_gen"`，见 `config.py` **L241** → 分节键 `PREF_CONFIRM_BEFORE_GEN`） |
| 4 | 执行模式 note | `prompt_builder.py` **L198-203**；`prompts\planner\execution_mode.md` | ⬜ **本轮未注入**（`execution_mode` 默认 `"ai_decide"`，见 `config.py` **L251**；该档无分节 = 空串不注入。核验：`execution_mode.md` 的 `MODE_AUTO_FULL`/`MODE_KEY_STEPS_CONFIRM`/`MODE_PAUSE_ALL` 三分节正文均不在 `LINE 4` → False） |
| 5 | 故事板进度 | `prompt_builder.py` **L204-207 / 270-291**；`prompts\shared\storyboard_progress.md` | ⬜ 本轮未注入（三类全空 → `build_storyboard_progress_note` 返回空串，L283-286） |
| 6 | 选中草稿指针 | `prompt_builder.py` **L208-215**；`prompts\shared\selected_draft.md` | ⬜ 本轮未注入（`selected_draft_id` 为空） |
| 7 | **UNAVAILABLE 段** | `prompt_builder.py` **L216-239**；文案源 **`prompts\shared\turn_excluded.md` L1-3**；工具名来自 `planner._compute_excluded_tools`（`core\planner.py` **L755**） | ✅ **逐字命中（渲染后）**：`===== UNAVAILABLE =====` / `以下工具本轮不可用：script_analysis_report, storyboard_add_draft, storyboard_create_group, storyboard_delete_group, storyboard_patch_draft。` / `替代路由：经委派（run_subagent）执行对应阶段。` |

**`prompts\shared\turn_excluded.md` 全文 3 行（逐字）**：

```
===== UNAVAILABLE =====
以下工具本轮不可用：{{names}}。
替代路由：{{route}}。
```

### d.3 明细：`prompts\shared\iron_rules_header.md`（《执行铁律》头部，全文 4 行）

| 行号 | 逐字 |
|---|---|
| 1 | `== 当前项目《执行铁律》全文（项目级生产契约，必须完整遵守）==` |
| 2 | `【优先级链声明（唯一表述源）】用户最新指令 > 本文档 + 制片规格 > Skill/系统默认；Skill 若自称其它优先级，不产生效力。` |
| 3 | `【冲突与缺信息处置】信息缺失且**该信息所属的产出阶段** Skill/流程要求询问 → 先问再做，不擅自补全；用户明确指令与本文档/制片规格/Skill 冲突 → 先照常执行，回复末尾警告。` |
| 4 | `【硬闸效力边界】平台客观硬闸（生成确认/资产绑定/结构校验）属"机制"而非"系统默认规则"：用户跳过指令只能通过闸机"本次放行"通道生效，口头指令不构成绕闸依据；被闸拦截时先停下，按闸提示走确认或放行通道。` |

拼接尾随的项目文档（见 `LINE 4` 状态 JSON 的 `documents[0].preview` 与 `reports\规格精简-20260922\9999-文档-执行铁律.md`，字符数 **161**，与 state JSON 声明的 `char_count: 161` **一致**）：

```
# 执行铁律（系统约定，按优先级执行：用户最新指令 > 本文档 + 制片规格 > Skill/系统默认（优先级链完整声明与硬闸效力边界见平台注入的《执行铁律》头部））

1. 拆解覆盖完整（系统机器验收）。
2. 冲突与缺信息处置、回复纪律：见平台注入的《执行铁律》头部声明
   （优先级链唯一表述源），本文档不复述。
```

→ **该头部在 9999 运行时刻不含「不跨阶段预收」**，也不含任何"合并/不合并提问"的元指令。

### d.4 明细：`prompts\planner\skill_runtime.md` 的 `DISCIPLINE` 节（《Skill 流程纪律》）

- 文件：`prompts\planner\skill_runtime.md`（共 24 行），分节键 `## DISCIPLINE` = **L6-L15**。
- 逐字要点（与本次归因直接相关的三条）：
  - **L8**（第 1 条）：`Skill 阶段逐段执行：执行哪一阶段、何时暂停，一律以当前 Skill 流程基线为准；顺序由你按流程散文自主推进，跨阶段乱序会损害质量。`
  - **L14**（第 6 条）：`多步任务按批次推进：…**停轮契约唯一出口**：…中途暂停（Skill 声明的暂停点、向用户问询/确认）必须调用 workflow_pause 工具，批次之间不存在停轮选项…**思考同样分批**：…（一次性巨量思考会拖慢第一批落盘，中断即全丢）…`
  - **L15**（第 7 条）：`章节即依据：…`
- 核验：`DISCIPLINE` 节内含「**一次性**」（L14，指"巨量思考"），**不含**「效率」「一起问」「打包」「预收」，**不含**任何"把问题合并一次问"的指令。
- 注入证据（间接）：模型在 `LINE 5/6/8` 逐条引用其形态 —— `其实按照 Skill 流程纪律，可委派阶段整段委派。`（LINE 5）、`按 Skill 流程纪律第 6 条，暂停必须调用 workflow_pause。`（LINE 6）。

### d.5 明细：`prompts\planner\execution_preference.md`（《执行偏好》）

- 文件：`prompts\planner\execution_preference.md`（共 18 行）；本轮签名分节 = **L11-12**（`## PREF_CONFIRM_BEFORE_GEN`）。
- `LINE 4` 中逐字出现的是 **L12**（见 d.2 #3）。
- 该文件**不含**「效率」「一起问」「打包」「预收」；语义轴 = "花钱生成是否先弹确认卡"，与"合并提问"正交。

### d.6 `UNAVAILABLE` 段与本轮工具面的核对

- 注入文本（`LINE 4` 末段）：`以下工具本轮不可用：script_analysis_report, storyboard_add_draft, storyboard_create_group, storyboard_delete_group, storyboard_patch_draft。`
- 模型反应（`LINE 5`，逐字）：`但 storyboard 工具（storyboard_add_draft 等）当前不可用，替代路由是经委派执行对应阶段。这意味着故事板相关阶段也要委派。`
  → **`UNAVAILABLE` 段被模型正确读取并驱动了委派决策**，其文案本身不涉及提问频次。

### d.7 非平台侧但本轮在场的输入

| 源 | 文件:行号 | 内容 |
|---|---|---|
| 用户正文 | `conv-main.jsonl` **LINE 3**（`source=user`） | `AI-短剧一站式生成` |
| 选中 Skill 正文 | `data\skills\AI-短剧一站式生成\SKILL.md` **L5-37**（`<planner>` 段，经通道 A order=100 注入） | 含 `L6 **启动协议**`、`L8 用户触发本 Skill 时，按顺序确认以下信息后再推进：`、`L12 3. 输出语言偏好…`、`L27 关键暂停点…绝不一口气输出全部步骤…` |

### d.8 逐条核对结论

1. **`LINE 4` 逐字可证的注入文案共 3 条**：状态 JSON、执行偏好注（`execution_preference.md` L12）、UNAVAILABLE 段（`turn_excluded.md` L1-3 渲染）。**三者均无「效率/一起问/打包/预收」。**
2. **通道 A 的全部 6 个在场段**（protocol / catalog / mcp_catalog / iron_rules / global_settings / subagent / selected_skill）**均不落进本检材**（jsonl 无 system 字段），其"在场"由**代码路径 + 模型逐条引用**证明；**静态源文本经全库检索亦无该四字**。
3. **`skill_runtime.md` DISCIPLINE 与 `iron_rules_header.md` 均在第 6 行之前被模型读过**（`LINE 5` 引用「Skill 流程纪律」「planner 说『用户触发本 Skill 时，按顺序确认以下信息后再推进』」），但二者**都不含**「为了效率」或任何"合并提问"表述。

---

## e) 判据：本仓库中「系统引导」与「系统提示词引导」的可操作区分，及本条最终归属

### e.1 两者**不是同一层**，有 4 条可观测差异

本仓库把"给模型的文本指令"切成**两条物理通道**（§d.0）。可操作判据按证据强度排序：

| # | 判据 | 通道 A · system 段 | 通道 B · history 尾部消息 |
|---|---|---|---|
| 1 | **落流判据**（最强） | **不落**进会话 jsonl（8 种记录类型无 system 字段）→ 只能由代码路径 + 模型引用间接证明 | **逐字落**进会话 jsonl，形态 = `type=user/message`、**`source="state"`** → 可用原始检材直证 |
| 2 | **role 判据** | 运行时 `messages` 中 role = `system`（`prompt_builder.py` L4-5 明写"system prompt 组装"） | 运行时 role = `user`（L8-10 明写"经 build_state_tail_message 以 history 尾部消息（**user 通道**）"） |
| 3 | **文案源判据** | `prompts/**` 经 `load_prompt` / `load_prompt_section` 整文件或分节加载（`utils\prompts.py`；如 L590 `load_prompt("planner/protocol.md")`、L353、L443、L403） | 运行时拼装 + `prompts/planner/execution_preference.md`、`execution_mode.md`、`shared/turn_excluded.md`、`shared/degradation.md`、`shared/storyboard_progress.md`、`shared/selected_draft.md` + 动态状态 JSON |
| 4 | **缓存稳定性判据** | 声明为**跨步字节稳定前缀**（L4-5、L98-99、L730-734） | **每轮刷新**（`prompt_builder.py` L162-174；`planner.py` L766） |

**推论（用于本条归属）**：
- 若「系统引导」指**通道 B** → 本条**可观测的注入中不含任何"合并提问"指令**（`LINE 4` 三段全部逐字核过）。
- 若「系统引导」指**"模型侧一切来自平台的文本"（A∪B）** → 通道 A **亦不含**：`prompts\` 全库「效率/一起问/打包/预收」**0 命中**，「一次性」3 行、「合并」1 行均为工程/流程语义（§c）。
- 因此**无论采用哪种口径，都得不到"平台下发了『为了效率』或『合并提问』指令"的结论**。

### e.2 必须声明的证据边界（诚实标注）

> 通道 A 的**完整装配文本**在本 run **无检材**：会话 jsonl 不落 system prompt；`tracer.py` 只记 `prompt_fingerprints`（L34/L528-546）不记正文；`data\sse_capture` 只录响应侧（`messages_n=3` 仅记条数）。
> 故"通道 A 不含该四字"是**基于静态源文本 + 注入条件（段注册表 + 各段 builder 的 gate）**的断言，**不是对本 run 实际装配结果的直接观测**。
> 缓解：全库静态检索对四个词给出 **0 命中**（0/0），且该结论对本条归因**不承重** —— 即使不依赖通道 A 的检索，本条仍由 ④-1 的三条可观测证据（逐字节流、跨项目分布、`LINE 4` 逐字核对）独立成立。

### e.3 最终结论（本条归属）

> **「为了效率」= 候选④（模型自主裁决），且性质为"模型自发口语化用语"，不是对任何平台文本的复述。**
> **不是"系统引导"（无论定义为通道 B 还是 A∪B），也不是"系统提示词引导"（通道 A）。**

三条支撑（按强度）：

1. **生成层证据**：「为了效率」四字跨 SSE delta#233/234 边界产出，任一 delta 内部**不含完整四字**；拼接串（1627）与落盘 `reasoning_content`（1627）**完全相等**。→ 当场组织措辞，非复制上下文片段。
2. **分布证据**：同一用语在 **17 个项目 / 20 个会话文件 / 2026-09-09 → 2026-09-22** 的推理中反复独立出现，语境横跨 6 类不同决策（并行读取、建组附草稿、抽样核对、传参格式、减少轮次、合并暂停），**无共有指令可解释**。
3. **来源反证**：`prompts\` 与 `src\video_agent\` 对「效率」「一起问」「打包」「预收」**合计 0 命中**；平台关于该轴的唯一两条历史文本（`iron_rules_header.md` L3「不跨阶段预收」= 禁；`docs\冻结与暂缓清单.md` #16「缺项合并一次问询」= 许，非注入文本）已在 9999 运行前（2026-09-20，commit `4231a93`）**双删**。

### e.4 附：本条更深一层的发现（对上游决策有用）

**「为了效率」在本条中并未驱动"合并提问"——实际行为是"减少提问"。**

- 同段（`LINE 6`）先写：`所以只需问语言偏好。同时可以问一下是否有额外要求？不，保持简洁，按启动协议只问语言。`
- 紧接：`也许还可以问用户是否需要引导散文体识别——不，先问语言，然后委派 script_analyze。`
- 再出现：`其实为了效率，可以一次性问：①输出语言偏好。之后委派 script_analyze。`（**"一次性问"之后只有一个问项**：①，无②）
- **落地行为**（`LINE 8` 的 `workflow_pause.options`）= `中文 / 英文 / 双语` —— **只有语言一项**，**没有**画幅/时长/风格。

**对照组（8888 = `proj-1789839470-bbbc8d91`，2026-09-19，双删批之前）**：同一 Skill、同样从零开始，其首个 `workflow_pause` 的 `options` 实测为 **10 项**：

```
['从零开始', '已有部分产出', '中文', '英文', '9:16 竖屏', '16:9 横屏', '60~90 秒', '2~3 分钟', '写实科幻电影感', '冷峻硬核科幻']
```

即 8888 **真的把启动三项 + 画幅 + 时长 + 影像风格打包进了一次暂停**（其 `LINE 12` 思考：`但为了效率，可以在第一次暂停时一并征询制片规格关键参数（画幅、时长、风格），因为这些在阶段 2（写规格）时也需要。`）。

**9999 则不再打包**：画幅/时长/风格被放到**剧本分析完成后的第二次暂停**（`conv-main.jsonl` **LINE 23**：`PAUSE q='剧本分析已完成，以下几项全局参数请你确认'`；用户 **LINE 28** 答 `冷峻硬科幻 16:9 横屏 3 分钟以上 授权合理设计`），与所选 Skill 的分阶段暂停点（`SKILL.md` **L27-32**）一致。

→ 同一用语在 8888 与 9999 都出现，但**行为相反**；决定行为的不是这四个字，而是当时在场的平台文本状态。**把「为了效率」当作"平台下了合并提问指令"的证据，会得到与行为相反的结论。**

> 关于"双删批"的机制说明来自 `docs\指令混乱审计报告-20260920.md` 与 `CHANGELOG.md`（**自述留痕，按验收口径 4 仅作线索**）；其**行为后果**（8888 打包 10 项 vs 9999 只问 1 项）已由上述两份原始 jsonl 独立核实。

---

## 5. 可复现的取证命令（可直接粘贴执行）

> 工作目录 = `E:\07 天问\自己做agent`；全部为**只读**命令。

### 命令 1 · 定位「为了效率」（文件 + 行号 + 逐字 + 字段名）

```powershell
chcp 65001 > $null
python -c @"
import json
P = r'workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl'
ls = [x for x in open(P, encoding='utf-8').read().split('\n') if x.strip()]
print('TOTAL_LINES =', len(ls))
for n, l in enumerate(ls, 1):
    if '为了效率' in l:
        o = json.loads(l)
        print('RAW LINE', n, '| type=', o.get('type'), '| step=', o.get('step'), '| kind=', o.get('kind'))
        for k in ('text', 'reasoning_content', 'content'):
            v = o.get(k)
            if isinstance(v, str) and '为了效率' in v:
                i = v.find('为了效率')
                print('  field', k, 'len=', len(v))
                print('  段:', [p for p in v.split('\n\n') if '为了效率' in p])
"@
```

### 命令 2 · 验证第 6 行与第 8 行是"分片 / 全文"关系

```powershell
chcp 65001 > $null
python -c @"
import json
P = r'workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl'
ls = [x for x in open(P, encoding='utf-8').read().split('\n') if x.strip()]
a = json.loads(ls[4])['text']; b = json.loads(ls[5])['text']; rc = json.loads(ls[7])['reasoning_content']
print('len(L5)=', len(a), 'len(L6)=', len(b), 'len(L8.reasoning)=', len(rc))
print('L5+L6 == L8 ?', (a + b) == rc)
"@
```

### 命令 3 · SSE 捕获复核（证明四字是逐字节流生成、跨 delta 边界）

```powershell
chcp 65001 > $null
python -c @"
import json
f = r'data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl'
d = []
for l in open(f, encoding='utf-8'):
    l = l.strip()
    if not l: continue
    o = json.loads(l)
    if '__chunk__' not in o: continue
    r = o.get('raw', '')
    if not r.startswith('{'): continue
    try: j = json.loads(r)
    except: continue
    for c in j.get('choices') or []:
        t = (c.get('delta') or {}).get('reasoning_content')
        if t: d.append((o['__chunk__'], t))
acc = ''.join(t for _, t in d)
print('delta 数 =', len(d), ' 拼接长 =', len(acc))
pos = acc.find('为了效率'); print('位置 =', pos)
for i, (ci, t) in enumerate(d):
    s = sum(len(x[1]) for x in d[:i]); e = s + len(t)
    if s <= pos < e or s < pos + 4 <= e:
        print('  delta#%d chunk=%d [%d,%d) = %r' % (i, ci, s, e, t))
print('逐 delta 内完整含四字的个数 =', sum(1 for _, t in d if '为了效率' in t))
"@
```

### 命令 4 · `prompts\` + `src\video_agent\` 逐词检索（含行号与逐字行）

```powershell
chcp 65001 > $null
python -c @"
import os
TERMS = ['效率', '一次性', '一起问', '打包', '预收', '合并']
SKIP = {'__pycache__', '.git', 'node_modules'}
per = {t: {} for t in TERMS}
for root in [r'prompts', r'src\video_agent']:
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() not in {'.md', '.py', '.txt', '.json', '.yaml', '.yml', '.toml'}: continue
            fp = os.path.join(dp, fn).replace('\\\\', '/')
            for i, ln in enumerate(open(fp, encoding='utf-8', errors='replace').read().split('\n'), 1):
                for t in TERMS:
                    if t in ln: per[t].setdefault(fp, []).append(i)
for t in TERMS:
    print('【%s】%d 行 / %d 文件' % (t, sum(len(v) for v in per[t].values()), len(per[t])))
    for fp, ns in sorted(per[t].items()): print('   ', fp, ns)
"@
```

### 命令 5 · 跨项目分布（证明无共有指令可解释）

```powershell
chcp 65001 > $null
Get-ChildItem "workspace\sessions" -Recurse -Filter *.jsonl |
  ForEach-Object { $c = Get-Content $_.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($c -and $c.Contains("为了效率")) { $_.FullName.Replace((Get-Location).Path + '\', '') } }
```

### 命令 6 · 核对 `LINE 4` 的逐字来源（执行偏好 / UNAVAILABLE / 铁律）

```powershell
chcp 65001 > $null
python -c @"
import json
P = r'workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl'
ls = [x for x in open(P, encoding='utf-8').read().split('\n') if x.strip()]
c = json.loads(ls[3])['content']
pref = open(r'prompts\planner\execution_preference.md', encoding='utf-8').read().split('\n')[11]
te = open(r'prompts\shared\turn_excluded.md', encoding='utf-8').read().rstrip('\n').split('\n')
names = 'script_analysis_report, storyboard_add_draft, storyboard_create_group, storyboard_delete_group, storyboard_patch_draft'
rend = '\n'.join(x.replace('{{names}}', names).replace('{{route}}', '经委派（run_subagent）执行对应阶段') for x in te)
ir = open(r'prompts\shared\iron_rules_header.md', encoding='utf-8').read().rstrip('\n')
print('execution_preference L12 逐字在 LINE4 ?', pref in c)
print('turn_excluded 渲染结果在 LINE4 ?', rend in c)
print('iron_rules_header 全文在 LINE4 ?', ir in c)
"@
```

### 命令 7 · 全仓搜「为了效率」（确认非注入源；含线索文件）

```powershell
chcp 65001 > $null
Get-ChildItem prompts, src, data, scripts, tests, static, docs -Recurse -File -Include *.py,*.md,*.txt,*.json,*.ts,*.tsx -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\node_modules\\|\\__pycache__\\' } |
  Select-String -Pattern '为了效率' -Encoding UTF8 |
  Select-Object Path, LineNumber, Line | Format-Table -AutoSize -Wrap
```

### 命令 8 · 轨迹核对（工作台日志 + git 时点）

```powershell
chcp 65001 > $null
Select-String -Path "logs\agent-20260922.log" -Pattern "agt-1790055387" -Encoding UTF8 | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
git -C "E:\07 天问\自己做agent" log -3 --date=iso --pretty="%h %ad %s"
git -C "E:\07 天问\自己做agent" show HEAD:prompts/shared/iron_rules_header.md
git -C "E:\07 天问\自己做agent" show 4231a93^:prompts/shared/iron_rules_header.md
git -C "E:\07 天问\自己做agent" show -s --format="%h %ad %s" --date=iso 4231a93
```

---

## 6. 检材 SHA256（复算锚点）

| 检材 | SHA256 |
|---|---|
| `workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl` | `A1DD3B2C0B8440FBCB7BE1E6FDA6DE6F50CB2AC83F15018B4CB7020AACCFBB14` |
| `data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl` | `606D1B5E3EAA946756EE7D4B4FC1E13E58C1BF89BF76BECDCE950780D5E6D0EF` |
| `prompts\shared\iron_rules_header.md` | `A93AFC77B61408859E15CD1270A14F6ABCD18C28BADC40CBDE1E81A8E34C1325` |
| `prompts\planner\skill_runtime.md` | `7829FF87EE1450AB03F1BA903F2B22BA1A101C53421DAEE8321B60E8E35F930A` |
| `prompts\planner\execution_preference.md` | `D73276746A28A6D0766DD3CB3693AA81769F028DC915710082CEF8C0092AFC1B` |
| `prompts\shared\turn_excluded.md` | `AB2CB0A5AD304FD773D5498F4F2CDC7DFA61B5E0ABB4699F1EED9F5E6D8A8533` |
| `prompts\planner\protocol.md` | `130CE4C839E6F67BAF1A093AE9F7B4CA5E8C180AD5F88247E4C89708D0A0B8A8` |
| `prompts\planner\subagent.md` | `82EA150028ECDB74E8DFE7437F71D0CBE6BC232AE43C0B449CC106D7A9667CA2` |
| `data\skills\AI-短剧一站式生成\SKILL.md` | `D4D2DF3B83990AFEB7B9A35ACAC4D88519DBC25980469BC3BD9C1C563A2A4B10` |
| `src\video_agent\core\prompt_builder.py` | `C22DC0C97876BE17F4ED52B725235D3A73B8E5ECB869ADD7B8BFADB3511B6765` |
| `tests\unit\test_prompt_relocation_batch3.py` | `D8511623C4D59610DF2DEA7DB912AED18AFD57EF599F68AA7175AB8792D3A0B7` |

---

## 7. 验收自检表

| 验收项 | 状态 | 落点 |
|---|---|---|
| 1. 出现位置 = 具体文件 + 行号 + 逐字原文 | ✅ | `conv-main.jsonl` **LINE 6**（`text`, len=471）、**LINE 8**（`reasoning_content`, len=1627）；§a.1 / §a.3 |
| 2. 四条候选来源逐条结论 + 证据 | ✅ | §b ①不成立 ②不成立 ③不成立 ④成立（供应商侧部分标注"不可观测、仅可推断"） |
| 3. 「某文件写了这四个字」的断言必须给文件 + 行号 | ✅ | 全库仅 3 处（`tests\unit\test_prompt_relocation_batch3.py`:139、`docs\指令混乱审计报告-20260920.md`:74/75/193），均标注为**非注入源**；`prompts\`/`src\video_agent\`/`data\` 为 **0 命中**（无断言，故无需"未证实"字样） |
| 4. 不拿仓库自述文档当注入证据 | ✅ | `CHANGELOG.md` / `docs\**` / `tests\**` 仅作线索并显式标注；所有结论回原始 jsonl（§a）、运行时代码（§d）、运行时刻 SSE 捕获（§a.4）复核 |
| 5. 可复现取证命令 | ✅ | §5 命令 1–8 |
| 红线：只读、未改 `src\`/`prompts\`/`data\skills\` | ✅ | 写入仅 `reports\规格精简-20260922\`；`git status --porcelain` 仅 `?? .agent-teams/`、`?? reports/` |

---

## 8. 不确定项与证据边界（诚实清单）

1. **通道 A（system 段）的完整装配文本本 run 无检材** —— 会话 jsonl 不落 system prompt；`tracer.py` 只记 `prompt_fingerprints`；`data\sse_capture` 只录响应侧（`messages_n=3`）。"通道 A 不含该四字"由**静态源全文检索（0 命中）+ 注入条件代码**支撑，非直接观测。**该边界不影响本条结论**（结论不依赖通道 A 的检索）。
2. **供应商侧默认偏好不可观测** —— `base_url=https://tokenrhythm.studio/v1`、`model=deepseek-v4-flash-0731` 只记于 SSE `__header__`；供应商是否附带系统提示词、措辞如何，本仓库无检材。故该项已按题目要求标注「不可观测、仅可推断」，且本报告**不采纳**该项作为归属（④-1 已充分解释）。
3. **`LINE 5`/`LINE 6` 的切分阈值未逐位反推到源码常量** —— 已核实切点落在 delta#206 内部（非句界）、两段之和恰等于全文，证明"按长度任意切分"；但生成该阈值的具体常量未在本报告内定位（`session_log.py` L505 的 `PRUNE_THRESHOLD_CHARS = 8192` 属同名族但数值不符，可能有独立的分片常量）。**该细节不影响 §a.4 结论**（分片/全文关系已由长度恒等式与 SSE 拼接双向证明）。
4. **「一次性问：①」只有一项** —— 逐字如此（无 ②）。可有两种读法：(i) 模型本打算列多项但只写出一项；(ii) 措辞冗余。**本报告不对此二读法作裁断**，仅指出：无论哪种读法，**落地行为只有语言一问**，与"打包后阶段参数"无关。

---

## 9. 附：本次取证写入的辅助检材（均在 `reports\规格精简-20260922\`，只读脚本产物）

| 文件 | 用途 |
|---|---|
| `_probe_lines.py` | 打印 `conv-main.jsonl` 全部 62 行的类型/字段/长度；按行号 dump 逐字字段（§a 用） |
| `_probe_concat.py` | 验证 `LINE5.text + LINE6.text == LINE8.reasoning_content`（§a.4 用） |
| `_probe_sse.py` / `_probe_sse2.py` | 解析运行时刻 SSE 捕获，定位跨 delta 边界（§a.4 / §e.3 用） |
| `_probe_terms.py` / `_probe_counts.py` / `_terms_out.txt` | 六词逐行检索与统计（§c 用） |
| `_probe_ctx.py` / `_ctx_out.txt` | 原始 jsonl 第 1–11 行 raw JSON 落盘（§a.2 用） |
| `_probe_quotes.py` | 校验模型引述片段的真实源文件（§b ④-1 用） |
| `_probe_verify.py` | 校验 `LINE 4` 三段逐字来源 + 跨项目时间跨度（§d.2 / §b ④-1 用） |
| `_probe_crossproj.py` / `_crossproj_out.txt` | 跨项目「为了效率」分布与上下文（§b ④-1 用） |
| `_probe_8888.py` | 对照组 8888 的启动暂停 options（§e.4 用） |
| `_probe_turns.py` | `conv-main.jsonl` 全轮次正文与 pause 问题清单（§e.4 用） |
| `_probe_sys.py` | 校验 jsonl 是否含 system/prompt 字段（§e.2 证据边界用） |
| `_probe_null.py` | 复核模型引述句不在 `iron_rules_header` / `DISCIPLINE`（§b ④-1 用） |

以上脚本均**只读**；未触碰 `src\`、`prompts\`、`data\skills\`。

