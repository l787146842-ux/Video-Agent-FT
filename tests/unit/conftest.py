# -*- coding: utf-8 -*-
"""unit 测试公共守卫（批5 审核整改）。

degradation 劣化即红：核心探测点的「预期外降级」遥测（record_degradation）
一旦在单测运行期间触发即测试失败——承重接线断裂不再静默存活，
对齐评测驱动公理（宪法 §2.6 校准闭环同源纪律）。

有意触发降级的测试（故障注入/回落验证）用
``@pytest.mark.allow_degradation`` 豁免本守卫。
"""
import pytest

from src.video_agent.core import live_metrics


@pytest.fixture(autouse=True)
def _degradation_watchdog(request):
    live_metrics.reset_degradations()
    yield
    if request.node.get_closest_marker("allow_degradation"):
        live_metrics.reset_degradations()
        return
    hits = live_metrics.get_degradations()
    live_metrics.reset_degradations()
    assert not hits, (
        "承重接线意外降级（劣化即红）: "
        + ", ".join(f"{h['point']}×{h['count']}" for h in hits)
        + "；确属有意的故障注入请加 @pytest.mark.allow_degradation"
    )
