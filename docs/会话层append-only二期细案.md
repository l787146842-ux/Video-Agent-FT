# 二期细案：状态注入事件化 + append-only 缺陷修复批（A-E，已落地）

> 状态：**已获批并全量落地（2026-09-09，批 G1-G4）**。批次留痕见 `CHANGELOG.md` 2026-09-09「会话层 append-only 二期批」；§一 验收总口径的实测项（稳态 ≥95% / 末段 ≥98% / read_state_group 行为观测）待 deepseek 通道真实跑批（终验）。v2 修订史：A 由「轮首注入闸门 + 快照落账本」重写为「**注入即事件**」正向设计（dsh `agent.inject` 源码实证，快照补丁废弃）；B/D 判定统一收编到 user/message `source` 字段。
> 一期（`docs/会话层append-only化细案.md`，批 E1-E3）已落地；本批是其审查发现项的修复 + 缓存主目标的结构性收口。
> 审查结论（2026-09-09 会话）：B/C 为正确性与成本必修；A 为 95% 目标的唯一通路（外部标杆转录实证拉模式）；D/E 为形态补全；**F（未知工具解析层归位）经复核已随一期落地（fc_tool_runner.py:312 解析层拒收 + fc_gates.py:242 兜底），审查误报，本批无此项**。

## 一、批间关系与目标

| 项 | 一句话 | 性质 |
|---|---|---|
| **B** | 截断重答 × 压缩检查点交互丢全史 | 正确性 bug（必修） |
| **C** | 压缩轮每步重复烧摘要调用 | 成本/延迟 bug（必修） |
| **D** | 检查点永不合并、永久堆积 | 压缩语义补全（dsh 原文有、我们漏） |
| **A** | 状态尾每步全量重发 → 轮首注入 + 按需读 | 缓存主目标（95% 唯一通路） |
| **E** | 图片/多模态消息不入事件流 → 回放字节不等 | 前缀连续性补全 |

**验收总口径**（A 落地后实测）：`scripts/cache_hit_report.py` 稳态 ≥95%，长会话末段（上下文 >100K）≥98%；B/C/D/E 各带单测钉死。

## 二、B：rewind × checkpoint 交互修复（session_log.py）

**Bug 链**：压缩检查点以 `user/message` 事件落流 → 用户截断重答该轮时，`rewind_last_turn` 扫「最后一条 user/message」命中**检查点**（非真实用户消息）→ `to_seq` 错位 → 单遍 fold 中检查点被 rewind 丢弃，但其 `replaces_seqs` 遮蔽的原事件早在 fold 早期被移除、**无法恢复** → 回放 = 空历史 + 被重答的旧 user 消息反而残留。

**修法二件套**（同一模块，一批完成；与 §五 source 字段共用判定——检查点事件带 `source="checkpoint"`，rewind 定位「最后一条 `source="user"` 的 user/message」一次解决检查点与状态事件两类合成消息）：

1. **`rewind_last_turn` 扫描按 source 定位**：跳过 `source != "user"` 的 user/message（检查点/状态注入等合成事件均非轮起点；老事件无 source 字段视为 user，向后兼容）。
2. **`_fold_surface` 改两遍 fold**：
   - 第一遍：扫全部 `log/rewind`，取**最后一条**生效 `to_seq`（无 rewind 则 ∞）；
   - 第二遍：正常 fold，但 `seq > to_seq` 的事件**直接跳过**（视为从未发生）——检查点若 `seq ≤ to_seq` 正常生效（继续遮蔽其必然更早的 shadowed）；检查点若 `seq > to_seq` 连同其 shadowed 一起从未进入 fold，**原事件自然完整恢复**。
   - 现单遍逻辑（rewind 时对 out 做列表过滤）删除。

**单测**：①重答压缩触发轮 → 回放含被遮蔽原事件（恢复）+ 检查点消失；②重答非压缩轮 → 行为与现一致；③连续两次 rewind 取最后一条；④检查点 seq ≤ to_seq 时继续遮蔽（不双重呈现）。

## 三、C：压缩轮重复烧摘要修复（session_log.py + turn_executor.py）

