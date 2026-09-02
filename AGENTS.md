# AGENTS.md — 改动前必须知道的事

> 本文件是入口索引（§六-§八为自足摘要），不复述规则正文。规则的唯一家见各指针文档；
> 冲突时以 ARCHITECTURE_RULES.md（宪法）为准。

## 一、改动前必须知道的 10 条

1. **宪法优先**：`ARCHITECTURE_RULES.md` 是最高优先级约束（Rule 1-7：
   Planner 唯一入口 / 动作通道单轨 FC / StateManager 唯一写入点 /
   外部调用走 Adapter / Tool 注册与 risk 分级 / 提示词外置 / 画布禁改）。
   违规即错误实现；改完过一遍其 §十二 违规检查清单。
2. **规则只有一个家（P1）**：修改前先按本文件 §八治理条款摘要的决策树
   定位归属层；禁止在事故现场就近补条款、禁止同一规则多层复述。
3. **约束下沉（P2）**：能代码机械校验的，不写 prose「严禁/必须」；
   闸机是执行逻辑（Policy-as-Data，注册表在 `core/gate_registry.py`），
   闸机文案外置 `prompts/gates/messages.md`。
4. **闸门做减法**：闸机/门禁以「保留核心、砍掉仪式」为纲——运行时安全闸
   （tool_risk/gen_confirm/prompt_write）+ 架构闸（layer_imports/contract/
   legacy_orchestration）+ category_keys 防硬编码为核心，保留不动；仪式化门禁
   （脚手架计数棘轮 / 覆盖率镜像基线 / 行数硬闸 / 幽灵闸）已随 2026-09-02
   「治理闸机减负」裁决退役；闸机增减由用户裁决（脚手架见 `core/scaffold_registry.py`）。
5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批
   未提交改动（宪法 §5 血泪条款：开工先备份、禁止裸 restore/checkout）。
6. **状态写入归 StateManager**；路径归 `utils/paths`；可调参数归
   `config.settings`；类别 Key 归 `state/models.py` CAT_* 常量
   （宪法 §六，禁止硬编码替代）。
7. **Skill 是指令性制作手册（2026-08-29 用户裁决，决策史见 git tag `adr-archive-20260901`）**：Skill 改动须过本文件 §八 G1「Skill 改动裁决关」（只读属性已废除）——
   禁止以降低 Skill 要求的方式迁就系统缺陷，优先修平台层；例外须用户显式裁决。
8. **UI 变更必须用户目测**：测试全绿 ≠ UI 正确；构建后经用户目测反馈
   确认才算交付（宪法 §3，不派浏览器子代理截图代目测）。
9. **先读懂再动手**：修改范围最小化，不为「觉得更好」重构无关代码；
   删除前全局搜索确认无引用；注释只写结论不写事故过程（宪法 §9）。
10. **分层验证（快）**：见下节——pre-commit 只跑受影响子集，
    日常验收只认 `acceptance.py --quick`，全量每批末一次。

## 二、分层验证规范

| 场景 | 命令 | 口径 |
|---|---|---|
| commit 前钩子 | `python scripts/install_hooks.py` 安装后自动 | 只跑 staged 改动的受影响测试子集（`scripts/select_affected_tests.py` 映射，目标 10-30s；映射为空才回落全量） |
| 改动后定点验证 | `python -m pytest tests/unit/<相关> -q -n 8 --dist loadfile` / `npx vitest run <相关>` / `npx tsc --noEmit` | 只跑受影响文件，快 |
| 日常验收（唯一依据） | `python scripts/acceptance.py --quick` | 全部门禁 + tsc，只认进程退出码 0，不人眼读输出 |
| 批末验收 | `python scripts/acceptance.py` | 全量：门禁 + pytest/vitest/tsc/eslint 四件套 |
| 终验 | `python scripts/acceptance.py --with-eval` | 批末 + 评测管线 |

纪律：
- 只认进程退出码（Windows GBK 乱码曾把失败伪装成通过）；
- 钩子逃生门：`SKIP_PRECOMMIT=1`（CI 仍全量）/ `FULL_HOOK=1`（强制全量）；
- 批与批之间不攒改动；每批末全量一次，平时 quick；
- cov / fe_cov 为固定容差地板（脚本内写死 COVERAGE_FLOOR，低于地板才 FAIL），
  不再逐批镜像上调基线、无 --update-baseline 仪式（2026-09-02 治理闸机减负裁决）。

## 三、常用命令

```bash
python -m src.video_agent.web      # 后端 FastAPI 服务
npm run dev                        # 前端 Vite 开发服务器
npm run build                      # 前端构建（输出 static/dist/）
npm run check                      # tsc + eslint
python scripts/acceptance.py --quick   # 日常快验（门禁 + tsc）
python scripts/acceptance.py           # 批末全量验收
python scripts/run_eval_pipeline.py    # Skill 管线可解析性评测（frontmatter/manifest 解析底线）
```

## 四、文档指针（规则的家）

