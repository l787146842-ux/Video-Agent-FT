"""
统一异常层次 — 所有业务异常的基类与分类。

层次结构：
    VideoAgentError (基类，面向用户的 message)
    ├── AdapterError          — 供应商调用失败
    ├── GenerationError       — 生成管线失败
    └── StateError            — 状态操作失败
        └── StateConflictError — 版本闸拒绝写入（409 冲突）

路由层通过 @app.exception_handler(VideoAgentError) 统一处理。
每个异常携带 error_code 供前端国际化翻译用（消息本身保持中文）。
"""
from typing import Optional


class VideoAgentError(Exception):
    """业务异常基类 — message 面向用户（中文），error_code 供前端翻译用"""

    status_code: int = 500  # 默认 HTTP 状态码
    error_code: str = "INTERNAL_ERROR"  # 错误码（前端可根据此码做国际化翻译）

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        error_code: str = "",
        raw: str = "",
    ):
        super().__init__(message)
        if status_code:
            self.status_code = status_code
        if error_code:
            self.error_code = error_code
        # 未预期异常的技术细节（友好文案进 message，原始报文进 raw，
        # exception_handler 转译时随 ErrorPayload.raw 下发，前端折叠展示）
        self.raw = raw


class AdapterError(VideoAgentError):
    """Adapter 调用失败（LLM / 图片 / 视频供应商）

    结构化故障信息（替代脆弱的错误文案字符串匹配）：
    - retryable: 是否为瞬时故障（5xx / 429 / 超时 / 连接失败），可重试/切备用模型
    - http_status: 上游 HTTP 状态码（如有），供日志与监控分档
    - kind: 错误类别（upstream/auth/quota/param/refusal/timeout/network/unknown），
      字段口径与 ErrorPayload 对齐；取值见 adapters/errors.py 的 KIND_* 常量
    """
    status_code = 502
    error_code = "ADAPTER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        error_code: str = "",
        retryable: Optional[bool] = None,
        http_status: Optional[int] = None,
        kind: str = "",
    ):
        super().__init__(message, status_code=status_code, error_code=error_code)
        self.retryable = retryable
        self.http_status = http_status
        self.kind = kind


# 上下文窗口超长的 kind 取值（常量归 exceptions：core 侧会话层压缩的
# 溢出恢复判定依赖它，而分类动作发生在 adapters/errors.py，
# 依赖方向 adapters → core 不可反向）
KIND_CONTEXT_OVERFLOW = "context_overflow"


def is_context_overflow_error(exc: BaseException) -> bool:
    """异常是否为供应商确认的上下文超长（dsh CONTEXT_WINDOW_EXCEEDED 分类；
    会话层压缩溢出恢复（session_log.compact_pass force）的唯一触发判定）。"""
    return isinstance(exc, AdapterError) and exc.kind == KIND_CONTEXT_OVERFLOW


class GenerationError(VideoAgentError):
    """生成管线失败（配置缺失、供应商无返回等）"""
    status_code = 502
    error_code = "GENERATION_ERROR"


class StateError(VideoAgentError):
    """状态操作失败（项目不存在、路径无效等）"""
    status_code = 400
    error_code = "STATE_ERROR"


class StateConflictError(StateError):
    """状态写入被版本闸拒绝：磁盘账本新于本实例已知号（别的实例写过更新数据），
    本次破坏性写入（如截断）放弃落盘，调用方应以 409 冲突告知客户端重试。"""
    status_code = 409
    error_code = "STATE_CONFLICT"