**Bug 链**：`call_llm` 里 `full_messages = [{"role":"system"}] + messages` 是**新列表**；`compact_pass` 的 splice 只改副本；agent_loop 的 `messages` 不受影响 → 下一步重新组装未压缩历史、压力仍在、日志已有检查点导致 `_match_surface_seqs` 对不齐 → 降级纯内存面 → **每步重调一次摘要**（15-30s/次 + 全价）。

**修法二件套**：

1. **双列表同步 splice**：`compact_pass` 新增可选参数 `mirror: List`（= agent_loop 的 messages）；splice 时同步 `full_messages[i+1:j+1] = [checkpoint]` 与 `mirror[i:j] = [checkpoint]`（mirror 无 system 头，坐标 -1）。turn_executor 两通道传入 `messages`。
   - 语义保证：下步 `full_messages = [system] + messages` 自然含检查点 → 与日志 fold 结果一致 → `_match_surface_seqs` 对齐 → 不再降级、不再重复事务。
2. **指纹缓存兜底**（round_compact 同款回归）：span 内容 md5 → 已见摘要缓存（上限 64 条 LRU）；同 span 重复触发（理论上双 splice 后不再发生，防御性）直接复用摘要，不再发模型调用。

**单测**：①阈值轮多步：摘要调用次数 = 1（原为每步一次）；②mirror 与 full_messages 同步（步 2 的 `_match_surface_seqs` 对齐走日志事务分支）；③指纹缓存命中不发调用。

## 四、D：检查点合并（session_log.py + prompts/planner/feedback.md）

**缺口**：①范围选择 `start` 扫描跳过「（系统」前缀消息 → 检查点永不进压缩范围；②摘要指令无 prior-checkpoint 合并条款。

**修法**：

1. **范围选择纳入检查点**：判定改按 `source == "checkpoint"`（§五 统一判定；检查点事件落流时带 source，_is_checkpoint_msg 不再按文案前缀猜）；`start` 前进条件从「非真实用户消息」改为「非 `source="user"` 且非检查点」——检查点可作为 span 起点（其代表的老历史随 span 一起被再压缩）。
2. **摘要指令补合并条款**（feedback.md::COMPACTION_INSTRUCTION 追加，dsh 原文意译）：「若上文已含 <compacted-summary> 块，它是此前检查点：不要逐字照抄，保留仍属实的事实、丢弃已过时内容，把新旧信息合并为单一摘要」。

**单测**：①含旧检查点的会话再压缩 → 新检查点 shadowed 范围含旧检查点 seq；②fold 后仅存单一合并检查点（旧的不重复呈现）。

## 五、A：状态注入收编为日志事件（正向设计，主抄 dsh `agent.inject` 形态）

**病根**（审查实测归因）：状态尾每步全量重发（~10-20K）且含步数计数器（每步必变），位于请求末尾（新内容之后）→ 每步全价 ≈ 状态尾体量 → 命中率天花板 75-85%（与 1111 实测 74-81% 吻合，**剩余缺口全在此，不在 tool 回喂**）。结构表述：**存在一个「每请求重建、不落日志」的尾部消息**——它是日志外的第二事实源，前缀连续性与 rewind/压缩语义全要为它打补丁。

**dsh 正统形态**（session 事件模型源码实证）：dsh 给模型注入的一切——文件变更通知、AGENTS.md、skill 内容、cron 通知——都是 `user/message` **事件**（带 `source` 字段区分真人输入/inject 注入/续跑），落日志、回放逐字节复现（"All three project their `content` verbatim; `source` tells them apart"）。系统提示词本身也是 surface 0 号节点事件。**dsh 没有任何「每请求重建的注入」——不存在本问题，无需补丁**。外部标杆转录同形态（8 次「信息搜索完成」拉取 + 「媒体/时间线变更已同步」变更通知，无每步全量推送）。

**设计（注入即事件，尾部消息概念退役）**：

