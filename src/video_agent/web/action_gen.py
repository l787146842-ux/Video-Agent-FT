"""生成动作域 re-export 壳（D-01 清偿，2026-08-22）。

定义源已下沉至 `src/video_agent/core/action_gen.py`；本壳保留既有导入路径。
"""
from src.video_agent.core.action_gen import (  # noqa: F401
    apply_generate_image,
    apply_generate_video,
)