| 文档 | 职责 |
|---|---|
| `ARCHITECTURE_RULES.md` | 架构宪法（Rule 1-7 / 闸机宪法 §2 / 前端 §3 / 流程治理 §5 / 文件地图 §十一 / 违规清单 §十二）；只写现行规则 |
| `CHANGELOG.md` | 裁决 / 批次 / 事故历史留痕的**唯一家**（ADR 编号对照、从宪法正文迁出的批次注记、任务 / 内部编号对照、git tag 归档索引） |
| 指令治理层（GOVERNANCE） | 已归档删除，见 git tag `governance-archive-20260901`；活条款摘要见下 §八 |
| 脚手架退役规程 | 已归档删除，见 git tag `scaffold-deprecation-archive-20260901`；活规则摘要见下 §七 |
| `docs/前端体验规范.md` | 飞天品牌/确认卡片/@面板等视觉交互强制约束 |
| `docs/adr/` | 架构决策记录 0001-0007 已归档删除，见 git tag `adr-archive-20260901`；编号→结论对照见 `CHANGELOG.md` §一 |
| 历史审计文书 | 已归档删除，见 git tag `audit-history-archive-20260826` |
| 长期路线图 | 已归档删除，见 git tag `roadmap-archive-20260901`；冻结/暂缓裁决见下节自足表述 |

## 五、机器门禁速查

门禁清单唯一事实源 = `scripts/acceptance.py` GATES 表；门禁增减由用户裁决（宪法 §2.3），仪式化门禁已随 2026-09-02「治理闸机减负」退役。

## 六、未清偿债务与已裁决冻结项

未清偿项集中登记于仓内清单 `docs/未清偿债务清单.md`。
清偿一条、清单删一条；不再开「第 N 轮」修复计划书。

以下为用户显式裁决的冻结/暂缓项（防翻案，非债务；原卷见 git tag
`roadmap-archive-20260901`）：

- 记忆层为**有意空缺**：记忆系统（含语义检索与跨项目偏好沉淀）已随批次 D 有意退役、当前阶段不重建；评审不得将 `data/memory/` 空置或项目隔离空壳判为缺陷；重启须出现跨会话决策丢失的真实事故并经用户裁决。
- 回滚到任意时刻/分叉方案对比：已评估、用户主动暂缓，未经用户提出不得启动；「已评估」不得当作「已批准」引用。
- 不做 skill_search 模型自行检索：业界口径为目录元数据常驻注入 + 模型判断选中 + 按需读全文，另造检索轮子属私货（2026-08-29 用户裁决砍除）。
- 不做社区 + 排序/搜索前端（2026-08-29 用户裁决暂无必要；出现真实用户生态与内容规模再重新登记）。
- 不做 Skill 正文中性化：不检查/不消音 skill 正文任何句式；装外部 skill 视同装软件，安全靠动作单轨/确认闸/platform 安全底线（tool_risk + costly 确认）不可关机械兖底（质量闸严格度另见宪法 §2.1）（2026-08-29 用户裁决，防翻案）。
- 长期项不排期、不立项：展望方向未经触发条件成立与用户裁决不得动工，历史登记见上述 git tag。

## 七、脚手架退役（活规则摘要；原卷见 git tag `scaffold-deprecation-archive-20260901`）

- scaffold 条目登记于 `core/scaffold_registry.py`（数据保留供人读审查）；计数棘轮 `SCAFFOLD_COUNT_BASELINE` 已随 2026-09-02「治理闸机减负」裁决退役，不再逐件机械兜底。
- 退役由用户裁决逐件下账（删代码 + 注册表删条目），不再走「连续 N 周期零触发自动降级 / audit_gate_triggers」仪式。
- `scripts/archive` 归档件到期策略唯一家为 `scripts/archive/README.md`（满两季度即删）。

## 八、治理条款摘要（原宪法第十三章/GOVERNANCE；原卷见 git tag `governance-archive-20260901`）

- **P1 单一事实源**：每条规则只有一个表述源，其他层只能引用不得复述；引导与校验冲突时以代码校验的客观结果为准并修表述。
- **P2 约束下沉**：能被代码机械校验的一律实现为代码校验（拒收/修正），禁止用「严禁/必须」prose 说服模型；代码校验只裁定模型产出的格式与客观状态，不拦用户意志。
- **P3 状态即数据**：注入给模型的状态/工具结果必须是纯客观数据，引导语独立且极短，禁止把说教嵌入数据体。
- **修复决策树**：先查现有机制/下一代模型是否已覆盖（证明不覆盖才新增组件并入脚手架台账）→ 定位规则唯一定义层（找不到归属 = 新规则按层安家）→ 能代码校验就下沉、不能则只改唯一定义层 → 清除其他层分身 → 回归测试带事故编号 → 查耦合行。确定性三问判别：答案可算＋机器可判＋无创作空间→收归系统；仅可判→模型写系统验收；都不是→留模型人审。
- **捷径禁令**：禁止在事故现场就近补条款；同一规则不得两层以上新增表述；新增 prose 禁令前必须回答「为何不能被代码校验」。
- **方案四关（G1-G4）**：G1 Skill 改动不得以降低要求迁就系统缺陷、优先修平台层；G2 出方案前先查既有机制（缺口假设须 eval 证明）；G3 禁止「写一句话让模型配合机制」式 prose 方案；G4 事故修复覆盖同类全部调用路径（统一策略 + 钉死回归 + 台账三件套）。
- **指令体量**：`prompts/planner/system_fc.md` 展开后保持精简、靠人工审核控制体量（原「≤7KB 机械预算闸」已随 2026-09-02「治理闸机减负」裁决退役，不再机械强制、亦不恢复机械闸）；回喂话术单条 ≤ 3 句；同一规则定义处恒等于 1。
- **门禁登记**：新增门禁脚本在 `scripts/acceptance.py` GATES 表同步登记；闸机增减由用户裁决（宪法 §2.3）。
- **错误信封必须抛错**：适配器层识别上游拒收并抛错（不当稿子），错误展示走人话 + 原文折叠。
- **治理限速**：全面审核报告每季度至多 1 篇；不再开「第 N 轮」修复计划书，清偿动作唯一载体是未清偿清单（清偿一条、清单删一条）。
