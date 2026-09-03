"""P3-17 提示词工程收尾钉测试（整改批 3.5 修订）：
1. （已删）legacy 路径单注入与 SKILL_RUNTIME_MODE 灰度开关——回退闸随
   批 3.5 fail-hard 退役：通用主路径为唯一路径，legacy/executors 代码与
   settings.skill_runtime 字段均已物理删除，残留环境变量启动即拒；
2. 运行时组装总长遥测：record_sections 内存注册（Q12 裁决 2026-09-01：
   jsonl 落盘样本无消费方，已停写；只保留内存注册供 context-usage 端点）。
"""


# ---------- 运行时组装总长遥测 ----------

def test_record_sections_memory_registry():
    """record_sections 只写内存注册表（不落盘）；get_sections 返回副本。"""
    from src.video_agent.utils import live_metrics

    live_metrics.record_sections("proj", {"total": 12345, "skill": 10})
    assert live_metrics.get_sections("proj")["total"] == 12345
    # 副本语义：外部改动不影响注册表；空 project_id 不落任何记录
    snap = live_metrics.get_sections("proj")
    snap["total"] = 0
    assert live_metrics.get_sections("proj")["total"] == 12345
    live_metrics.record_sections("", {"total": 1})
    assert live_metrics.get_sections("") == {}
