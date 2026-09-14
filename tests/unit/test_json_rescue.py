"""工具参数 JSON 抢救器单测（8888 事故批）。

钉死 rescue_tool_arguments 的四个契约面：
① 合法 JSON 对象 → 原样解析；
② 字符串值内裸控制字符 → 本地抢救成功（不伪造、不改业务数据）；
③ 截断/引号失衡 → (None, 拒因)：拒因携带出错位置与原文片段（真实拒因
   可回喂模型自救），绝不返回空参数伪造调用；
④ 非 JSON 对象（数组/标量/空串）→ 按各自契约处理。

背景：8888 项目实证，子代理 31 次 / 主循环 9 次 create_group 参数因中继
截断解析失败，原实现两处静默伪造 {} → 工具按「未携带非空 title」假拒收
→ 模型原样重发 15 轮。抢救器 = 数据不丢 + 真实拒因（对齐 dsh 错误可见）。
"""
import pytest

from src.video_agent.utils.json_rescue import rescue_tool_arguments


def test_valid_json_object_passes_through():
    args, err = rescue_tool_arguments('{"title": "S02·曹彬来电", "count": 3}')
    assert err == ""
    assert args == {"title": "S02·曹彬来电", "count": 3}


def test_bare_control_chars_rescued():
    """字符串值内的真实换行（模型高频病）→ 转义抢救成功，业务数据不变"""
    raw = '{"title": "S01", "desc": "第一行\n第二行\t缩进"}'
    args, err = rescue_tool_arguments(raw)
    assert err == ""
    assert args == {"title": "S01", "desc": "第一行\n第二行\t缩进"}


def test_truncated_json_rejected_with_real_reason():
    """8888 实证形态：参数被截断（引号失衡）→ 拒收 + 拒因含位置与原文片段"""
    raw = '{"title": "S02·曹彬来电", "desc": "【空间锚'
    args, err = rescue_tool_arguments(raw)
    assert args is None
    assert "参数 JSON 解析失败" in err
    assert "第 " in err and "字符" in err          # 出错位置可读
    assert "S02·曹彬来电" in err                    # 原文片段保留（数据不丢）
    assert "未执行、未写入任何字段" in err           # 明确无副作用


def test_unbalanced_quotes_rejected():
    """奇数引号（8888 案例实测形态）→ 不伪造，拒因可回喂"""
    raw = '{"title": "S03, "desc": "ok"}'
    args, err = rescue_tool_arguments(raw)
    assert args is None
    assert "参数 JSON 解析失败" in err


def test_non_object_json_rejected():
    """合法 JSON 但非对象（数组）→ 按拒收处理，不伪造 {}"""
    args, err = rescue_tool_arguments('["a", "b"]')
    assert args is None
    assert "JSON 对象" in err


def test_empty_string_yields_empty_args():
    """空参数串 → 空 dict（无参工具合法形态）"""
    args, err = rescue_tool_arguments("")
    assert err == ""
    assert args == {}


def test_reject_reason_is_parser_truth_not_field_lie():
    """拒因是解析器真话，不是字段级假话（8888 假拒因「未携带非空 title」禁绝）：
    title 明明在原始参数里，拒因必须指向 JSON 语法而非缺字段。"""
    raw = '{"title": "真实存在的标题", "desc": "截断'
    _, err = rescue_tool_arguments(raw)
    assert "未携带" not in err
    assert "参数 JSON 解析失败" in err
    assert "真实存在的标题" in err      # 模型的数据原样可见，可据此修复
