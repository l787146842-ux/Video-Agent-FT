"""audit-0819f 钉死回归（批 12 迁移）：闸预检只认用户原话。

1111 事故根治：附件预览里的剧本对白问号不得参与意图判定
（闸预检认 raw_user_text）。

2026-11-12 宽权限批：闸预检（`planner._run_gate_precheck` /
`stage_probes.gate_precheck`）已整体退役——规格/原料前置闸属业务判断，
交模型按 Skill 散文执行。原「预检取 raw_user_text」的文本搜索式钉死
随之失效：被测入口已不存在，继续断言 `"context.raw_user_text or
user_message" in src` 只会要求一个被删的功能保留其拼装写法。

现改为守卫退役事实 + 保留「用户原话」这条语义仍由 Skill 手势扫描使用
（`planner._build_and_log_skill_event` 只扫 `raw_user_text`，不扫附件
拼装文本——同一事故根因的另一条防线，仍在生产路径上）。
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


# ---------- 闸预检已退役；「只认用户原话」改由 Skill 手势扫描承载 ----------

def test_gate_precheck_retired():
    """闸预检入口不得复活（业务型前置闸已删）。"""
    from src.video_agent.core import stage_probes as po
    from src.video_agent.core.planner import Planner

    assert not hasattr(po, "gate_precheck"), (
        "stage_probes.gate_precheck 回潮：规格/原料前置兜底卡已退役")
    assert not hasattr(Planner, "_run_gate_precheck"), (
        "planner._run_gate_precheck 回潮：该空壳已随同批删除")


def test_skill_gesture_scan_uses_raw_user_text():
    """同根因防线仍在：Skill `/slug` 手势只扫用户原话，不扫附件拼装文本
    （1111 事故：附件预览里的剧本对白不得触发技能注入）。"""
    src = (ROOT / "src/video_agent/core/planner.py").read_text(encoding="utf-8")
    assert 'getattr(context, "raw_user_text"' in src, (
        "Skill 手势扫描必须取 context.raw_user_text（多模态拼装不得参与）")
