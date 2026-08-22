# action_executor 下沉计划（审核整改批 8，仅规划不动码）

> **性质：活跃（欠账 D-01 登记于项目外清单 E:\07 天问\未清偿债务与事故清单-2026-08-22.md）；复审到期日 2026-09-30。**

- 状态：规划已登记（scaffold_registry I09 承重壳，2026-08-21）
- 对象：`src/video_agent/web/action_executor.py`（885 行，宪法 Rule2 层级例外）
- 问题：按分层约束，故事板写域与动作语义应在 core/state 层；该文件因依赖
  web 生成管线（`web/generation.py`）暂留 web 层，是 core→web 边界上最大
 的一块未下沉债务。

## 现状边界（下沉前禁改）

- 对外行为冻结：studio-actions 结构化 dict 的执行语义、闸机接入
  （guard_pipeline 共用判定）、生成确认闸（`_gen_confirm_gate`）、
  一条龙豁免消费（`flow_auto_continue`）均不得在下沉前变更；
- 消费方：mock 演示通道、web 生成管线、既有集成测试。

## 两阶段路线

### 阶段一：生成动作域下沉（前置：生成管线依赖梳理）

1. 梳理 `action_gen.py` / `_apply_generate_image` / `_apply_generate_video`
   对 `web/generation.py` 的依赖面（任务提交/轮询/SSE 通知）；
2. 将依赖抽象为 core 层接口（生成端口），web 层保留实现（端口/适配器姿势，
   与 Rule4 Adapter 体系一致）；
3. 生成动作域迁入 core（或 skill_runtime）后经构造注入装配，集成测试回归。

### 阶段二：故事板写域收编（前置：阶段一完成）

1. `_apply_add_draft/_apply_draft_patch/_apply_group_patch/_apply_delete_*`
   等故事板写域逐节对照 `state/storyboard_ops.py`（动作语义唯一实现既有原则）；
2. 重复逻辑归 storyboard_ops，action_executor 仅保留动作分发薄壳直至消费方迁完；
3. 消费方（mock 演示通道等）迁移后，action_executor 空壳删除，
   scaffold_registry I09 下账。

## 验收（每阶段）

- `python scripts/acceptance.py` 全 PASS（只认退出码）；
- 阶段涉及的集成测试全绿 + 闸机黄金语料无劣化；
- 下沉批次遵守宪法 §5（开工先备份、每批即 commit、劣化即回退）。

## 风险

- 承重壳迁移期间任何行为漂移都会污染 mock 演示与生成管线：故采用
  「先抽接口、后迁实现、最后删壳」三步，禁止一次性重写（宪法 §9）。
