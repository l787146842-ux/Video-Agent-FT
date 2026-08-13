"""
DEPRECATED：多步循环实现已下沉至 core/agent_loop.py（P1-1 层级理顺）。

本文件仅保留向后兼容的 re-export 别名（遵循项目惯例：DEPRECATED 模块
保留别名导入，不立即删除），新代码一律从 core.agent_loop 导入。
移除节点见 docs/兼容层移除计划.md。
"""
from src.video_agent.core.agent_loop import (  # noqa: F401
    MAX_STEPS,
    AgentLoopResult,
    LlmCall,
    ContextBuilder,
    split_actions,
    _split_actions,
    run_agent_loop,
)
