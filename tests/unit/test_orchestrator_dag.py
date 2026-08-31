"""3A 编排器 DAG 化调度钉死测试。

用 AI-短剧一站式生成 风格的声明依赖图（6 等 4、5 完成；5 无独立平台
阶段被吸收）钉死：依赖图翻译、step→stage 映射、规格闸就绪探针。
（拓扑就绪集/同批并行/交接判定的调度函数钉死用例已随任务#27
文本轨残留退役删除：被测调度函数退役（ADR-0004 后 runtime 永不执行
阶段），存活消费语义迁入 _spec_stage_pending 探针并由下方同构用例钉死。）
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import stage_probes as po
from src.video_agent.skill_runtime import registry

_SKILL = "dag-test-skill"

_MANIFEST = {
    "flow": {
        "spec_wizard": True,
        "stage_executors": {
            "1": ["script_analyze"],
            "3": ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"],
        },
        "steps": {
            "1": "读取并分析用户上传的剧本文件，提取角色、场景、关键道具",
            "2": "将全局制作参数写入 Final_Video_Spec.md",
            "3": "设计 Storyboard：登记所有 key_element，拆解 shot 列表",
            "4": "生成所有 key_element 设定图（角色三视图、场景四视图）",
            "5": "生成每批次运镜轨迹示意图（分镜表格图）",
            "6": "逐 shot 生成视频，每镜仅引用对应 key_element 图像",
            "7": "生成所有 audio_layer 音频资产（台词、BGM、旁白）",
            "8": "按 Storyboard 顺序组装时间线，完成音画同步",
        },
        "dependencies": {
            "3": [1, 2], "4": [3], "5": [3], "6": [4, 5], "7": [3],
            "8": [4, 5, 6, 7],
        },
        # 整改批 3.5：描述关键词启发式已退役（声明权威）——step→stage
        # 映射一律显式声明
        "step_stages": {
            "1": "analysis", "2": "spec", "3": "structure",
            "4": "ke_media", "5": "ke_media", "6": "shot_media",
            "7": "audio_assets", "8": "assembly",
        },
    }
}

_ENTRY = SimpleNamespace(available_tools=[
    "script_analyze", "storyboard_key_elements", "storyboard_shots",
    "storyboard_audio", "write_media_prompt", "audio_generate", "video_assembler",
])


@pytest.fixture
def dag_env(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: _MANIFEST)
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    return monkeypatch


def _set_done(monkeypatch, done_keys):
    monkeypatch.setattr(
        po, "stage_done",
        lambda key, state, skill="": key in done_keys,
    )


def test_step_to_stage_mapping(dag_env):
    """依赖图翻译：step 号 → 平台阶段（5 分镜表格图归入 ke_media，边被吸收；
    2026-08-31 用户裁决 spec 阶段退役后，映射到 spec 的声明被吸收）。"""
    deps = po._stage_dependencies(_SKILL)
    assert deps.get("structure") == ["analysis"]
    assert deps.get("ke_media") == ["structure"]
    # 6 → [4,5]：5 归入 ke_media，故 shot_media 前置坍缩为 ke_media
    assert set(deps.get("shot_media", [])) == {"ke_media"}
    assert deps.get("audio_assets") == ["structure"]
    assert "ke_media" in deps.get("assembly", [])
    assert "shot_media" in deps.get("assembly", [])


