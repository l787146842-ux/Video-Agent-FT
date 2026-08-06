import time
import uuid


def gen_id(prefix: str, *, wide: bool = False) -> str:
    """生成唯一 ID。wide=True 时随机部分为 12 位（用于资产文件名）。

    随机部分使用 uuid4 切片：原实现 random.randint 同秒批量调用碰撞率高
    （3 位随机仅 900 种取值），uuid4 可将碰撞概率降至可忽略。
    格式保持 prefix-时间戳-随机，与存量 id 形态兼容。
    """
    r = uuid.uuid4().hex[:12] if wide else uuid.uuid4().hex[:8]
    return f"{prefix}-{int(time.time())}-{r}"
