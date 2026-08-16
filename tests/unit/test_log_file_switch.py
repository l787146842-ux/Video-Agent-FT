"""日志文件开关回归（六轮 S4/N2）。

钉死：测试进程（conftest 注入 LOG_FILE_ENABLED=false）不落生产日志文件——
app 模块加载后 loguru 不存在指向 logs/ 的文件 sink，多进程争用
（loguru rotation rename WinError 32）从源头消失。
"""
from loguru import logger


def test_settings_respect_log_file_switch():
    from src.video_agent.config import settings

    # conftest 顶层 setdefault false → settings 读环境变量为 False
    assert settings.log_file_enabled is False


def test_no_file_sink_in_test_process():
    # 触发 app 模块加载（幂等；日志 sink 在 import 期装配）
    import src.video_agent.web.app  # noqa: F401
    from loguru._file_sink import FileSink

    from src.video_agent.utils.paths import LOGS_DIR

    for handler in logger._core.handlers.values():
        sink = getattr(handler, "_sink", None)
        if isinstance(sink, FileSink):
            path = str(getattr(sink, "_path", ""))
            assert not path.startswith(str(LOGS_DIR)), (
                f"测试进程不应持有生产日志文件 sink: {path}"
            )
