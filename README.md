# FTDYB — 影视创作 Agent 工作台（Video Agent Studio）

对话式影视创作 Agent：以自然语言驱动「故事 → 剧本 → 分镜 → 关键帧 → 视频/音频」全流程，
与第三方画布项目**熊布**（大熊画布，端口 3000）配合，素材与节点直接落到画布上。

## 与熊布的关系与边界

- 熊布是**独立迭代的第三方项目**，代码不在本仓库内。
- **架构铁律 Rule 7**：任何时候禁止修改熊布的任何文件；所有交互只走其既有公开接口
  （HTTP API / iframe 嵌入），统一封装在 `src/video_agent/adapters/canvas_adapter.py`。
- 熊布侧的新能力需求一律写入 [docs/对熊布的需求清单.md](docs/对熊布的需求清单.md)，不做单边侵入。
- 完整约束见 [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md)（AI 协作最高优先级约束）。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / Pydantic v2 / httpx / loguru |
| 前端（现行） | SolidJS + TypeScript + Vite + TailwindCSS（`src/web/`） |
| 前端（legacy，待移除） | 原生 JS 单页 `static/studio.html`（见 [兼容层移除计划](docs/兼容层移除计划.md)） |
| Agent 核心 | Planner 唯一入口 + 多步工具循环（function calling / 文本动作双路径） |
| 记忆 | 自研记忆系统（chromadb 向量检索，可降级 JSON 关键词检索） |
| 测试 | pytest（单元 + 集成）/ vitest / Playwright（e2e 冒烟） |

## 启动方式

需要**两个服务**：熊布（端口 3000）+ 本项目（端口 8080）。

### 一键启动（Windows）

```bat
启动服务.bat
```

依次拉起熊布 → 本项目 → 打开 http://localhost:8080/ 。

### 手动启动

```bash
# 1. 熊布（画布，先行）
cd E:\07 天问\熊布
python main.py            # http://127.0.0.1:3000

# 2. 本项目（Agent 服务）
pip install -r requirements.txt
python -m src.video_agent.web   # http://127.0.0.1:8080
```

熊布离线时本项目仍可运行（画布相关功能降级，前端显示离线提示）。

CLI 路径（无 Web）：

```bash
python cli.py "你的创作目标" --workflow config/default_workflow.json
```

## 开发命令

```bash
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
├── memory/               长期记忆系统
├── workflows/            六阶段工作流引擎 + SSE
└── config.py             集中配置（环境变量驱动）

src/web/                  新前端（SolidJS SPA）
static/                   legacy 前端 + 构建产物 dist/ + 共享 CSS/JS
prompts/                  外置 Prompt（Rule 6）
config/                   CLI 工作流定义
data/                     供应商配置 / 技能文档 / 记忆 fallback（gitignore）
tests/                    unit / integration / e2e / fixtures/canvas（契约夹具）
workspace/                运行时状态与资产（gitignore）
```

## 文档索引

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md) | 架构铁律（AI 协作强制约束） |
| [docs/配置说明.md](docs/配置说明.md) | 各配置文件的权威关系与加载优先级 |
| [docs/对熊布的需求清单.md](docs/对熊布的需求清单.md) | 需要熊布侧实现的能力（postMessage 协议等） |
| [docs/兼容层移除计划.md](docs/兼容层移除计划.md) | legacy 前端 / 别名端点 / DEPRECATED 模块的移除时间表 |
| [docs/修复改进计划书-2026-08.md](docs/修复改进计划书-2026-08.md) | 2026-08 全面审查后的三批次修复计划 |
| [tests/fixtures/canvas/README.md](tests/fixtures/canvas/README.md) | 熊布 API 契约夹具的录制与刷新方法 |

## 环境与安全

- 复制 `.env.example` 为根目录 `.env` 配置运行参数（端口、熊布地址、记忆后端等），
  各配置项的完整说明见 [docs/配置说明.md](docs/配置说明.md)。
- API Key 统一存放于 `API/.env`（已 gitignore，勿提交）。
- `ENVIRONMENT=production` 时所有 `/api/` 请求需携带 `X-API-Key` 头。
