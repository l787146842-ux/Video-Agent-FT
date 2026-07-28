"""
统一异常层次 — 所有业务异常的基类与分类。

层次结构：
    VideoAgentError (基类，面向用户的 message)
    ├── AdapterError      — 供应商调用失败
    ├── GenerationError   — 生成管线失败
    └── StateError        — 状态操作失败

路由层通过 @app.exception_handler(VideoAgentError) 统一处理。
"""


class VideoAgentError(Exception):
    """业务异常基类 — message 面向用户，可直接展示"""

    status_code: int = 500  # 默认 HTTP 状态码

    def __init__(self, message: str, *, status_code: int = 0):
        super().__init__(message)
        if status_code:
            self.status_code = status_code


class AdapterError(VideoAgentError):
    """Adapter 调用失败（LLM / 图片 / 视频供应商）"""
    status_code = 502


class GenerationError(VideoAgentError):
    """生成管线失败（配置缺失、供应商无返回等）"""
    status_code = 502


class StateError(VideoAgentError):
    """状态操作失败（项目不存在、路径无效等）"""
    status_code = 400
