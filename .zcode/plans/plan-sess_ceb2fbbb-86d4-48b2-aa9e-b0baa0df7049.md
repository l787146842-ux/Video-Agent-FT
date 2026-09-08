# 1000 事故正向修复：同意章程收拢 + 告示牌同源 + 兜底网（三小批）

## 背景与目标

9999→1000 两次事故同根：「什么算用户同意」没有唯一答案（4 条同意路径各自为政）、承诺文案与闸机实现脱节（空头支票）、部分拒收轮无回喂、假话口播无对账。本方案按 外部标杆 正向设计收拢，**不开计划书**（GOVERNANCE §六），载体 = 债务清单 D-18/D-19 登记 + CHANGELOG 留痕。

用户已批准三项裁决：①暂停卡 accept 同意扩展覆盖规格兑现写入（写规格文档放行），铁律文档保护不涉；②「本次放行」「草稿标已确认」保留为入口、背后走同一判定；③新增文案一致性门禁进 GATES。

## 影响面结论（已三路调查核实）

- skill 系统：15 份 SKILL.md 零冲突，一个字不改。
- 工具系统：零改动（detail_tier/risk/costly/is_spec_doc_name 全部现成）。
- 后端 web/前端：同意登记端零改动；前端仅设置页 hint 几行字（构建后用户目测）。
- 核心闸机层 = 主战场；agent_loop 两处小改；重试/恢复/降级路径不碰同意状态（已核实零牵连）。

## 批一 · 同意章程（核心）

1. `src/video_agent/core/guard_pipeline.py`：新增模块级同意章程声明表（来源 pause_accept/override/drafts_confirmed/pref × 动作类 costly生成/规格写入/其他high → 放行与否，policy-as-data）；`evaluate_tool_risk`/`evaluate_gen_confirm` 收敛为读表判定，留痕格式兼容（GateVerdict 不变，`consent=pause_accept` message 前缀保留）。
2. `consented` 作用域：`if costly:` → `if costly or is_spec_write:`，其中 `is_spec_write` 由 `fc_gates.tool_risk_gate`（签名已有 args，L195-205 调用处）用 `prompt_gates.is_spec_doc_name(args.name)` 判定后传入。普通非 costly 高危（如"大纲.md"）照旧拦；MCP/未注册工具 deny-by-default 兜底不动；`image_generate` 条件豁免与双闸叠加不变量（TestCostlyToolNoZeroConfirmPath）原样保绿。
3. 登记端零改动：chat_consume.py 账本、gate_overrides 轮粒度消费（planner_gate_session）、drafts_confirmed 三条写入路径全部不动。
4. 宪法同步：ARCHITECTURE_RULES.md §2.4（同意来源枚举）§2.7（同意矩阵）；改完过 §十二检查清单。
5. 测试：test_guard_pipeline_branches L112-116 拆两半（非规格非costly仍拒 + 规格写入放行）；test_tool_risk_gate 补规格名变体；9999 冒烟逐字保绿；新增 1000 放行段回归（ScriptedAdapter：document_write 被拒→发暂停卡→accept→重提放行→规格落盘→「规格已完成」事件卡，积木全部现成）。

## 批二 · 告示牌同源

1. 拒因文案按动作类型分支：prompts/gates/messages.md 新增非生成类高危拒因分节（如实说「点本次放行/工作台确认」，不再承诺 pause-accept）；生成/规格类保留现承诺（批一后成真）。保留「高风险工具确认闸拦截」头部前缀（15 处测试前缀断言保绿）。代码侧继续走 `_gate_msg` Call 形态（prompt_literals 豁免）。
2. 新门禁 `scripts/check_consent_copy.py`：校验 5 处文案（messages.md 两节+新增节、protocol.md L6、execution_preference.md、ExecutionPreferenceSection.tsx hint）承诺要素 ⊆ 章程允许、无 C1a 已废的文本解读式同意暗示；fail-closed、纯 ASCII 输出、无网络。登记：acceptance.py GATES 表 + test_gate_canaries.py `_EXPECTED_GATE_NAMES`（顺序敏感）+ 双向 canary。
3. 补 wiring 等值断言：test_gate_pipeline_wiring 把 TOOL_RISK_BLOCKED_MSG 等纳入「兜底==外置分节」校验，收掉盲区。
4. protocol.md L6 措辞如调整，同批更新 test_gate_messages_coverage L113 子串断言；execution_preference.md 分节纳入门禁（原无锁）。
5. 设置页 hint 微调（如需）+ 构建后用户目测（宪法 §3.1）。

## 批三 · 兜底网

1. 回喂放宽：turn_executor `_extra` 增 `rejected_productive_tools`（tool_results ok=False 条目 × 工具声明推导：detail_tier=="expand" 或 risk∈{medium,high}，排除 workflow_pause；不区分闸拒收/执行失败——两者都该让模型面对事实）；agent_loop L524 放宽为 `_all_rejected or bool(rejected_productive_tools)`，注释同步。
2. 收敛保障：per-turn 产出类续轮上限 2（recovery_policy 表加一行，policy-as-data；超限走轮末收尾+warnings+「继续完成」按钮，复用现成形态）。max_steps 封顶天然兜底不变。
3. 对账扩展：round_end_policies 宣称正则泛化为「产物类型→宣称句式+空判定谓词」映射（补规格句式如「规格已写入」；保留将来时豁免，4444 误报校准基调不动）；false_claim_audit 与 agent_loop 确认轮审计共用扩展实现；warnings 消费链现成（前端零改动）。
4. 1000 回归补回喂段：被拒（无 overrides）→ 拒因回喂进下一轮 → 模型发暂停卡（不全拒收轮也续轮）；同轮纯读类失败照旧提前终止的负样本。
5. 批末 `python scripts/acceptance.py` 退出码 0；三批各自独立验收后 commit（SKIP_PRECOMMIT 不用）。

## 登记与收尾

- `docs/未清偿债务清单.md`：D-18 = 1000 事故清偿（本三批）；D-19 = write_spec 探针缺 "spec" 键导致 workflow 账本该节点恒未完成（既有缺口，备查）；死 re-export（GENERATION_CONFIRM_GATE_ERROR / DRAFTS_REVIEW_*）与孤儿函数 text_mentions_spec_doc 记入 D-18 备注不删（改动最小化）。
- CHANGELOG.md §二 登记三批与裁决（含「非花钱高危不吃同意」收窄裁决的修正说明）。
- 验收口径：每批定点测试 + quick；批末全量 acceptance（不含 --with-eval，非终验）。

## 明确不做

- skill 散文、工具声明、同意登记端、gate_overrides 轮粒度消费、前端按钮/API：零改动。
- gate_overrides 按 rule_id 精细放行（现消费端为轮粒度，动了会破坏既有测试与线束）：不做。
- stage_done 补 spec 探针（超出范围）：只登记 D-19。
- 外部标杆 积分/会员体系：继续缓办（既有裁决）。