# FTDYB — 影视创作 Agent 工作台（Video Agent Studio）

对话式影视创作 Agent：以自然语言驱动「故事 → 剧本 → 分镜 → 关键帧 → 视频/音频」全流程，
与第三方画布项目**画布**（大熊画布，端口 3000）配合，素材与节点直接落到画布上。

## 与画布的关系与边界

- 画布是**独立迭代的第三方项目**，代码不在本仓库内。
- **架构铁律 Rule 7**：任何时候禁止修改画布的任何文件；所有交互只走其既有公开接口
  （HTTP API / iframe 嵌入），统一封装在 `src/video_agent/adapters/canvas_adapter.py`。
- 画布侧的新能力需求一律写入 [docs/对画布的需求清单.md](docs/对画布的需求清单.md)，不做单边侵入。
- 完整约束见 [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md)（AI 协作最高优先级约束）。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / Pydantic v2 / httpx / loguru |
| 前端（现行） | SolidJS + TypeScript + Vite + 手写语义 CSS（tokens.css，九轮 B5 起 Tailwind 已摘除）；设置页已 SPA 化（`src/web/`） |
| Agent 核心 | Planner 唯一入口 + 多步工具循环（动作通道单轨 = function calling，ADR-0001/0004 裁决文本轨退役） |
| 测试 | pytest（单元 + 集成）/ vitest / Playwright（e2e 冒烟） |

## 启动方式

需要**两个服务**：画布（端口 3000）+ 本项目（端口 8080）。

### 一键启动（Windows）

```bat
启动服务.bat
```

依次拉起画布 → 本项目 → 打开 http://localhost:8080/ 。

### 手动启动

```bash
# 1. 画布（画布，先行）
cd E:\07 天问\熊布
python main.py            # http://127.0.0.1:3000

# 2. 本项目（Agent 服务）
pip install -r requirements.txt
python -m src.video_agent.web   # http://127.0.0.1:8080
```

画布离线时本项目仍可运行（画布相关功能降级，前端显示离线提示）。

## 开发命令

```bash
# 开发/测试依赖（pytest/pytest-cov 等已归位 requirements-dev.txt，含 -r requirements.txt）
pip install -r requirements-dev.txt

# 后端测试（全量 / 单元 / 集成）
python -m pytest tests/ -q
python -m pytest tests/unit/ -q
python -m pytest tests/integration/ -q

# 前端
npm install
npm run dev          # Vite 开发服务器
npm run build        # 构建到 static/dist/（后端 / 路由优先返回 dist）
npm run check        # tsc --noEmit + eslint
npm run test         # vitest
npm run test:e2e     # Playwright（需两个服务都在运行）
python scripts/install_hooks.py  # 一步安装 pre-commit 钩子（幂等，npm run hooks 同效）
```

CI 配置见 [.github/workflows/ci.yml](.github/workflows/ci.yml)；本地已安装
pre-commit 钩子（commit 前自动跑 pytest 单元 + vitest，安装方式见 `scripts/pre-commit.sh` 头部注释）。

## 目录导览

```
src/video_agent/          后端（FastAPI 应用）
├── core/planner.py       Agent 唯一入口（Rule 1）
├── web/                  FastAPI 路由 + 聊天服务 + SSE
├── state/                StateManager 唯一状态写入点（Rule 3）+ Pydantic 模型
├── adapters/             外部调用统一层（Rule 4），含 canvas_adapter
├── tools/                业务 Tool 体系（Rule 5）
├── skill_runtime/        Skill 执行器运行时（章节→执行器，agent-as-tool）
└── config.py             集中配置（环境变量驱动）

src/web/                  前端（SolidJS SPA）
static/                   构建产物 dist/ + images/（api-settings 嵌入页已 SPA 化移除）
prompts/                  外置 Prompt（Rule 6）
data/                     供应商配置 / 技能文档（data/ 整体 gitignore；技能文档 data/skills/*.md 例外入库，是产品数据源）
tests/                    unit / integration / e2e / fixtures/canvas（契约夹具）
workspace/                运行时状态与资产（gitignore）
```

## 文档索引

> 文档分层（五轮 S8）：`docs/` 根目录只放**现行有效规范**；
> 历史审核报告/整改计划书/恢复文书归档于 `docs/audit-history/`（按轮次检索）。

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md) | 架构铁律（AI 协作强制约束） |
| [docs/GOVERNANCE.md](docs/GOVERNANCE.md) | 指令治理层方法论（原宪法第十三章，与总纲同权） |
| [docs/配置说明.md](docs/配置说明.md) | 各配置文件的权威关系与加载优先级 |
| [docs/前端体验规范.md](docs/前端体验规范.md) | 品牌/视觉/交互细节强制规范 |
| [docs/对画布的需求清单.md](docs/对画布的需求清单.md) | 需要画布侧实现的能力（postMessage 协议等） |
| [docs/audit-history/兼容层移除计划.md](docs/audit-history/兼容层移除计划.md) | 兼容层清偿台账（已完结：版本节点与 D-05 兼容别名尾巴全部清偿，归档于 audit-history） |
| [docs/audit-history/](docs/audit-history/) | 历轮审核报告与整改计划书归档 |
| [tests/fixtures/canvas/README.md](tests/fixtures/canvas/README.md) | 画布 API 契约夹具的录制与刷新方法 |

## 环境与安全

- 复制 `.env.example` 为根目录 `.env` 配置运行参数（端口、画布地址、记忆后端等），
  各配置项的完整说明见 [docs/配置说明.md](docs/配置说明.md)。
- API Key 统一存放于 `API/.env`（已 gitignore，勿提交）。
- `ENVIRONMENT=production` 时所有 `/api/` 请求需携带 `X-API-Key` 头。
