"""动作执行器 re-export 壳（D-01 清偿，2026-08-22）。

定义源已下沉至 `src/video_agent/core/action_executor.py`（层级例外清偿；
web 依赖经 core/ports.py 端口倒置，装配点注入）。本壳仅为存量消费方
（测试夹具 / eval 管线 / web 层调用方）保留既有导入路径；
壳删除路线见 docs/action_executor下沉计划.md 阶段二。
"""
from src.video_agent.core.action_executor import StateOperationExecutor  # noqa: F401
