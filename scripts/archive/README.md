# scripts/archive — 历史一次性迁移/补丁工具，已完成使命，不再维护

> 治理沉积物折旧专项归档（批次与裁决留痕见 `CHANGELOG.md`）。各脚本的迁移目标在各自批次内
> 已执行完毕并有验收/防回潮测试兜底；留档仅供追溯，禁止再纳入 acceptance/CI。

## 到期删除策略（设立留痕见 `CHANGELOG.md`）

- **到期即删**：归档脚本自归档日起满两个季度（约 6 个月）即删除；
  首批到期日 2027-03-01（以 2026-08-21/25 归档时点起算），届时由用户裁决执行
  （原「随季度脚手架审计一并裁决」已失效：脚手架台账 / 折旧机器已根除）。
- **删除动作**：直接删除脚本文件 + 本 README 对应行删除（清偿一条、清单删一条）；
  不设逐脚本裁决——到期默认删，例外保留须书面裁决并钉死新到期日。
- **历史留底**：脚本内容与本登记表的完整历史以 git 提交史为准
  （删除前无需另建备份；git 历史即留底）。
- **后续归档件**：新归档脚本入册时在本表登记行注明归档日期，到期日按
  归档日 + 两季度计算，不再逐件写入策略文本。

| 脚本 | 一句话用途 |
|---|---|
| migrate_manifests_to_sidecar.py | B0 批：把 Skill 文档内嵌 manifest 数据等价迁移为 sidecar 声明（registry 双读期收敛用） |
| migrate_skill_executor_names.py | L-0821C 用户裁决批：skill 文档虚构执行器名一律替换为本项目真实执行器/工具名（章节按标题边界拆分，sidecar flow.steps 同步镜像） |
| migrate_storyboard_sections_merge.py | D-24 故事板支清偿批（2026-09-25 归档）：上一条的**反向操作**——14 个 Skill 的故事板三拆章节合并回 `<storyboard_designer>`（正文逐字不改）+ planner 内素材分析步/故事板步字段回写与登记类内联删工具名；dry-run 默认、--apply 落盘，已执行完毕（skill_sections_golden 重采兜底） |
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
| migrate_media_generator_merge.py | D-24 媒体生成支（2026-10-01 归档）：14 个 Skill 的 `<image_generate>`/`<generate_video>`/`<audio_generate>`（含孤立 `<generation>`）合并为单一 `<media_generator>`，**正文逐字不改**（对 golden 逐字节中性）；dry-run 默认、--apply 落盘，已执行完毕 |
| migrate_ref_assets_to_urls.py | 9999 三问批（2026-09-26 归档）：把草稿 `refAssets` 里的**草稿 id** 归一到媒体 URL（实测 79 条全是 id 形态）；**未执行**（用户裁决「只修代码，存量不管」），apply 前须停服务 |
| migrate_9999_sheet_refs.py | 9999 三问批（2026-09-26 归档）：给 11 张「分镜表格图」卡按 `shotRefs` 补规范引用记号（`<<<image_名称>>>`）+ 参考图；**未执行**（同上裁决），dry-run 实测 11/11 全解析；幂等（已含记号的卡自动跳过） |

> **未执行件例外（2026-09-26）**：末两行是本目录**唯一**「已归档但未执行」的脚本
> （上表其余各行均按设立口径「迁移目标已在各自批次内执行完毕」）。
> 两者**不在 acceptance/CI 链路**、不被 pre-commit 调用；成因与清偿条件登记于
> `docs/未清偿债务清单.md` D-25，到期口径同上（归档日 + 两季度，届时随 D-25 一并裁决）。
