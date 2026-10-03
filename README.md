<p align="center">
  <img src="static/images/logo.png" width="88" alt="FTDYB logo">
</p>

<h1 align="center">FTDYB · 影视创作 Agent 工作台</h1>

<p align="center">由 <b>Skill 驱动流程</b>的对话式影视创作 Agent —— 制作流程写在文档里，不写死在代码里。</p>

> [!NOTE]
> **本项目仍在持续迭代**，尚未稳定，历史数据格式不保证兼容；不少地方仍有待改进。
> 欢迎提意见、报问题、给建议 —— 联系方式见文末。

## 它是什么

**一个以 Skill 作为视频制作流程、据此控制视频生产的 Agent。**

每套 Skill 是一份 Markdown 制作手册，用章节标签声明「分几步走、每步产出什么、何时停下来问用户」。
Agent 按手册推进「故事 → 剧本 → 分镜 → 关键帧 → 视频 / 音频」全流程，
素材与节点直接落到外部画布 [infinite-canvas](https://github.com/basketikun/infinite-canvas) 上。

平台自身只管两件事：提供执行动作的工具集，守住不可逾越的安全边界。**流程归 Skill，边界归平台。**

## Skill 如何驱动流程

一套 Skill = `data/skills/<名称>/SKILL.md`，由三部分组成：

| 部分 | 内容 | 作用 |
|---|---|---|
| frontmatter 声明 | `name` / `description` | 注册与拒载依据：声明不合格的包不进 Skill 目录、不可加载 |
| `<planner>` 章节 | 阶段划分、里程碑、暂停点、阶段间依赖 | **流程的唯一事实源**，全文常驻主代理 |
| 其余章节 | 各专业阶段的产出规范（故事板设计、提示词写法、媒体生成、组装导出…） | 按阶段注入，不提前污染当前阶段 |

运行时的一条链：

1. **选中 Skill** —— 主代理只拿到流程段与章节目录，其余章节不进场。
2. **推进到某阶段** —— 主代理把该阶段整段委派出去，平台把对应章节全文注入子代理，
   并按阶段收紧它的工具面（`run_subagent(stage=…)`）。
3. **主代理是纯编排角色** —— 各专业阶段的写入工具对它结构性不可见，只能经委派触达；
   花钱的生成动作留在主线程，以便走确认闸。
4. **章节即依据** —— 未被注入或显式加载过的章节不构成依据，
   杜绝「分镜设计里混进提示词写法」这类跨阶段污染。

**边界不可被 Skill 削弱。** Skill 规定流程怎么走，但平台硬边界（生成确认、工具风险分级、
阶段硬拦停）由平台机械执行：执行模式档位下，即使 Skill 正文写着「直通」也照停——
**档位优先于 Skill 散文**。

Skill 是产品数据源而非代码：用户可在工作台直接编辑、保存带版本留痕，**改文档即改流程**。

## 外部画布（infinite-canvas）

画布是本项目**使用的外部项目**，代码不在本仓库内、独立迭代：
<https://github.com/basketikun/infinite-canvas>

它由四部分组成，本项目只用其中前两个公开面：

| 画布模块 | 是什么 | 本项目怎么用 |
|---|---|---|
| `web/` | 画布站点本体（React 19 + Vite 7，端口 **3000**） | iframe 嵌入，靠 hash 引导 `#agentUrl` / `#agentToken` 接入 |
| `canvas-agent/` | 本地 Agent 桥（npm 包，端口 **17371**） | **唯一集成通道**：`POST /api/tools` 调工具，`GET /health` `/config` 探活与版本 |
| `plugins/` | 节点插件 SDK + Codex app 插件 | 预留扩展点，当前未启用 |
| `docs/` | 文档站（Fumadocs） | 未使用 |

**集成铁律（宪法 Rule 7）**：任何时候禁止修改或 fork 画布的任何文件，只依赖上述公开面；
画布内生成的图存于其浏览器端，服务端无法回读原图。确需画布侧新能力时按需求对齐，不做单边侵入——
完整约束见 [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md)。

本项目侧全部画布代码收敛在 `src/video_agent/adapters/`：`infinite_canvas_backend.py`（实现）、
`canvas_adapter.py`（工厂）、`canvas_port.py`（端口）、`canvas_schema.py`（契约映射与工具白名单）。

## 快速开始

需要**两个服务**：画布（3000）+ 本项目（8080）；画布侧还需先起 canvas-agent（17371）。

Windows 一键启动（依次拉起三者并打开 <http://localhost:8080/>）：

```bat
启动服务.bat
```

手动启动：

```bash
npx -y @basketikun/canvas-agent@0.6.0   # 1. canvas-agent（先行，17371）
                                        # 2. 画布站点（3000）：在其 web/ 目录执行 npm run dev
pip install -r requirements.txt         # 3. 本项目
python -m src.video_agent.web           #    http://127.0.0.1:8080
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / Pydantic v2 / httpx / loguru |
| 前端 | SolidJS + TypeScript + Vite + 手写语义 CSS（`src/web/`） |
| Agent 核心 | Planner 唯一入口 + 多步工具循环（动作通道单轨 = function calling） |
| 测试 | pytest（unit / integration）/ vitest / Playwright |

## 开发与验收

常用命令与分层验证口径的唯一家 = [AGENTS.md](AGENTS.md) §二 / §三。日常与批末验收：

```bash
python scripts/acceptance.py --quick   # 快验：GATES + tsc
python scripts/acceptance.py           # 批末全量：GATES + SUITES + RATCHETS
```

前端：`npm run dev` / `build` / `check`（tsc + eslint）/ `test`。

## 文档索引

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE_RULES.md](ARCHITECTURE_RULES.md) | 架构宪法（AI 协作最高优先级约束）；§十一 为后端文件地图 |
| [AGENTS.md](AGENTS.md) | 改动前必读、分层验证 |
| [docs/GOVERNANCE.md](docs/GOVERNANCE.md) | 治理条款唯一家 |
| [docs/配置说明.md](docs/配置说明.md) | 各配置源的权威关系与加载优先级 |
| [docs/前端体验规范.md](docs/前端体验规范.md) | 品牌 / 视觉 / 交互强制规范 |
| [CHANGELOG.md](CHANGELOG.md) | 裁决 / 批次 / 事故历史留痕唯一家 |

## 环境与安全

- 复制 `.env.example` 为根目录 `.env` 配置运行参数（端口、画布地址、安全开关等），
  完整说明见 [docs/配置说明.md](docs/配置说明.md)。
- API Key 统一存放于 `API/.env`（已 gitignore，勿提交）。
- `ENVIRONMENT=production` 时所有 `/api/` 请求需携带 `X-API-Key` 头（未配置 key 则一律拒绝）。

## 反馈与联系

本项目仍在迭代中，**欢迎提意见、报问题、给建议**——使用中觉得别扭的地方、想要的能力、
发现的缺陷，都请直接联系我：

| 渠道 | 联系方式 |
|---|---|
| 微信 | `ljx-xzdz` |
| QQ | `787146842` |
| 邮箱 | `787146842@qq.com` |

也欢迎在 [GitHub Issues](https://github.com/l787146842-ux/Video-Agent-FT/issues) 留痕，便于问题跟踪与公开讨论。
