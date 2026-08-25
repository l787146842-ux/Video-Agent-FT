# action_executor 下沉计划（审核整改批 8，仅规划不动码）

> **性质：部分清偿（欠账 D-01 登记于项目外清单 E:\07 天问\未清偿债务与事故清单-2026-08-22.md）；阶段二复审到期日 2026-09-30。**

- 状态：阶段一已完成（2026-08-22，D-01 清偿批）；阶段二大部分已完成
  （任务 24 P7-3），剩余为实例方法壳的最终收编与销账
- 对象：~~`src/video_agent/web/action_executor.py`~~（885 行）→ 已下沉 `src/video_agent/core/action_executor.py`；web 侧 re-export 壳已清退，消费方均直接导入 core（任务 #13 F-4）
- 问题：按分层约束，故事板写域与动作语义应在 core/state 层；该文件因依赖
  web 生成管线（`web/generation.py`）暂留 web 层，曾是 core→web 边界上最大
 的一块未下沉债务（已于 2026-08-22 清偿）。

## 阶段一落地记录（2026-08-22）

- 依赖倒置：新建 `core/ports.py` 端口注册表（generation / provider_config /
  task_log / skill_docs 四端口），`web/port_wiring.py::install_core_ports()`
  在三处装配点注入（web/app.py lifespan、tests/conftest.py、
  scripts/run_eval_pipeline.py）；端口持 web 模块引用、属性调用时解析，
  存量测试对 web 模块属性的 monkeypatch 仍生效；
- 迁移：git mv 四件入 core（action_executor / action_gen /
  action_descriptions / prompt_refs）；web 侧四件改 re-export 壳；
- 清零：core 层 10 处 core→web 延迟导入全部移除（planner 3 处、
  fc_tool_runner 3 处、gates_spec / option_groups / token_budget / agent_loop
  各 1 处）；core 层不再存在对 web 层的任何 import；
- 行为冻结：studio-actions dict 执行语义、guard_pipeline 共用判定、
  `_gen_confirm_gate`、`flow_auto_continue` 豁免均未变更；单测基线不变；
- 偏差说明：本计划阶段一原定「仅生成动作域下沉」，实际为一次性清偿
  D-01 债务将整执行器四件一并下沉（依赖倒置同时覆盖 provider_config，
  超出原计划仅 generation 的端口面）；路线方向一致，范围扩大；
- 登记同步：`func_imports_baseline.txt` 刷新（177→126 条）、
  ARCHITECTURE_RULES.md 层级例外条款改「已清偿」、scaffold_registry I09
  更新为清偿后形态、coupling_registry 符号路径改 core。

## 现状边界（下沉前禁改）

- 对外行为冻结：studio-actions 结构化 dict 的执行语义、闸机接入
  （guard_pipeline 共用判定）、生成确认闸（`_gen_confirm_gate`）、
  一条龙豁免消费（`flow_auto_continue`）均不得在下沉前变更；
- 消费方：mock 演示通道、web 生成管线、既有集成测试。

## 两阶段路线

### 阶段一：生成动作域下沉（前置：生成管线依赖梳理）✅ 已完成（2026-08-22，见上方落地记录）

1. 梳理 `action_gen.py` / `_apply_generate_image` / `_apply_generate_video`
   对 `web/generation.py` 的依赖面（任务提交/轮询/SSE 通知）；
2. 将依赖抽象为 core 层接口（生成端口），web 层保留实现（端口/适配器姿势，
   与 Rule4 Adapter 体系一致）；
3. 生成动作域迁入 core（或 skill_runtime）后经构造注入装配，集成测试回归。

### 阶段二：故事板写域收编（前置：阶段一完成）— 大部分已完成（任务 24 P7-3），剩余为实例方法壳的最终收编与 I09 销账

1. `_apply_add_draft/_apply_draft_patch/_apply_group_patch/_apply_delete_*`
   等故事板写域实现体已切出 `core/action_drafts.py`，12 处委托
   `state/storyboard_ops.py` 纯函数（动作语义唯一实现既有原则）；
2. action_executor 仅保留实例方法壳（patch 目标不变），待最终收编；
3. web 消费方已直接导入 core（re-export 壳已清退，任务 #13 F-4）；
   剩余：实例方法壳收编删除后，scaffold_registry I09 下账。

## 验收（每阶段）

- `python scripts/acceptance.py` 全 PASS（只认退出码）；
- 阶段涉及的集成测试全绿 + 闸机黄金语料无劣化；
- 下沉批次遵守宪法 §5（开工先备份、每批即 commit、劣化即回退）。

## 风险

- 承重壳迁移期间任何行为漂移都会污染 mock 演示与生成管线：故采用
  「先抽接口、后迁实现、最后删壳」三步，禁止一次性重写（宪法 §9）。