1. **user/message 事件加 `source` 字段**：`"user"`（真人输入）| `"state"`（状态注入）| `"checkpoint"`（压缩检查点，等价现 replaces_seqs 判定，二选一统一为 source）。历史推导中「真实用户消息」判定统一改按 source（B 的 rewind 跳检查点同用此判定，一次定义全局复用）。
2. **状态注入 = 轮首一条 source=state 的 user/message 事件**：
   - 落点：chat_service 轮始（turn/start + 用户消息事件之后、进入 agent_loop 之前），状态构建器**每轮执行一次**（原 turn_executor 每步懒构建退役为每轮一次，本身即简化）；
   - 内容 = 现状态尾全家（状态 JSON + 降级引导 + 执行偏好/模式 note + 故事板进度 + 选中草稿指针），**步数行删除**（每步必变；STEP_FEEDBACK 已带轮次，冗余）；
   - 非工作室上下文不落（现状同口径）。
3. **步间零注入**（dsh 形态）：轮内后续步请求 = [system] + 回放历史（含状态事件与全部步事件），无尾部消息；模型靠轮首基线 + tool/result 回喂（天然变更通知）跟踪状态，需要全量调 `read_state_group`。
4. **turn_executor 尾部装配退役**：`_state_tail_message` 每步注入与 `_degrade_state_tail` 每步降级删除；B 档降级（state_context_budget_chars）改作用于轮首事件构造前（超限先降级再落流）。
5. **STEP_FEEDBACK 文案改**（feedback.md）：尾指针「见对话末尾最新的工作台状态 JSON」失效 →「如需最新工作台全量状态，可调用 read_state_group 按组读取」。

**缓存结构（正向推得，非补丁）**：下一轮请求 = [system] + 回放（…上一轮 user 消息 + 状态事件① + 步 1..N + 最终回复 + 本轮 user 消息 + 状态事件②）。回放段与上一轮实际发出的请求**逐字节相同**（都是日志的纯函数）→ 命中至上一轮最后一字节，每轮全价仅 = 上轮回复 + 新消息 + 新状态事件（纯新内容，理论下限）。轮内每步全价仅增量 ~1-3K → 稳态 95-97%，长会话末段 ≥98%。

**边界场景**：
- **轮内用户操作**（暂停回应/选中草稿）：新 user 消息 = 新轮 = 新轮首状态事件，自然刷新 ✓；
- **轮内长循环**（20+ 步）状态累积：tool 回喂逐条可见；read_state_group 兜底（转录同款行为）；
- **压缩交互**：状态事件是普通历史消息（source=state 非轮锚），随老轮组一起被压进摘要，上下文不膨胀（替代「快照落账本」补丁的压缩收编，机制原生）；
- **rewind 交互**：rewind 扫描按 source="user" 定位，天然跳过状态事件与检查点（与 B 共用判定）；
- **scope 子对话**：同口径（scope 轮始同点落 source=state 事件）；
- **迁移**：老线程无状态事件（今天的历史本就不含状态注入），回放行为一致，无突变。

**单测**：①轮首状态事件落流（两通道 + scope）；②步 2+ 请求无尾部消息（executor 装配断言）；③回放 = 上轮请求逐字节（跨轮等价性，缓存结构性保证）；④source 判定：rewind/压缩范围/真实用户消息三处消费同一判定；⑤步数字段不再出现；⑥STEP_FEEDBACK 新文案接线；⑦B 档降级作用于事件构造前。

## 六、E：图片/多模态消息入流（session_log.py + fc_feedback.py + chat_service.py）

**缺口三处**：①用户带附件轮：请求为 content parts（含 image_url），日志落 `user_text` 纯文本 → 回放字节不等；②`view_storyboard_media` 图片 user 消息无事件；③`strip_prior_feedback_images` 只改内存不改装载 → 回放后旧轮图片全回来（vision token 膨胀 + 与内存演化路径不一致）。

**修法**：

1. **事件 content 支持 parts**：`user/message` 事件的 `content` 允许 list（parts 原样 JSON 落盘，data_uri 原样——workspace 本地不进 git，磁盘代价可接受；vision token 才是大头，磁盘无谓）。`derive_messages` 透传 list content。
   - 落点：chat_service 两通道 `append_user_message` 改传 `llm_user_content`（为 list 时）替代 `user_text`；截断重答路径同口径。
