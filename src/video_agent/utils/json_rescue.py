"""工具参数 JSON 抢救与真实拒因（8888 事故批，对齐 dsh「数据不丢、错误可见」）。

背景（8888 项目实证）：模型生成的 tool_call arguments 因中继截断/引号失衡
解析失败时，原实现两处（adapter 流式累积 / fc_tool_runner 非流式）都把原始
参数静默丢弃、伪造空参数 {} 继续调用——工具报「未携带非空 title」假拒因，
模型原样重发 15 轮无法自救。

铁律（strip-gate 事故同源）：prompt 数据绝不能被静默丢弃。处置顺序：
1. 本地抢救（确定性修复，不伪造数据）：字符串值内的裸控制字符转义
   （模型在字符串里吐真实换行/制表是最常见病；字符串**外**的换行属
   JSON 合法空白，不得转义——按「是否在字符串内」最小扫描区分）；
2. 抢救失败 → 返回 None + 带出错位置与原文片段的结构化拒因，
   由调用方拒收并把真实原因回喂模型（模型可增量修复，不整批重写）。

dsh 对照（tool-calls.ts:104-111）：非法 JSON 原样作为字符串传给工具层，
由工具层 schema 校验后返回 isError 结果。本项目工具层为强类型 dict，
故在解析层拦下并给结构化拒因——模型可见的错误语义与 dsh 一致。
"""
import json
from typing import Optional, Tuple


def _escape_controls_in_strings(raw: str) -> str:
    r"""只转义**字符串值内**的裸控制字符（\x00-\x1f）；字符串外不动。

    JSON 字符串值内裸控制字符非法（须 \uXXXX 转义），但 token 之间的
    换行/制表是合法空白——盲目全局转义会把合法 JSON 改坏。本扫描器
    以最小状态机区分两种位置（只认引号与反斜杠，无他依赖）。"""
    out: list = []
    in_str = False
    esc = False
    for ch in raw:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                continue
            if ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
                continue
            out.append(ch)
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def rescue_tool_arguments(raw: str) -> Tuple[Optional[dict], str]:
    """尝试解析工具参数 JSON；失败先本地抢救，仍失败返回 (None, 拒因)。

    返回 (args, error)：
    - 解析（或抢救后）成功 → (dict, "")；
    - 失败 → (None, 拒因文本)：携带 JSON 解析器报错位置与原文前 200 字符，
      供调用方直接作为工具拒收反馈（模型可见、可据此修复）。
    """
    raw = str(raw or "")
    try:
        args = json.loads(raw) if raw.strip() else {}
        if isinstance(args, dict):
            return args, ""
        # 合法 JSON 但非对象（数组/标量）：按拒收处理，不伪造 {}
        return None, f"工具参数必须是 JSON 对象，实际为 {type(args).__name__}"
    except (json.JSONDecodeError, ValueError) as e:
        # 抢救：字符串值内的裸控制字符转义（不改变任何业务数据）
        try:
            args = json.loads(_escape_controls_in_strings(raw))
            if isinstance(args, dict):
                return args, ""
        except (json.JSONDecodeError, ValueError):
            pass
        pos = getattr(e, "pos", 0) or 0
        snippet = raw[:200]
        return None, (
            f"参数 JSON 解析失败（第 {pos} 字符附近：{e.msg}），"
            f"本次调用未执行、未写入任何字段。原始参数（截前 200 字符）：{snippet}。"
            "请修正 JSON 语法后重新调用（保留原有全部字段内容）。"
        )


__all__ = ["rescue_tool_arguments"]
