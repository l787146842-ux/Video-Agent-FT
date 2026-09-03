# AGENTS.md — 改动前必须知道的事

> 入口索引：只放指针与操作口径，不复述规则正文（P1）。规则唯一家见 §四；冲突时以 `ARCHITECTURE_RULES.md`（宪法）为准。

## 一、改动前必须知道的 5 条

1. **宪法优先**：`ARCHITECTURE_RULES.md` 是最高优先级约束（Rule 1-7 / 闸机宪法 §2 / 前端 §3 / 流程治理 §5 / 文件地图 §十一 / 违规清单 §十二）；违规即错误实现，改完过一遍其 §十二 违规检查清单。
2. **规则只有一个家**：治理条款（P1 单一事实源 / P2 约束下沉 / P3 状态即数据、修复决策树、捷径禁令、方案四关 G1-G4）唯一家 = `docs/GOVERNANCE.md`（见 §八）；修改前先按其修复决策树定位归属层，禁止在事故现场就近补条款、禁止同一规则多层复述。
3. **门禁不在文档枚举**：清单唯一事实源见 §五；闸机增减由用户裁决（宪法 §2.3）。
4. **交付纪律**：小批 commit、独立验收（分层口径见 §二）；UI 变更须构建后经用户目测确认（宪法 §3.1）。
5. **改动最小化**：先读懂再动手、不为「觉得更好」重构无关代码、删除前全局搜索确认无引用（宪法 §9）。

## 二、分层验证规范

| 场景 | 命令 | 口径 |
|---|---|---|
| commit 前钩子 | `python scripts/install_hooks.py` 安装后自动 | 只跑 staged 改动的受影响测试子集（`scripts/select_affected_tests.py` 映射，目标 10-30s；映射为空才回落全量） |
| 改动后定点验证 | `python -m pytest tests/unit/<相关> -q -n 8 --dist loadfile` / `npx vitest run <相关>` / `npx tsc --noEmit` | 只跑受影响文件，快 |
| 日常验收（唯一依据） | `python scripts/acceptance.py --quick` | GATES（静态门禁）+ tsc，只认进程退出码 0，不人眼读输出；**不含覆盖率地板**（cov/fe_cov 归批末 RATCHETS，quick 全绿 ≠ 覆盖率安全） |
| 批末验收 / 终验 | `python scripts/acceptance.py`（终验加 `--with-eval`） | 全量三阶段：GATES + SUITES（pytest/vitest/tsc/eslint）+ RATCHETS（覆盖率后置断言）；`--with-eval` 追加评测管线 |

纪律：只认进程退出码（Windows GBK 乱码曾把失败伪装成通过）；钩子逃生门 `SKIP_PRECOMMIT=1`（CI 仍全量）/ `FULL_HOOK=1`（强制全量）；批与批之间不攒改动、每批末全量一次平时 quick；cov / fe_cov 为固定容差地板（脚本内写死 COVERAGE_FLOOR，低于地板才 FAIL），不再逐批镜像上调基线、无 --update-baseline 仪式。

## 三、常用命令

```bash
python -m src.video_agent.web    # 后端 FastAPI 服务
npm run dev / build / check      # 前端 Vite 开发 / 构建（输出 static/dist/）/ tsc + eslint
python scripts/acceptance.py --quick   # 日常快验（GATES + tsc）
python scripts/acceptance.py           # 批末全量验收（终验追加 --with-eval）
python scripts/run_eval_pipeline.py    # Skill 管线可解析性评测（frontmatter/manifest 解析底线）
```

## 四、文档指针（规则的家）

| 文档 | 职责 |
|---|---|
| `ARCHITECTURE_RULES.md` | 架构宪法（Rule 1-7 / 闸机宪法 §2 / 前端 §3 / 流程治理 §5 / 文件地图 §十一 / 违规清单 §十二）；只写现行规则 |
| `docs/GOVERNANCE.md` | 治理条款唯一家（三原则、修复决策树、捷径禁令、方案四关 G1-G4、指令体量、门禁登记、错误信封、治理限速） |
| `CHANGELOG.md` | 裁决 / 批次 / 事故历史留痕的**唯一家**（ADR 编号对照、近期活跃批次注记、任务 / 内部编号对照、已整卷归档原文件的 git tag 索引、历史分卷索引 §五） |
| `docs/history/` | 较早历史留痕的物理分卷（2026-09-01 及更早，verbatim 搬移自 `CHANGELOG.md` §二；逐卷索引见其 §五） |
| `docs/前端体验规范.md` | 飞天品牌 / 确认卡片 / @面板等视觉交互强制约束 + 条款→验证映射台账 |
| `docs/未清偿债务清单.md` / `docs/冻结与暂缓清单.md` | 未清偿债务与事故残留项 / 用户已裁决的冻结 · 暂缓项（口径见 §六） |
| `scripts/archive/README.md` | `scripts/archive/` 归档件到期策略唯一家（见 §七） |

## 五、机器门禁

GATES 表（静态架构扫描）+ RATCHETS 表（覆盖率后置断言）在 `scripts/acceptance.py`，两表即门禁清单唯一事实源；文档层不枚举、不镜像数字。

## 六、债务与冻结项

未清偿债务登记于 `docs/未清偿债务清单.md`（清偿一条、清单删一条；不再开「第 N 轮」修复计划书）；用户已裁决的冻结 / 暂缓项（防翻案，非债务）登记于 `docs/冻结与暂缓清单.md`。

## 七、台账与归档件

脚手架 / 耦合台账已根除（裁决留痕见 `CHANGELOG.md` §二），组件取舍回到普通工程判断与回归测试；归档件到期策略见 §四 指针。

## 八、治理条款

唯一家 = `docs/GOVERNANCE.md`（原宪法第十三章 / GOVERNANCE 活条款；原卷见 git tag `governance-archive-20260901`）。
