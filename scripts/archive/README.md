# scripts/archive — 历史一次性迁移/补丁工具，已完成使命，不再维护

> 治理沉积物折旧专项（P2a，2026-08-21）归档。各脚本的迁移目标在各自批次内
> 已执行完毕并有验收/防回潮测试兜底；留档仅供追溯，禁止再纳入 acceptance/CI。

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
