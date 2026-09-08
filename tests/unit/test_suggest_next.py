# -*- coding: utf-8 -*-
"""批 3 · B4 拆伪按钮（V3-1）退役回归：平台不再计算"下一步"。

原文件钉死状态驱动建议（suggest 系）的行为；该函数族已随 B4 整体退役
（平台统一 8 节点图量异构 skill 必失真——商品宣传无分析步、宣言式 13 步
恒显"剧本分析"，3333 同款误导）。现口径：

- 平台不再发 kind="next" 建议；建议动作只剩失败重试（retry）与
  假停兜底继续（continue，label 固定「继续」不取节点标题）；
- "下一步"由模型聊天自述（外部标杆转录原样）；
- 防复活在 scripts/check_legacy_orchestration.py FORBIDDEN 机械承接
  （退役符号字面不落本文件，测试内运行时拼接断言）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 运行时拼接退役符号（防复活门禁扫描 *.py 字面，测试断言合法含这些词）
_FN = "suggest_" + "next_actions"
_TITLE = "current_" + "node_title"


def test_retired_symbols_absent_from_src():
    """退役符号全链退场（round_end_policies / agent_loop / workflow_runtime 零引用）。"""
    rep_src = (ROOT / "src/video_agent/core/round_end_policies.py").read_text(encoding="utf-8")
    assert _FN not in rep_src
    assert _TITLE not in rep_src
    loop_src = (ROOT / "src/video_agent/core/agent_loop.py").read_text(encoding="utf-8")
    assert _FN not in loop_src
    wr_src = (ROOT / "src/video_agent/core/workflow_runtime.py").read_text(encoding="utf-8")
    assert _TITLE not in wr_src


def test_fakestop_continue_label_is_generic():
    """假停兜底继续按钮 label 固定「继续」：不再取节点标题（异构 skill 失真源）。"""
    src = (ROOT / "src/video_agent/core/round_end_policies.py").read_text(encoding="utf-8")
    assert '{"kind": "continue", "label": "继续", "value": "继续"}' in src
    assert '"kind": "next"' not in src, "平台不再计算 kind=next 建议"
