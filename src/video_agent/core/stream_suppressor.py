"""流式增量过滤器（P2-1）：从 planner.py 拆出（批次3 文件瘦身）。

抑制两种流程信号围栏：
- ```studio-actions 整块抑制；
- ```json 围栏内含确认信号（request_confirmation / "tool": "confirm"）时整块抑制，
  普通 json 代码块照常放行。
planner.py 对本类做 re-export，既有导入路径不变。
"""
from typing import List


class StreamActionSuppressor:
    """流式增量过滤器（P2-1）：只抑制流程信号围栏，
    普通文本与普通 markdown 代码块照常推送。

    围栏可能跨 chunk 截断（如先收到 `` 再收到 `studio-actions），
    通过保留尾部 2 字符与等待信息行换行来解决。
    """

    FENCE = "```"
    SUPPRESS_LANG = "studio-actions"
    JSON_LANG = "json"
    _JSON_SIGNAL_MARKERS = (
        "request_confirmation",
        '"tool": "confirm"',
        '"tool":"confirm"',
        '"tool": "pause"',
        '"action": "confirm"',
    )

    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0        # 围栏状态已解析到的位置
        self.emit_upto = 0  # 已推送（或已整块跳过）的位置
        self.in_actions = False
        self._pending_json = False
        self._json_captured = ""
        self._post_fence = False  # 闭合围栏恰在缓冲末尾，待确认下一个字符是否为换行
        # 边写边填：捕获被抑制的 studio-actions 块内容（不含围栏），
        # 供 StreamingActionExtractor 增量提取；消费方读取后自行置空
        self.suppressed = ""
        self._supp_upto = 0  # 已捕获到的缓冲位置

    @staticmethod
    def _has_signal(text: str) -> bool:
        return any(mk in text for mk in StreamActionSuppressor._JSON_SIGNAL_MARKERS)

    def feed(self, delta: str) -> str:
        """追加增量文本，返回本次可推送的部分（可能为空串）。"""
        self.buf += delta
        if self._post_fence:
            # 上一轮闭合围栏停在缓冲末尾：吞掉属于围栏行的尾随换行
            self._post_fence = False
            if self.pos < len(self.buf) and self.buf[self.pos] == "\n":
                self.pos += 1
                self.emit_upto = self.pos
        out_parts: List[str] = []
        while True:
            if not self.in_actions and not self._pending_json:
                i = self.buf.find(self.FENCE, self.pos)
                if i == -1:
                    # 未见完整围栏：尾部保留 2 字符（可能是截断的 `` / ```）
                    safe = max(self.pos, len(self.buf) - (len(self.FENCE) - 1))
                    self.pos = safe
                    break
                # 围栏前的待推文本先冲出去
                if i > self.emit_upto:
                    out_parts.append(self.buf[self.emit_upto:i])
                    self.emit_upto = i
                # 围栏起始已确定；信息行未收完则暂等
                nl = self.buf.find("\n", i + len(self.FENCE))
                if nl == -1:
                    self.pos = i
                    break
                info = self.buf[i + len(self.FENCE):nl].strip()
                if info.startswith(self.SUPPRESS_LANG):
                    self.in_actions = True
                    self.pos = nl + 1
                    self.emit_upto = nl + 1  # 开标行进入抑制区，不推送
                    self._supp_upto = nl + 1  # 块内容捕获起点
                elif info.startswith(self.JSON_LANG):
                    # json 围栏先挂起：闭合后按内容决定抑制还是放行
                    self._pending_json = True
                    self._json_captured = ""
                    self._supp_upto = nl + 1
                    self.pos = nl + 1
                    self.emit_upto = i  # 整块暂不发射
                else:
                    self.pos = nl + 1  # 普通代码块，围栏行照常放行
            elif self.in_actions:
                j = self.buf.find(self.FENCE, self.pos)
                if j == -1:
                    # 闭合围栏未到：增量捕获块内容（尾部保留 2 字符防截断围栏混入）
                    safe = max(self._supp_upto, len(self.buf) - (len(self.FENCE) - 1))
                    if safe > self._supp_upto:
                        self.suppressed += self.buf[self._supp_upto:safe]
                        self._supp_upto = safe
                    break
                # 闭合围栏已确定：捕获剩余块内容（不含围栏本身）
                if j > self._supp_upto:
                    self.suppressed += self.buf[self._supp_upto:j]
                self._supp_upto = j
                end = j + len(self.FENCE)
                if end < len(self.buf):
                    if self.buf[end] == "\n":
                        end += 1
                else:
                    # 闭合围栏恰在缓冲末尾：换行归属待下一个 chunk 确认
                    self._post_fence = True
                self.pos = end
                self.emit_upto = end  # 整块（含闭合围栏）跳过
                self.in_actions = False
            else:  # _pending_json
                j = self.buf.find(self.FENCE, self.pos)
                if j == -1:
                    # 闭合围栏未到：增量暂存块内容
                    safe = max(self._supp_upto, len(self.buf) - (len(self.FENCE) - 1))
                    if safe > self._supp_upto:
                        self._json_captured += self.buf[self._supp_upto:safe]
                        self._supp_upto = safe
                    break
                if j > self._supp_upto:
                    self._json_captured += self.buf[self._supp_upto:j]
                self._supp_upto = j
                end = j + len(self.FENCE)
                if end < len(self.buf):
                    if self.buf[end] == "\n":
                        end += 1
                else:
                    self._post_fence = True
                if self._has_signal(self._json_captured):
                    # 含确认信号：整块抑制，内容进入 suppressed 供提取
                    self.suppressed += self._json_captured
                    self.emit_upto = end
                else:
                    # 普通 json：整块放行（emit_upto 停在开标行起点，底部整段发射）
                    pass
                self.pos = end
                self._pending_json = False
                self._json_captured = ""
        if self.pos > self.emit_upto:
            out_parts.append(self.buf[self.emit_upto:self.pos])
            self.emit_upto = self.pos
        return "".join(out_parts)

    def flush(self) -> str:
        """流结束时冲刷剩余缓冲：未闭合的 studio-actions 块保持抑制；
        未闭合 json 块按是否含确认信号决定放行或抑制。"""
        if self.in_actions:
            return ""
        if self._pending_json:
            if self._has_signal(self._json_captured):
                self.suppressed += self._json_captured
                out = ""
            else:
                out = self.buf[self.emit_upto:]
            self._pending_json = False
            self._json_captured = ""
            self.emit_upto = self.pos = len(self.buf)
            return out
        out = self.buf[self.emit_upto:]
        self.emit_upto = self.pos = len(self.buf)
        return out
