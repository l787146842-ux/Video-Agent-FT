# 主刀细案：会话层 append-only 化（v4 方案 §主刀，送审稿）

> 状态：**送审待批，未动工**。批准后按 §十 分批执行。
> 主抄源 = dsh（github.com/deepseek-ai/deepseek-harness，MIT，master）；本细案所有「原样」参数均对照其 `compaction-basic` / `compaction-tool-result-pruner` / `session` 三包文档逐字核对。

## 一、问题与目标（为何动结构）

**结构性根源**：历史非 append-only——轮内 assistant(tool_calls) + tool 结果 + 步回喂只存在于单请求内存列表，轮末蒸发（chatMessages 只落名义 user/正文）。后果三条（v4 实测）：70K tokens 中 ~40K 是轮内回喂累积；模型跨轮「反推式梳理」（状态断层类打架）；读过的 Skill 章节/文档每轮消失、重读与去重指针双双失效。

**目标**（验收见 §九）：① 同一内容不再二次全文回喂；② 稳态缓存命中率实测 ≥95%；③ 上下文增长曲线平滑（修剪/压缩按阈值触发，无锯齿）。

## 二、现状事实（G2：既有机制盘点）

| 机制 | 位置 | 现行为 | 收编裁决 |
|---|---|---|---|
| chatMessages | state（SQLite）名义消息 | user + 最终正文 + 卡片；轮内事件不落盘 | **保留 = UI 投影**，不再是 LLM 历史源 |
| `_main_history_from_thread` | chat_service:344 | 逐条转 role/content + mechanical 占位 | **替换**为事件流装载（§五） |
| `truncate_history` | chat_opening:74 | assistant >2000 字符压头1800+尾200（位置无关） | **暂留**（入口层预裁），批 E3 实测后裁决退役 |
| `round_compact.compact_oldest_round` | turn_executor:264/316 | 0.8×max_tokens 触发 LLM 摘要，轮组原地替换（内存态、不留痕） | **退役**，职责并入会话层压缩（§八） |
| `should_compress_feedback` / `compress_prior_feedback` | fc_feedback:112-152 | 0.35 预算触发，FEEDBACK_MARKER user 回喂压占位句 | **退役**：tool role 化后其对象只剩旧格式；修剪器+压缩覆盖其职责 |
| `strip_prior_feedback_images` | fc_feedback:263 | 旧轮图片回喂剥离 | **保留**（修剪器只裁文本，图片另案） |
| `digest_projected_tool_results/args` | fc_feedback:155-260 | TOOL_RESULT_DIGEST_CHARS=0 默认关 | **保留现状**（默认关，不叠加新语义） |
| `truncate_messages`（轮组原子） | token_budget:174 | 超预算整轮组删除保险丝 | **保留** = 末级保险丝（阶梯②） |
| `history_compact`（scope 域） | chat_service:932 | 会话级摘要仅 scope 在用 | 不动（域外） |

## 三、dsh → 本平台映射总览

| dsh 概念 | 本平台实现 |
|---|---|
| Session = append-only 事件日志，历史由回放推导 | `workspace/sessions/<project_id>/<conversation_id>.jsonl`，逐事件一行 JSON |
| `user/message` / `assistant/message` / `tool/result`（surface 事件，seq 单调） | 同名三事件；assistant 事件内嵌 `tool_calls`（见 §四 D1） |
| `request/header` 快照 | 不引入（system/tools 每请求仍由 PROMPT_SECTIONS/tools_schema 现算，口径在原处） |
| `tool-result-pruner`（8192/4096/1024 码点，零模型调用，原文留日志） | `session_pruner`（§七），参数原样 |
| `compaction-basic`（0.8 触发 / 0.16 逐字尾 / 摘要热前缀复用 / 日志括号事务） | `session_compact`（§八），参数原样 |
| checkpoint policy（下一步动作前先落盘） | 每事件 append 即 flush（JSONL 追加，成本可忽略） |
| `/compact` 手动命令 | **不引入**（平台无对应交互面；后续另案） |

## 四、存储格式

### 4.1 事件词汇表（首版最小集）

```jsonc
// surface 事件（参与推导 LLM 可见消息；seq 全日志单调）
{"seq":1,"type":"turn/start","time":...,"turn":7}
{"seq":2,"type":"user/message","time":...,"turn":7,"content":"..."}
{"seq":3,"type":"assistant/message","time":...,"turn":7,"step":1,
 "content":"","reasoning_content":"","tool_calls":[{"id":"call_x","name":"read_skill","arguments":"{...}"}],
 "usage":{"prompt_tokens":...,"cached_tokens":...}}
{"seq":4,"type":"tool/result","time":...,"turn":7,"step":1,
 "call_id":"call_x","name":"read_skill","ok":true,
 "content":"执行成功，全文如下（...）"}          // = 回喂进模型的最终文本（消化/指针化后口径）
{"seq":5,"type":"step/feedback","time":...,"turn":7,"step":1,"tool_count":2}   // log-only，见 D2
{"seq":6,"type":"turn/end","time":...,"turn":7,"reason":"stop"}
```

