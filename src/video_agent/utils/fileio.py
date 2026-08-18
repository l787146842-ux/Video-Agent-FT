"""
文件写入工具：原子写，避免进程中途崩溃留下损坏的 JSON。
"""
from loguru import logger
import os
import tempfile
import time
from pathlib import Path
from typing import Union

# Windows 实时杀软可能短暂锁住新建 tmp/目标文件（WinError 5），短退避重试
_REPLACE_RETRIES = 3
_REPLACE_BACKOFF_S = 0.05


def _replace_with_retry(tmp_path: str, path: Path) -> None:
    """os.replace 遇 PermissionError 短退避重试；仍败抛原异常。"""
    last: BaseException = PermissionError("replace not attempted")
    for i in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp_path, str(path))
            return
        except PermissionError as e:
            last = e
            time.sleep(_REPLACE_BACKOFF_S * (2 ** i))
    raise last


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    """
    先写临时文件再 os.replace 原子替换目标文件。
    目标目录不存在时自动创建。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError as _e:
            logger.debug("[fileio] 忽略异常: {}", _e)
        raise
