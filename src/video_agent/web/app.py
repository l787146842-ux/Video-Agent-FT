"""
Video Agent Web Application
FastAPI 主应用 — 挂载 FTDYB 前端静态服务 + API 网关
"""
import asyncio
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.video_agent.utils.paths import PROJECT_ROOT, STATIC_DIR, WORKSPACE_DIR, ASSETS_DIR, LOGS_DIR
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.config import settings
from src.video_agent.web.routes.config import router as config_router
from src.video_agent.web.routes.providers import router as providers_router
from src.video_agent.web.routes.project import router as project_router
from src.video_agent.web.routes.storyboard import router as storyboard_router
from src.video_agent.web.routes.agent import router as agent_router
from src.video_agent.web.routes.conversations import router as conversations_router
from src.video_agent.web.routes.generate import router as generate_router
from src.video_agent.web.routes.workflow import router as workflow_router
from src.video_agent.web.routes.plugins import router as plugins_router
from src.video_agent.web.routes.upload import router as upload_router
from src.video_agent.web.routes.canvas import router as canvas_router
from src.video_agent.web.routes.cli_status import router as cli_status_router

# 日志配置
logger.remove()
if settings.environment == "production":
    # 生产环境：JSON 结构化日志（便于 ELK / Loki 采集）
    logger.add(sys.stdout, serialize=True, level="INFO")
else:
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
    )
# 日志落盘（排障用）：滚动 10MB × 保留 5 份；enqueue 避免阻塞事件循环
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    LOGS_DIR / "agent-{time:YYYYMMDD}.log",
    rotation="10 MB",
    retention=5,
    encoding="utf-8",
    enqueue=True,
    level="INFO",
)

# ---------- 生命周期：注册适配器 + Skills + 初始化状态 ----------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    from src.video_agent.web.providers import register_adapters
    from src.video_agent.web.skill_docs import ensure_default_skill_docs
    from src.video_agent.state.manager import StateManager
    from src.video_agent.config import settings
    register_adapters()
    # 代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，不再注册；
    # 下拉框与 Skill 目录只保留 data/skills/*.md 文档 Skill。
    ensure_default_skill_docs()
    StateManager.get_instance()  # 触发加载/初始化
    # 画布 Tool 注册（可通过 CANVAS_ENABLED=false 关闭）
    if settings.canvas_enabled:
        from src.video_agent.tools.canvas_tools import register_canvas_tools
        register_canvas_tools()
        # 画布版本漂移探测（P1-5）：fire-and-forget，失败/离线不阻塞启动

        async def _check_canvas_version():
            from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
            await get_canvas_adapter().check_version_drift()

        asyncio.create_task(_check_canvas_version())
    logger.info("[Startup] Adapters + Skills + Skill docs ready, state service loaded")
    # 安全提醒：生产环境未配置 API_KEY 时所有 /api/ 请求将被拒绝
    if settings.environment != "development" and not settings.api_key:
        logger.warning(
            "[Security] 生产环境未设置 API_KEY 环境变量，所有 /api/ 请求将返回 401。"
            "请设置 API_KEY 或切换为 development 模式。"
        )
    yield
    # ---------- 关闭清理：冲刷防抖落盘 + 释放 Adapter HTTP 连接池 ----------
    # 防抖落盘可能有挂起变更，关闭前必须冲刷，避免丢失最后一轮写入
    StateManager.get_instance().flush_save()
    from src.video_agent.adapters.factory import AdapterFactory
    for adapter_type in ("chat", "image_generation", "video_generation"):
        for provider, adapter in AdapterFactory._adapters.get(adapter_type, {}).items():
            if hasattr(adapter, "close"):
                try:
                    await adapter.close()
                except Exception:
                    pass
    AdapterFactory._adapters.clear()
    logger.info("[Shutdown] Adapter 连接池已释放")


app = FastAPI(title="Video Agent Studio", version="1.0.0", lifespan=lifespan)

# ---------- CORS 中间件 ----------
# 开发环境默认允许所有源（方便本地调试）；
# 生产环境必须通过 CORS_ORIGINS 环境变量显式配置允许源，否则仅允许本机访问。
_DEFAULT_CORS = "*" if settings.environment == "development" else "http://127.0.0.1:8080,http://localhost:8080"
_cors_origins = os.getenv("CORS_ORIGINS", _DEFAULT_CORS).split(",")
if "*" in _cors_origins and settings.environment != "development":
    logger.warning("[Security] 生产环境 CORS 配置为 *，建议通过 CORS_ORIGINS 环境变量限制允许源")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,  # 本项目用 API Key 头认证，无 cookie 认证需求
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 请求限流中间件 ----------
if settings.rate_limit_per_minute > 0:
    from src.video_agent.web.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(
        RateLimitMiddleware,
        rate=settings.rate_limit_per_minute,
        generate_rate=settings.rate_limit_generate_per_minute,
    )
    logger.info(
        f"[Startup] 限流已启用: 聊天 {settings.rate_limit_per_minute} req/min/IP，"
        f"生成 {settings.rate_limit_generate_per_minute} req/min/IP"
    )


