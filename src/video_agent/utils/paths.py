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
LOGS_DIR = PROJECT_ROOT / "logs"
SKILL_DOCS_DIR = DATA_DIR / "skills"
PROVIDERS_FILE = DATA_DIR / "api_providers.json"
ENV_FILE = API_DIR / ".env"

# 素材库元数据（本地化）
# 分类/标签/展示名元数据；扫描事实源仍是 ASSETS_DIR 目录本身
ASSET_LIBRARY_FILE = DATA_DIR / "asset_library.json"
# 缩略图懒生成缓存目录（下划线前缀：素材扫描与列表接口一律跳过）
ASSET_THUMBS_DIR = ASSETS_DIR / "_thumbs"

# 缓存命中遥测落盘（utils/live_metrics.record_cache_usage 追加写；JSONL，
# 供离线分析前缀缓存命中率）
CACHE_METRICS_FILE = DATA_DIR / "cache_metrics.jsonl"
