# 脚手架存量入账清单（0A 草稿，待审定）

> **【档案化 · 2026-08-21 审核整改批0】** 本草稿为阶段 0A 一次性盘点资产，
> 脚手架退役清单现行事实源 = 退役登记（check_legacy_orchestration 门禁 + 宪法 §十二），本文档仅供历史追溯。

> 对应《正向设计修复改进计划书》阶段 0A。
> 原则（Anthropic《Effective Harnesses for Long-Running Agents》）：harness 的每个组件都是
> 一条「模型做不到 X」的假设；假设会过期，模型升级即逐件拆测。
> **分类**：脚手架 = 对模型能力缺口的补偿，可折旧；不变量 = 工程/物理约束，长期承重，
> 不走拆除仪式但接受季度审计。
> 每条「假设」栏必须可证伪（写明若模型能做到什么即可删）。
> 审定后入账 `src/video_agent/core/scaffold_registry.py`（计划书 2-1）。

## 一、脚手架（可折旧，入拆除仪式）

| # | 组件 | 假设（模型做不到 X） | 承重证据 | 复测时机 |
|---|------|--------------------|---------|---------|
| ~~S01~~ | ~~`core/stream_suppressor.py` StreamActionSuppressor~~ | **已随 audit-0819b 单轨化删除**（确认改经 FC 工具结构化上抛，文本块通道消失，ADR-0001 执行记录二） | — | — |
| ~~S02~~ | ~~`web/action_parser.py` 退化信号检测~~ | **已随 4-4 双轨退役删除**（ADR-0001，audit-0819） | — | — |
| S03 | `core/agent_loop.py` `_bad_output_nudge` | 模型会连续产出空/畸形输出 | bad_output_retry trace 计数；audit 回归 | 每次主模型切换 |
| S04 | `core/planner.py` `_ADVANCE_CORPUS`/`_ADHOC_VERBS` 路由语料 | 模型不能自决「走编排器还是模型循环」 | 编排器路由回归 | 阶段 3 DAG 化后重估；模型切换时 |
| S05 | `skill_runtime/registry.py` `fallback_skill_from_state` | 请求会丢失 skill 名，需回退 usedSkills 末位（7777） | 7777 回归 | 前端请求恒带 skill_slug 被机械验证后 |
| S06 | `skill_runtime/registry.py` `match_skill_name_from_text` | 用户会直接发 Skill 名而不挂引用块（6666） | 6666 回归 | 前端 @/Skill 引用块覆盖全部唤起路径后 |
| S07 | `core/round_end_policies.py` gate_heal | 模型被闸机拦截后会原样重试，需升级改写指引 | gate_heal 回归 | 每次主模型切换 |
| S08 | `core/round_end_policies.py` false_claim_audit（`_claims_structure_done`） | 模型会虚报「已完成拆解」而状态为空（2222/4444） | 2222/4444 回归 | 每次主模型切换 |
| S09 | `core/planner.py` `_SKILL_REMINDER` 回喂注入 | 模型读了 Skill 全文后仍会忘记暂停点（5555） | 5555 回归 | 编排器机械暂停全覆盖后 |
| S10 | `core/round_end_policies.py` 阶段兜底卡/暂停补发（层 9） | 执行器跑完但模型不自发暂停 | 层 9 回归 | 编排器接管暂停点后 |
| S11 | `skill_runtime/exec_common.py` `_executor_thinking` 思考降档 | 推理模型思考会吃光输出预算（deepseek-v4-flash 单次思考 2.6 万字事故） | 2222 二轮回归 | 每次主模型/执行器模型切换 |
| S12 | `skill_runtime/exec_common.py` `_resolve_cascade_fast` 模型级联（C5） | 快模型誊写批会零进展，需升级保险 | C5 回归 | 每次执行器模型切换 |
| S13 | `core/round_end_policies.py` `aborted_continuation_audit`（本期 1-2 新增） | 模型会说「马上继续」却以 stop 收尾（audit-0819 假停取证） | audit-0819-fakestop 回归 | 每次主模型切换 |
| ~~S14~~ | ~~`web/chat_opening.py` 附件降级全文注入~~ | **已随 4-4 双轨退役删除**（非 FC 聊天通道整体移除，ADR-0001） | — | — |

## 二、不变量（长期承重，季度审计，不入拆除仪式）

| # | 组件 | 为什么不是脚手架 |
|---|------|----------------|
| I01 | `core/token_budget.py` 轮组原子截断 + system_degrader | 上下文窗口有限是物理约束，与模型能力无关 |
| I02 | `core/fc_feedback.py` 惰性压缩/旧轮图片剥离（C3） | token 成本经济学，任何模型都承重 |
| I03 | `adapters/retry.py` + 模型 fallback 链 | 上游网络/服务瞬时故障是物理约束 |
| I04 | `core/guard_pipeline.py` 闸机管线（动作判定唯一入口） | 安全不变量（双轨一致条款随 4-4 单轨化废除） |
| I05 | 渐进式披露（Skill 目录常驻/全文按需 read_*） | 上下文经济学不变量 |
| I06 | `core/prompt_gates.py` GATE_RULES 注册表 + 黄金语料校准 | 安全策略即数据，属宪法不变量 |

## 三、盘点备注

- 本清单为存量快照；新增组件必须经宪法 13.5（含 Q0）决策树入账，禁止裸补丁。
- 4-4 双轨退役已执行（2026-08-19）：S02/S14 下账；audit-0819b 单轨化再下账 S01，基线 14→12→11。
- audit-0819d 四维对齐收尾（2026-08-19，用户裁决）：评估识别的三处存量补丁
  直接删除而非登记入账（基线维持 11）——S15 外来工具名翻译层
  （build_foreign_tool_note）、S16 文本别名归一（split_actions）、
  S17 执行器宽容兜底解析（_parse_actions_from_text 宽容正则）；防复活钉死见
  test_audit0819d_structured_executors。
- audit-0819e 控制流统一（2026-08-19，ADR-0002，1111 事故根治）：S04 概率
  路由语料（_ADVANCE_CORPUS/_ADHOC_VERBS）拆除下账，基线随降；
  替代机制为确定性分诊 + 步间回收 + 阶段前置闸（非脚手架，平台不变量）。
- 棘轮：入账后脚手架计数只降不升（acceptance 门禁，2-1）。