```jsonc
// log-only 事件（不直接推导消息）
{"seq":9,"type":"compaction/start","time":...,"turn":7}
{"seq":10,"type":"compaction/summary","time":...,"summary":"...","shadowed_seqs":[3,4],"shadowed_token_count":6100}
{"seq":11,"type":"compaction/end","time":...,"turn":7}
{"seq":12,"type":"tool/result","time":...,"pruned_from":4,"content":"头4096\n[... 中略 ...]\n尾1024"}   // 修剪替换，见 §七
{"seq":13,"type":"user/message","time":...,"replaces_seqs":[2,3,4,5,12],
 "content":"<compacted-summary>...</compacted-summary>"}   // 压缩替换检查点，见 §八
{"seq":14,"type":"log/rewind","time":...,"to_seq":8}       // 截断重答/回滚标记，见 D6
```

### 4.2 设计裁决（送审确认点）

- **D1 事件粒度**：`tool_calls` 内嵌于 `assistant/message`，**不**照搬 dsh 的独立 `tool/call` 事件。理由：与本平台 C2 派发结构（assistant.tool_calls + tool role 结果）同构，回放推导逐字节等价，迁移面最小；call_id 配对关系由 `tool/result.call_id` 承担。
- **D2 步回喂不存原文**：`step/feedback` 只存事实（turn/step/tool_count），装载时按 `feedback.md::STEP_FEEDBACK` 模板派生文本——措辞单一事实源仍在 prompt 层（P1），改措辞不重写历史。
- **D3 chatMessages 降位为 UI 投影**：前端时间线/消息面板零改动（其数据源本就是 chatMessages + trace）；事件流是 **LLM 历史唯一事实源**。两条写路径并存：轮始/轮末照旧写 chatMessages（UI），每步落事件流（模型）。
- **D4 失败回落**：事件流 append/load 失败 → 告警遥测（`record_degradation`）+ 回落现行 chatMessages 装载路径（fail-open 到今天的行为，不阻断对话）。
- **D5 文件位置与归属**：`workspace/sessions/<project_id>/<conversation_id>.jsonl`（workspace/ 已 gitignore）；每 conversation 一文件，scope 子对话天然隔离；单写者 = 服务进程该轮处理协程（与 cache_metrics 同口径，不做并发锁）。
- **D6 截断重答 / 一键回滚**：追加 `log/rewind{to_seq}` 标记，装载时忽略其后事件——**已提交事件绝不重写**（dsh 同款「标记非改写」）；文件不物理收缩（超限轮转另案，初版不做）。

## 五、装载链路（每请求全量回放）

```
stream_prepare（收到用户消息）
  ├─ user/message 事件 append+flush（与现行 chatMessages user 落账同点）
  └─ 装载历史:
      load_events(conversation_id)            # 读 jsonl，seq 校验（断行/损坏行止于最后完整行，告警）
      → apply_rewind                          # 取最后一个 log/rewind 生效截面
      → fold_surface                          # 三类 surface 事件按 seq 排布；
                                              #   pruned_from/replaces_seqs 遮蔽被替换节点
      → derive_messages                       # user→user；assistant→assistant(content,tool_calls,reasoning_content)；
                                              #   tool/result→tool role；step/feedback→模板派生 user 文本
      → [批E2] pruner_pass（若压力命中，见 §七）
      → [批E3] compaction_checkpoint（若历史上有检查点已折入 surface，无需额外处理）
      → truncate_history（现行入口预裁，暂留）
      → messages（交给 agent_loop，轮内继续 append）
```

**轮内镜像**（append-only 的核心增量）：agent_loop FC 路径现有的三处内存 append（assistant(:565)、tool 结果与悬挂补位(:570-576)、STEP_FEEDBACK(:586)）各镜像一条事件 append+flush——内存列表与日志逐事件同步，崩溃重启后从日志回放，工具结果不蒸发（问即停/中断轮的场景即此收益）。

**等价性硬口径**：同一条事件流，「整段回放推导」与「增量推导」输出逐字节一致（单测钉死）；这是缓存稳态 ≥95% 的结构性保证。

## 六、迁移策略（chatMessages → 事件流）

- 首次装载时若 `sessions/<pid>/<cid>.jsonl` 不存在：把该线程 chatMessages 名义消息（跳过 `kind="mechanical"` 与卡片条目）依序导出为 `user/message` + `assistant/message`（无 tool_calls）事件，头部落 `turn/start{turn:0}`，写完追加 `log/imported{from:"chatMessages"}` 标记事件后正式使用。**一次性、幂等**（以标记事件判重）。
- 历史工具结果**不补录**（本就不存在），迁移只保名义对话——与今天模型可见的历史完全一致，无行为突变。
- chatMessages 此后仅服务 UI 与回落路径（D4），写路径不变。

## 七、修剪器（抄 dsh tool-result-pruner，参数原样）

