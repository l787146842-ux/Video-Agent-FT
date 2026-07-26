"""
Video Agent Web Application
FastAPI 主应用 — 挂载 Flova Studio 前端静态服务 + API 网关
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

# 项目根目录 (src/video_agent/web/app.py -> 上溯 3 级)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

# 日志配置
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO",
)

# ---------- 生命周期：注册适配器 + Skills + 初始化状态 ----------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    from src.video_agent.web.providers import register_adapters
    from src.video_agent.web.state_service import StudioStateService
    from src.video_agent.skills import register_default_skills
    register_adapters()
    register_default_skills()
    StudioStateService.get_instance()  # 触发加载/初始化
    logger.info("[Startup] Adapters + Skills registered, state service ready")
    yield


app = FastAPI(title="Video Agent Studio", version="1.0.0", lifespan=lifespan)

# ---------- 静态文件服务 ----------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 上传素材的静态访问（workspace/assets/）
ASSETS_DIR = WORKSPACE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/workspace/assets", StaticFiles(directory=str(ASSETS_DIR)), name="uploaded-assets")


@app.get("/", include_in_schema=False)
async def index():
    """根路径返回 Studio 前端页面"""
    return FileResponse(str(STATIC_DIR / "studio.html"))


# ---------- 注册 API 路由 ----------
from src.video_agent.web.routes.config import router as config_router
from src.video_agent.web.routes.providers import router as providers_router
from src.video_agent.web.routes.project import router as project_router
from src.video_agent.web.routes.storyboard import router as storyboard_router
from src.video_agent.web.routes.agent import router as agent_router
from src.video_agent.web.routes.generate import router as generate_router
from src.video_agent.web.routes.workflow import router as workflow_router
from src.video_agent.web.routes.plugins import router as plugins_router
from src.video_agent.web.routes.upload import router as upload_router
from src.video_agent.web.routes.cli_status import router as cli_status_router

app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(providers_router, prefix="/api", tags=["providers"])
app.include_router(project_router, prefix="/api", tags=["project"])
app.include_router(storyboard_router, prefix="/api", tags=["storyboard"])
app.include_router(agent_router, prefix="/api", tags=["agent"])
app.include_router(generate_router, prefix="/api", tags=["generate"])
app.include_router(workflow_router, prefix="/api", tags=["workflow"])
app.include_router(plugins_router, prefix="/api", tags=["plugins"])
app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(cli_status_router, prefix="/api", tags=["cli-status"])


# ---------- 启动入口 ----------
def main():
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Static dir:   {STATIC_DIR}")
    logger.info(f"Workspace:    {WORKSPACE_DIR}")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
