"""流式增量过滤器（P2-1）：从 planner.py 拆出（批次3 文件瘦身）。

只抑制 ```studio-actions 围栏整块（防模型违规输出的动作块泄漏进用户流式气泡，
audit-0819 取证：FC 模型也会把围栏写进正文，抑制器在 FC 单轨下仍承重）。

4-4 双轨退役（ADR-0001）：```json 确认信号围栏抑制分支与 suppressed 内容捕获
（边写边填增量提取的喂料口）已删除——它们是文本轨基础设施。
planner.py 对本类做 re-export，既有导入路径不变。
"""
from typing import List


class StreamActionSuppressor:
    """流式增量过滤器（P2-1）：只抑制 studio-actions 围栏，
    普通文本与普通 markdown 代码块照常推送。

    围栏可能跨 chunk 截断（如先收到 `` 再收到 `studio-actions），
    通过保留尾部 2 字符与等待信息行换行来解决。
    """

    FENCE = "```"
    SUPPRESS_LANG = "studio-actions"

    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0        # 围栏状态已解析到的位置
        self.emit_upto = 0  # 已推送（或已整块跳过）的位置
        self.in_actions = False
        self._post_fence = False  # 闭合围栏恰在缓冲末尾，待确认下一个字符是否为换行

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
            if not self.in_actions:
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
                else:
                    self.pos = nl + 1  # 普通代码块，围栏行照常放行
            else:
                j = self.buf.find(self.FENCE, self.pos)
                if j == -1:
                    break  # 闭合围栏未到，块内内容保持抑制
                # 闭合围栏已确定：整块（含闭合围栏）跳过
                end = j + len(self.FENCE)
                if end < len(self.buf):
                    if self.buf[end] == "\n":
                        end += 1
                else:
                    # 闭合围栏恰在缓冲末尾：换行归属待下一个 chunk 确认
                    self._post_fence = True
                self.pos = end
                self.emit_upto = end
                self.in_actions = False
        if self.pos > self.emit_upto:
            out_parts.append(self.buf[self.emit_upto:self.pos])
            self.emit_upto = self.pos
        return "".join(out_parts)

    def flush(self) -> str:
        """流结束时冲刷剩余缓冲：未闭合的 studio-actions 块保持抑制。"""
        if self.in_actions:
            return ""
        out = self.buf[self.emit_upto:]
        self.emit_upto = self.pos = len(self.buf)
        return out
