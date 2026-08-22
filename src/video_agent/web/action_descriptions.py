"""Studio 操作中文描述表 re-export 壳（D-01 清偿，2026-08-22）。

定义源已下沉至 `src/video_agent/core/action_descriptions.py`（纯展示文案，
无 web 依赖，随执行器归位 core）；本壳保留既有导入路径。
"""
from src.video_agent.core.action_descriptions import (  # noqa: F401
    aggregate_action_log,
    describe_action,
)
