# scripts/archive — 历史一次性迁移/补丁工具，已完成使命，不再维护

> 治理沉积物折旧专项（P2a，2026-08-21）归档。各脚本的迁移目标在各自批次内
> 已执行完毕并有验收/防回潮测试兜底；留档仅供追溯，禁止再纳入 acceptance/CI。

## 到期删除策略（任务 #12 批次2 设立，2026-08-26）

- **到期即删**：归档脚本自归档日起满两个季度（约 6 个月）即删除；
  首批到期日 2027-03-01（以 2026-08-21/25 归档时点起算），届时随季度
  脚手架审计（折旧规程第二节）一并裁决执行。
- **删除仪式**：直接删除脚本文件 + 本 README 对应行删除（清偿一条、清单删一条）；
  不设逐脚本裁决——到期默认删，例外保留须书面裁决并钉死新到期日。
- **历史留底**：脚本内容与本登记表的完整历史以 git 提交史为准
  （删除前无需另建备份；git 历史即留底）。
- **后续归档件**：新归档脚本入册时在本表登记行注明归档日期，到期日按
  归档日 + 两季度计算，不再逐件写入策略文本。

| 脚本 | 一句话用途 |
|---|---|
| migrate_manifests_to_sidecar.py | B0 批：把 Skill 文档内嵌 manifest 数据等价迁移为 sidecar 声明（registry 双读期收敛用） |
| migrate_skill_executor_names.py | L-0821C 用户裁决批：skill 文档虚构执行器名一律替换为本项目真实执行器/工具名（章节按标题边界拆分，sidecar flow.steps 同步镜像） |
| migrate_skill_manifests.py | S1 批：为存量 Skill 补写 skill_manifest 配置块并删除 pause_rules/gate_rules 块 |
| migrate_spec_model_params.py | B7 批：规格文档中硬编码的生成模型参数迁移为引用全局设置（dry-run/--apply 两档）+ Skill 写死参数扫描报告 |
| add_spec_gate.py | S1 批：规格前置闸从 Skill manifest 迁移为 sidecar flow.spec_gate 声明 |
| dedupe_draft_ids.py | 一次性修复存量项目 draft/group/asset 重复 id（gen_id 低 3 位碰撞导致约 14% 重复；JSON + SQLite 双存储覆写） |
| clean_incident_refs.py | 九轮 9b 批：注释/docstring 事故编号叙事机械清点（只重写注释文本，防误删设白名单模式） |
| clean_temp_artifacts.py | 临时产物清扫：.pytest_tmp / .playwright-cli 等堆积调试文件（默认 dry-run，--apply 真删） |
| audit_skill_gates.py | 只读审计：盘点 Skill prompt_draft 下小节，为 skill_manifest gates 数据配置提供依据 |
| migrate_step_stages.py | P3-12 批：为 16 个 sidecar manifest 幂等补写 flow.step_stages 显式声明（schema v2，已执行完毕并有 test_sidecar_schema_v2 兜底） |
| migrate_manifests_to_frontmatter.py | 任务#5：16 个外置 JSON sidecar 声明迁入 Skill 文档头部 YAML frontmatter（flow.steps/step_stages/dependencies 三键废除不迁；已执行完毕，data/skills_manifests/ 随迁删除） |
| migrate_manifests_v3.py | 任务#34 B1：manifest v2→v3 幂等迁移（schema_version/requires_inputs/pause_points 只加不删）；默认目录 data/skills_manifests 已随任务#5 frontmatter 合一删除，仅 --dir 演练可用（test_sidecar_schema_v3 兜底） |
| migrate_zombie_step_keys.py | 三维审查修复收尾批：清除 Skill frontmatter flow 下步骤号僵尸键（stage_executors/step_done_conditions/step_short_titles）存量（dry-run 默认，--apply 真删）；已执行完毕（test_zombie_step_keys 锁源同值+幂等兜底，2026-08-25 归档） |
