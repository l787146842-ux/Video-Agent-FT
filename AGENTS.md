# AGENTS.md — 改动前必须知道的事

> 本文件是入口索引，不复述规则正文。规则的唯一家见各指针文档；
> 冲突时以 ARCHITECTURE_RULES.md（宪法）与 docs/GOVERNANCE.md 为准。

## 一、改动前必须知道的 10 条

1. **宪法优先**：`ARCHITECTURE_RULES.md` 是最高优先级约束（Rule 1-7：
   Planner 唯一入口 / 动作通道单轨 FC / StateManager 唯一写入点 /
   外部调用走 Adapter / Tool 注册与 risk 分级 / 提示词外置 / 画布禁改）。
   违规即错误实现；改完过一遍其 §十二 违规检查清单。
2. **规则只有一个家（P1）**：修改前先按 `docs/GOVERNANCE.md` §13.5 决策树
   定位归属层；禁止在事故现场就近补条款、禁止同一规则多层复述。
3. **约束下沉（P2）**：能代码机械校验的，不写 prose「严禁/必须」；
   闸机是执行逻辑（Policy-as-Data，注册表在 `core/gate_registry.py`），
   闸机文案外置 `prompts/gates/messages.md`。
4. **闸门只减不增**：闸机/门禁/脚手架/白名单全部棘轮化管理——
   新增须事故依据 + 退役条件 + 书面裁决（GOVERNANCE §13.14）；
   清偿一条、台账删一条（脚手架见 `core/scaffold_registry.py`，
   耦合行见 `core/coupling_registry.py`，同批更新漏改即红）。
5. **小批交付、即时提交**：每批独立 commit、独立验收；禁止攒大批
   未提交改动（宪法 §5 血泪条款：开工先备份、禁止裸 restore/checkout）。
6. **状态写入归 StateManager**；路径归 `utils/paths`；可调参数归
   `config.settings`；类别 Key 归 `state/models.py` CAT_* 常量
   （宪法 §六，禁止硬编码替代）。
7. **Skill 是数据不是指令**：禁止修改 `data/skills/*` 迁就系统缺陷
   （G1）；Skill 要求与系统行为不符时修平台层；例外须用户显式裁决。
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
- 批与批之间不攒改动；每批末全量一次，平时 quick。

## 三、常用命令

```bash
python -m src.video_agent.web      # 后端 FastAPI 服务
npm run dev                        # 前端 Vite 开发服务器
npm run build                      # 前端构建（输出 static/dist/）
npm run check                      # tsc + eslint
python scripts/acceptance.py --quick   # 日常快验（门禁 + tsc）
python scripts/acceptance.py           # 批末全量验收
python scripts/run_eval_pipeline.py    # 闸机黄金语料评测
```

## 四、文档指针（规则的家）

| 文档 | 职责 |
|---|---|
| `ARCHITECTURE_RULES.md` | 架构宪法（Rule 1-7 / 闸机宪法 §2 / 前端 §3 / 流程治理 §5 / 文件地图 §十一 / 违规清单 §十二） |
| `docs/GOVERNANCE.md` | 指令治理层（与宪法同权）：P1-P3 原则、13.5 决策树、G1-G4 方案四关、§13.14 治理刹车（门禁冻结 (f)） |
| `docs/脚手架折旧规程.md` | 脚手架拆除仪式 + 棘轮门禁折旧 + scripts/archive 到期策略 |
| `docs/前端体验规范.md` | 飞天品牌/确认卡片/@面板等视觉交互强制约束 |
| `docs/adr/` | 架构决策记录（取代关系须双边注记） |
| 历史审计文书 | 已归档删除，见 git tag `audit-history-archive-20260826` |
| `docs/长期路线图-2026-08-22.md` | 长期项登记（不排期、不立项） |

## 五、机器门禁速查（清单唯一事实源 = scripts/acceptance.py GATES 表）

契约（gen_api_types --check）/ 提示词预算 / 文件行数双棘轮 / 语义色收口 /
方法内 import / 类别 Key / 退役符号防复活 / 层间导入方向 /
引用完整性（文档指针+宪法锚点合并，裁决 R11）/ 脚手架计数 / 前后端覆盖率棘轮 /
Skill 工具名对齐。
每条带退役条件声明；新增门禁必须先立项（GOVERNANCE §13.14(e)/(f)）。

## 六、未清偿债务

未清偿项集中登记于仓内清单 `docs/未清偿债务清单.md`（GOVERNANCE §13.10）。
清偿一条、清单删一条；不再开「第 N 轮」修复计划书。
记忆层为有意空缺（批次 D 退役、不重建）、回滚/分叉用户主动暂缓，
均属用户裁决的展望项而非债务，详见 `docs/长期路线图-2026-08-22.md`（L4/L14/L19）。
