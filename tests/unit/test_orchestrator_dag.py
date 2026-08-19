"""3A 编排器 DAG 化调度钉死测试。

用 AI-短剧一站式生成 风格的 sidecar 依赖图（6 等 4、5 完成；5 无独立平台
阶段被吸收）钉死：拓扑就绪集、同批并行、线性回落、step→stage 映射。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import pipeline_orchestrator as po
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
        lambda key, state: key in done_keys,
    )


def test_step_to_stage_mapping(dag_env):
    """依赖图翻译：step 号 → 平台阶段（5 分镜表格图归入 ke_media，边被吸收）。"""
    deps = po._stage_dependencies(_SKILL)
    assert deps.get("structure") == ["analysis", "spec"]
    # 未声明阶段回落线性前置：spec 不得首轮即就绪
    assert deps.get("spec") == ["analysis"]
    assert deps.get("ke_media") == ["structure"]
    # 6 → [4,5]：5 归入 ke_media，故 shot_media 前置坍缩为 ke_media
    assert set(deps.get("shot_media", [])) == {"ke_media"}
    assert deps.get("audio_assets") == ["structure"]
    assert "ke_media" in deps.get("assembly", [])
    assert "shot_media" in deps.get("assembly", [])


def test_dag_shot_media_waits_for_ke_media(dag_env, monkeypatch):
    """钉死：ke_media 未完成时 shot_media 不就绪；确定性阶段 audio 先执行。"""
    _set_done(monkeypatch, {"analysis", "spec", "structure"})
    batch, handoff = po.next_batch({}, _SKILL)
    keys = [s.key for s in batch]
    # audio 前置 structure 已完 → 就绪；ke_media 创作型就绪但确定性优先不交接
    assert keys == ["audio_assets"]
    assert not handoff


def test_dag_shot_media_ready_after_ke(dag_env, monkeypatch):
    """钉死：ke_media 完成后 shot_media 就绪（创作型→交接模型循环）。"""
    _set_done(monkeypatch, {
        "analysis", "spec", "structure", "ke_media", "audio_assets",
    })
    batch, handoff = po.next_batch({}, _SKILL)
    # shot_media 前置 ke_media 已完 → 创作型就绪 → 交接
    assert batch == [] and handoff is True
    # ke_media 未完成时 shot_media 不就绪：audio 已完则无确定性就绪→也不交接
    _set_done(monkeypatch, {"analysis", "spec", "structure", "audio_assets"})
    batch, handoff = po.next_batch({}, _SKILL)
    # ke_media 创作型就绪 → 交接（不会越过 ke_media 直接跑 shot_media）
    assert batch == [] and handoff is True


def test_dag_handoff_when_only_creative_ready(dag_env, monkeypatch):
    """钉死：创作型就绪优先交接；shot_media 完成后 assembly 就绪执行。"""
    _set_done(monkeypatch, {
        "analysis", "spec", "structure", "ke_media", "shot_media",
        "audio_assets",
    })
    batch, handoff = po.next_batch({}, _SKILL)
    assert [s.key for s in batch] == ["assembly"] and not handoff
    # 全部完成 → 空批 + 不交接
    _set_done(monkeypatch, {
        "analysis", "spec", "structure", "ke_media", "shot_media",
        "audio_assets", "assembly",
    })
    batch, handoff = po.next_batch({}, _SKILL)
    assert batch == [] and handoff is False


def test_linear_fallback_without_dependencies(dag_env, monkeypatch):
    """钉死：无 dependencies 声明 → 线性回落（第一个未完成阶段）。"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {"spec_wizard": True},
    })
    _set_done(monkeypatch, {"analysis"})
    batch, handoff = po.next_batch({}, _SKILL)
    assert [s.key for s in batch] == ["spec"] and not handoff
    # 第一个未完成是创作型 → 交接
    _set_done(monkeypatch, {"analysis", "spec", "structure", "ke_media"})
    batch, handoff = po.next_batch({}, _SKILL)
    assert batch == [] and handoff is True