2. **图片消息镜像落流**：`format_tool_result_messages` 产出 `_image_msg` 时，agent_loop `_mirror_fc_feedback` 同点镜像 `user/message`（content=parts）事件。
3. **装载层图片剥离**（替代内存 strip 的跨轮语义）：`load_history`/装载链路在 derive 后，保留**最后一条**图片消息原样，更早图片消息的 image parts 替换为文本占位（复用 FEEDBACK_IMAGES_STRIPPED 文案）——「上下文只保留最新画面」的 vision token 治理在装载口径统一实现，日志原文永在。内存 `strip_prior_feedback_images` 保留（轮内即时剥离，两口径同文）。

**单测**：①多模态 user 轮：回放 parts 与请求逐字节一致；②图片消息落流 + 回放；③装载剥离：仅最后一条图片保留，更早换占位；④剥离后字节稳定（跨轮同构）。

## 七、分批执行（每批独立验收、独立 commit）

| 批 | 内容 | 验收 |
|---|---|---|
| **G1** | user/message `source` 字段 + B（两遍 fold + source 定位）+ C（双列表 splice + 指纹缓存） | B/C 单测组；全量回归 |
| **G2** | D（检查点纳入压缩范围 + 合并指令条款） | D 单测组；quick |
| **G3** | A（状态事件化：轮首 source=state 事件落流 + turn_executor 尾部装配退役 + 步数删除 + STEP_FEEDBACK 文案 + B 档降级前移） | A 单测组（含跨轮等价性）；全量回归 |
| **G4** | E（parts 落流 + 图片镜像 + 装载剥离） | E 单测组；全量回归 |
| **终验** | cache_hit_report 实测（deepseek 通道，完整 Skill 流程跑批） | 稳态 ≥95%，末段 ≥98%，人工判读 |

改动面：`session_log.py`（source/B/C/D/E 核心）、`turn_executor.py`（C 传参 + A 尾部装配退役）、`prompt_builder.py`（A 步数删除）、`prompts/planner/feedback.md`（A/D 文案）、`fc_feedback.py` + `agent_loop.py`（E 镜像）、`chat_service.py`（A 轮首状态事件落流 + E 落流点）；测试新增 4 组约 17 例。

## 八、风险与边界

- **G3 行为风险（唯一真风险）**：步 2+ 模型看不到全量状态，若模型不主动 read_state_group 而凭记忆断言组状态，可能出错。缓解：①轮首基线仍在；②tool 回喂逐条可见；③STEP_FEEDBACK 明示读取指引；④真跑批（终验）观察 trace 中 read_state_group 调用率与错误率，若模型明显失能，回滚开关 = chat_service 恢复轮内每步尾部注入 + 状态事件落流关闭（两处开关，行为回今天）。
- **GLM 通道缓存恒 0**（中转侧，已有实证）：A 的收益在 deepseek 等有缓存通道兑现；终验通道选择 deepseek。
- **E 的 JSONL 膨胀**：图片 base64 落盘，单会话文件可能到数十 MB——workspace 本地、不进 git、无回读性能问题（追加写）；超限轮转另案（一期已记）。
- **G1 两遍 fold 性能**：事件全量读已在做，第二遍只是常数翻倍，10K 事件量级无感。
- **状态事件体量**：每轮一条全量状态（~10-20K），长会话多轮累积——由压缩机制原生收编（随老轮组压进摘要），与 E 的图片膨胀同归一条治理线。

## 九、待用户裁决项

1. **A 的注入节奏**：轮首一条全量状态事件（推荐，dsh inject 同位 + 外部标杆「当前制作进度」同款轮首形态）vs 更激进（不落状态事件，全靠 read_state_group——对模型自觉性要求过高，不推荐）。
2. 步数行删除、STEP_FEEDBACK 文案改——随 G3 执行，是否照准。
3. 分批 G1→G4 顺序（正确性优先 → 语义 → 结构 → 补全）是否照准。
