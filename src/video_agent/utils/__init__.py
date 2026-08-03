import random
import time


def gen_id(prefix: str, *, wide: bool = False) -> str:
    """生成唯一 ID。wide=True 时随机部分为 4 位（用于资产文件名）"""
    r = random.randint(1000, 9999) if wide else random.randint(100, 999)
    return f"{prefix}-{int(time.time())}-{r}"