- **触发时机**：压缩触发命中后、范围选择前（低于压力绝不裁）；零模型调用。
- **对象**：surface 上每个 `tool/result` 的文本内容 > **8192** 码点（Unicode code point 计数，与 dsh 同口径）。
- **替换**：追加新 `tool/result` 事件（`pruned_from=<原seq>`），内容 = 头 **4096** + 中省略标注 + 尾 **1024**（码点切片，不劈 surrogate 对）；原文事件**永留日志**（回放/审计可复原）。一次 pass 内多替换各自成事件，与 dsh `PrunedEntry` 同构记账（chars_before/after 汇总入遥测）。
- **中省略标注**：`\n\n[... tool result middle pruned ...]\n\n`（原样照抄）。

## 八、阈值压缩（抄 dsh compaction-basic，参数原样）

- **触发**：请求前估算（最新 breakdown 同源）≥ floor(context_window × **0.8**)；`round_compact` 的 0.8×max_tokens 触发点由本机制取代。
- **范围选择**：最旧「配对平衡」span（assistant(tool_calls) 与其 tool/result 不劈半，复用 `token_budget._is_real_user_msg` 轮组边界），逐字保留最近 **16%**（retainRatio）尾部。
- **替换**：摘要以 `user/message`（`replaces_seqs` 全列）+ `<compacted-summary>` 包裹落日志；`compaction/start → summary → end` 括号先 append 再动内存（崩溃=可检孤儿锁，不误报完成）。
- **摘要请求热前缀复用**：system + tools + 被压缩区间消息逐字节重放 + 末尾压缩指令一条 user 消息——摘要调用是主对话的真前缀，只有尾部指令与摘要输出未命中缓存。
- **溢出恢复**：供应商确认上下文超长（AdapterError 分类）→ 绕过阈值做一次最大平衡缩减后重试一次（maxOverflowRetries=1）。
- **不做**：`/compact` 命令、per-model policy 表、Zstandard 压缩（均无对应需求面）。

## 九、验收口径

1. **无二次全文回喂**：trace 抽查长 Skill 跑批——同章节 `read_skill` 第二次起为指针化短句（跨轮留存使其可靠生效）；故事板建组 desc 不再逐步重复全文回喂。
2. **稳态命中率实测 ≥95%**：`python scripts/cache_hit_report.py`（剔除每项目首调与 <12K 预热的既有口径），跑一个完整 Skill 流程后人工判读。
3. **增长曲线平滑**：context-usage est_tokens 随步增长无锯齿；修剪/压缩仅在阈值命中步发生（事件流中有对应替换事件可查）。
4. **断轮恢复**（结构红利）：运行中杀进程重启，新请求的历史含已执行步的完整工具结果（日志回放），不再从状态 JSON 反推。

## 十、分批执行（每批独立验收、独立 commit）

| 批 | 内容 | 验收 |
|---|---|---|
| **E1** | 事件流骨架（词汇表+append/flush+load+fold/derive）+ 轮内三处镜像 + 装载链路切换 + §六迁移 + D4 回落 | 回放/增量等价性单测；迁移幂等单测；杀进程恢复验收；全量回归 |
| **E2** | 修剪器（§七）+ 遥测记账 | 8192/4096/1024 码点单测（中英文/emoji 边界）；低于压力不裁 |
| **E3** | 阈值压缩（§八）+ `round_compact`、`compress_prior_feedback` 退役 + `truncate_history` 实测后裁决 | 触发/保留尾/平衡边界单测；§九全量验收（含 cache_hit_report 实测） |

改动面预估：新增「会话事件流模块」（E1 落位，事件流骨架+装载）与「会话压缩模块」（E3 落位，修剪器+压缩）；改 `chat_service.py`（装载切换+镜像）、`agent_loop.py`（镜像）、`turn_executor.py`（退役调用点）、`config.py`（参数）、`token_budget.py`（不动或微调）；测试新增 3 组。

## 十一、风险与边界

- **缓存击穿点**：修剪/压缩替换事件 = 前缀失效起点（dsh 同款代价），仅在阈值命中时发生；稳态跑批中低频。
- **指令体量**：本方案零新增系统提示词（结构层方案，非 prose 方案，G3）；压缩检查点前言/修剪标注为运行时模板，落 `prompts/planner/feedback.md` 分节。
- **G1**：Skill 包冻结不动，本方案全在平台层。
- **G4**：装载链路切换覆盖主对话 + scope 子对话两条路径（`_scope_history_from_thread` 同点切换）。

## 十二、待用户裁决项

1. §4.2 D1-D6 六项设计裁决是否照准（尤其 D3 双写并存、D4 fail-open 回落、D6 rewind 标记制）。
2. §八 `round_compact` / `compress_prior_feedback` 退役是否随批 E3 执行（本细案建议：是，理由见 §二收编表）。
3. 分批 E1→E2→E3 顺序是否照准（v4 方案原文即此顺序）。
