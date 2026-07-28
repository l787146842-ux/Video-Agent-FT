"""
集中路径常量 — 消除各模块重复计算 PROJECT_ROOT。

所有需要引用项目目录的模块统一从此处导入：
    from src.video_agent.utils.paths import PROJECT_ROOT, WORKSPACE_DIR, ASSETS_DIR, ...
"""
from pathlib import Path

# 项目根目录（src/video_agent/utils/paths.py → 上溯 4 级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 核心目录
STATIC_DIR = PROJECT_ROOT / "static"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
ASSETS_DIR = WORKSPACE_DIR / "assets"
DATA_DIR = PROJECT_ROOT / "data"
API_DIR = PROJECT_ROOT / "API"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SKILL_DOCS_DIR = DATA_DIR / "skills"
PROVIDERS_FILE = DATA_DIR / "api_providers.json"
ENV_FILE = API_DIR / ".env"
