"""四轮 R6 回归（观察项 #15）：Skill 暂停点判定黄金语料——解析劣化即红。

背景：暂停点消费链 = manifest.pause.stage_pause > pause_rules 声明块 >
正文关键词兜底（何时暂停/强制暂停点）。自然语言表述多样，解析精度天然有上限；
本测试把 16 个存量 Skill 的现行判定值钉成黄金快照（tests/fixtures/skill_pause_golden.json），
任何变化（含「改进」）都必须显式裁决并刷新快照，不许静默漂移。

已知边界案例（快照内 false 但正文含暂停语义）：古风甜宠短剧等——其 <planner>
用「必须暂停并获得用户确认」表述，不命中兜底关键词；如未来需要生效，
按 S1 机制在 manifest 声明 pause.stage_pause（需用户裁决，G1 约束）。
"""
import json
from pathlib import Path

from src.video_agent.skill_runtime.guard import skill_requires_stage_pause
from src.video_agent.skill_runtime.registry import parse_pause_rules

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "skill_pause_golden.json"


def test_r6_golden_pause_detection_matches_snapshot():
    """全部存量 Skill 的暂停点判定与黄金快照逐条一致（劣化/漂移即红）。"""
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert golden, "黄金快照为空"
    diffs = []
    for name, expected in golden.items():
        actual = bool(skill_requires_stage_pause(name))
        if actual != expected:
            diffs.append(f"「{name}」期望 {expected} 实际 {actual}")
    assert not diffs, (
        "暂停点判定偏离黄金快照（如属有意改进，请裁决后刷新快照）：\n" + "\n".join(diffs)
    )


def test_r6_pause_rules_block_variants():
    """pause_rules 声明块表述变体：合法 JSON 解析；非法/缺省返回 None（兜底接管）。"""
    assert parse_pause_rules('```json pause_rules\n{"stage_pause": true}\n```') == {"stage_pause": True}
    assert parse_pause_rules('```json pause_rules\n{"stage_pause": false}\n```') == {"stage_pause": False}
    assert parse_pause_rules('```json pause_rules\n{"stage_pause": 1}\n```') == {"stage_pause": True}
    # 非法 JSON / 无声明块 / 非 dict → None（交兜底关键词检测）
    assert parse_pause_rules('```json pause_rules\n{bad json}\n```') is None
    assert parse_pause_rules("普通正文，无声明块") is None
    assert parse_pause_rules("") is None
    # 白名单外键忽略
    assert parse_pause_rules('```json pause_rules\n{"unknown_key": true}\n```') == {}


def test_r6_fallback_keyword_variants():
    """兜底关键词检测：「何时暂停/强制暂停点」命中即要求暂停（兼容存量文档表述）。"""
    from src.video_agent.skill_runtime import guard

    src = Path(guard.__file__).read_text(encoding="utf-8")
    # 防漂移：兜底关键词集合变更必须同批刷新本测试与黄金快照
    assert '"何时暂停" in content' in src
    assert '"强制暂停点" in content' in src
