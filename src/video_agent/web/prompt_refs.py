"""提示词 @引用解析 re-export 壳（D-01 清偿，2026-08-22）。

定义源已下沉至 `src/video_agent/core/prompt_refs.py`（纯状态域逻辑，
无 web 依赖，随执行器归位 core）；本壳保留既有导入路径
（web/generation.py、tools/storyboard_tools.py 等存量消费方）。
"""
from src.video_agent.core.prompt_refs import (  # noqa: F401
    build_storyboard_media_map,
    media_of_draft,
    resolve_prompt_mentions,
)