# ---------- development 模式本机写保护 ----------
# development 下无 API Key 认证且 CORS 为 *，恶意网页可驱动本地服务（烧 LLM 额度/删项目）。
# 对 /api/ 写请求校验 Origin/Referer 为本机或缺失（兼容 curl 与 Vite 代理），否则 403。
_LOCAL_ORIGIN_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")


@app.middleware("http")
async def dev_origin_guard(request: Request, call_next):
    if settings.environment == "development" \
            and request.method in ("POST", "PUT", "DELETE") \
            and request.url.path.startswith("/api/"):
        source = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if source:
            # Referer 带路径，截取 origin 部分再校验
            parsed = urlparse(source)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if not _LOCAL_ORIGIN_RE.match(origin):
                logger.warning(f"[Security] 拒绝外站来源的写请求: {source} {request.method} {request.url.path}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "拒绝非本机来源的写请求", "error_code": "FORBIDDEN_ORIGIN"},
                )
    return await call_next(request)


# ---------- API Key 认证中间件 ----------
@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    # 开发模式跳过认证
    if settings.environment == "development":
        return await call_next(request)
    # CORS 预检请求不携带 X-API-Key，必须放行（否则浏览器跨域请求全部 401）
    if request.method == "OPTIONS":
        return await call_next(request)
    # 非 /api/ 路径跳过（静态文件、页面）
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    # 校验 X-API-Key 头（未配置 api_key 时拒绝所有请求，安全默认）
    key = request.headers.get("X-API-Key", "")
    if not settings.api_key or key != settings.api_key:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# ---------- 统一异常处理 ----------
@app.exception_handler(VideoAgentError)
async def video_agent_error_handler(request: Request, exc: VideoAgentError):
    """业务异常统一转译为 JSON 响应（包含 error_code 供前端国际化）"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "error_code": exc.error_code},
    )

# ---------- 静态资源缓存策略 ----------
# 生产环境：vendor/ 第三方库 7 天；dist/ 构建产物 1 天；其他静态 1 小时
# 开发环境：dist/ 构建产物不缓存（文件名固定，避免改前端后 Ctrl+F5 仍命中旧缓存）
@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if settings.environment == "development" and path.startswith("/static/dist/"):
        # 开发环境 dist 不缓存，确保每次刷新都拿到最新构建产物
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif path.startswith("/static/vendor/"):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif path.startswith("/static/dist/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# ---------- 静态文件服务 ----------
# 单一 mount 即可服务 static/ 下所有子目录（含 dist/），无需重复挂载
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 上传素材的静态访问（workspace/assets/）
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/workspace/assets", StaticFiles(directory=str(ASSETS_DIR)), name="uploaded-assets")


def _studio_page() -> FileResponse:
    """新前端页面（唯一前端，SolidJS SPA）；dist 未构建时明确报错（启动脚本会自动补构建）。

    Cache-Control: no-cache —— index.html 是带 hash 资源引用的入口，
    每次加载都向服务器重新校验（未变则 304，开销极小），
    避免浏览器启发式缓存把旧入口（引用旧 hash JS）留在用户标签页里。
    """
    dist_index = STATIC_DIR / "dist" / "index.html"
    if not dist_index.exists():
        raise HTTPException(status_code=503, detail="前端产物缺失，请执行 npm run build 后重启服务")
    return FileResponse(str(dist_index), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
async def index():
    """根路径返回新前端页面"""
    return _studio_page()


@app.get("/canvas", include_in_schema=False)
@app.get("/settings", include_in_schema=False)
async def spa_fallback():
    """SPA 客户端路由回退：画布 / API 配置刷新或直接访问时返回新前端页面（A-5）"""
    return _studio_page()


@app.get("/launcher", include_in_schema=False)
async def launcher():
    """已废弃：重定向到 Studio 主页（画布模式已内置）"""
    return RedirectResponse("/")


@app.get("/launcher.html", include_in_schema=False)
async def launcher_html():
    """已废弃：重定向到 Studio 主页"""
    return RedirectResponse("/")


# ---------- 注册 API 路由 ----------
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(providers_router, prefix="/api", tags=["providers"])
app.include_router(project_router, prefix="/api", tags=["project"])
app.include_router(storyboard_router, prefix="/api", tags=["storyboard"])
app.include_router(agent_router, prefix="/api", tags=["agent"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(generate_router, prefix="/api", tags=["generate"])
app.include_router(workflow_router, prefix="/api", tags=["workflow"])
app.include_router(plugins_router, prefix="/api", tags=["plugins"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(canvas_router, prefix="/api", tags=["canvas"])
app.include_router(cli_status_router, prefix="/api", tags=["cli-status"])


# ---------- 启动入口 ----------
def main():
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Static dir:   {STATIC_DIR}")
    logger.info(f"Workspace:    {WORKSPACE_DIR}")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
