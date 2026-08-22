# -*- coding: utf-8 -*-
"""P3-12 Skill 声明 schema：显式映射 + 全键校验 + step_done_conditions 消费。

任务#5 frontmatter 合一后口径：flow.steps/step_stages/dependencies 生产
通道已废除（frontmatter 声明即 fail-hard）；①③ 节保留的声明消费测试
均为内存 manifest（orchestrator/gates_cards 通用消费代码保留，测试
走 monkeypatch 注入，不依赖生产声明）。

钉死三件事：
① flow.step_stages 显式声明优先于启发式（声明权威；未声明回落并记遥测）；
② manifest_schema 全键校验（合法/非法用例，fail-closed；未声明键合法；
   废除键 fail-hard；gates 键白名单与 prompt_gates 锁源）；
③ step_done_conditions 声明探针消费（stage_done 任意阶段声明通道同构 +
   gates_cards.current_flow_step 声明优先接线）。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import gates_cards
from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import manifest_schema
from src.video_agent.skill_runtime import registry


# ---------- ① step_stages 显式映射 ----------


_DECL_MANIFEST = {
    "flow": {
        "spec_wizard": True,
        "steps": {
            "1": "读取并分析剧本文件",
            "2": "组装时间线",          # 文案故意误导：启发式会判 assembly
            "3": "生成所有音频资产",
        },
        "dependencies": {"2": [1], "3": [2]},
        "step_stages": {"1": "analysis", "2": "spec", "3": "audio_assets"},
    }
}
_ENTRY = SimpleNamespace(available_tools=["script_analyze"])


@pytest.fixture
def decl_env(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: _DECL_MANIFEST)
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    po.reset_step_stage_stats()
    yield
    po.reset_step_stage_stats()


def test_step_stages_declaration_beats_heuristic(decl_env):
    """声明权威：step2 文案含「组装」但声明 spec → 以声明为准。"""
    deps = po._stage_dependencies("任意Skill")
    assert deps.get("spec") == ["analysis"]
    assert deps.get("audio_assets") == ["spec"]
    stats = po.step_stage_stats()
    assert stats["explicit"] == 3
    assert stats["heuristic"] == 0


def test_step_stages_declared_absent_is_absorbed(monkeypatch):
    """声明阶段不在当前阶段表（无 video_assembler → 无 assembly 阶段）：
    边被吸收，不回退启发式（声明权威），记 declared_absent 遥测。"""
    manifest = {
        "flow": {
            "steps": {"1": "分析剧本", "2": "组装时间线剪辑输出"},
            "dependencies": {"2": [1]},
            "step_stages": {"1": "analysis", "2": "assembly"},
        }
    }
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: manifest)
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    po.reset_step_stage_stats()
    assert "assembly" not in {s.key for s in po.stage_table("任意Skill")}
    deps = po._stage_dependencies("任意Skill")
    assert "assembly" not in deps
    stats = po.step_stage_stats()
    assert stats["declared_absent"] == 1
    assert stats["heuristic"] == 0  # 文案含「组装/剪辑」也不得回退启发式


def test_undeclared_step_falls_back_to_heuristic_with_telemetry(monkeypatch):
    """未声明回落启发式并记遥测（命中率计数 = 启发式下线证据）。"""
    manifest = {"flow": {
        "steps": {"1": "读取并分析剧本文件", "2": "生成所有音频资产"},
        "dependencies": {"2": [1]},
    }}
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: manifest)
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    po.reset_step_stage_stats()
    po._stage_dependencies("任意Skill")
    stats = po.step_stage_stats()
    assert stats["heuristic"] == 2 and stats["explicit"] == 0


# ---------- ② manifest_schema 全键校验（frontmatter 合一） ----------


def test_canonical_stage_keys_drift_lock():
    """规范阶段键锁源：schema 复制值必须与 orchestrator 单一事实源一致。"""
    assert manifest_schema.CANONICAL_STAGE_KEYS == tuple(
        s.key for s in po.CANONICAL_STAGES)


def test_gate_keys_drift_lock():
    """gates 键白名单锁源：与 prompt_gates._DEFAULT_GATE_RULES 键集一致
    （manifest_schema docstring 承诺；漂移即本钉报出）。"""
    assert set(manifest_schema.GATE_KEYS) == set(prompt_gates._DEFAULT_GATE_RULES)


def test_schema_accepts_full_valid_manifest():
    good = {
        "flow": {
            "stage_executors": {"1": ["script_analyze"]},
            "step_done_conditions": {"2": "assembly"},
            "step_short_titles": {"1": "剧本分析"},
            "stages": {"assembly": {"done": "document:X.md",
                                     "skip": False,
                                     "executors": ["video_assembler"]}},
            "spec_wizard": True, "spec_gate": True, "script_required": False,
        },
        "pause": {"stage_pause": True},
        "gates": {"require_subtitle": True, "cjk_min_ratio": 0.2},
        "version": "1.0",
        "tools_required": ["script_analyze"],
        "source": "用户导入",
    }
    assert manifest_schema.validate_manifest_data(good) == []
    assert manifest_schema.validate_manifest_data(None) == []  # 零声明合法


@pytest.mark.parametrize("manifest,keyword", [
    # 流程步骤抄本通道废除：声明即 fail-hard
    ({"flow": {"steps": {"1": "a"}}}, "已废除"),
    ({"flow": {"step_stages": {"1": "spec"}}}, "已废除"),
    ({"flow": {"dependencies": {"2": [1]}}}, "已废除"),
    ({"flow": {"step_done_conditions": {"1": "wonderland"}}}, "规范阶段键"),
    ({"flow": {"stage_executors": {"1": "script_analyze"}}}, "数组"),
    ({"flow": {"step_short_titles": {"1": ""}}}, "非空字符串"),
    ({"flow": {"stages": {"spec": {"done": "X.md"}}}}, "document:"),
    ({"flow": {"stages": {"wonderland": {"skip": True}}}}, "不是规范阶段键"),
    ({"flow": {"stages": {"spec": {"skip": "yes"}}}}, "布尔值"),
    ({"flow": {"spec_wizard": "yes"}}, "布尔值"),
    ({"pause": {"stage_pause": "yes"}}, "布尔值"),
    # gates 键白名单 fail-hard（未登记闸键拒注册）
    ({"gates": {"unknown_gate": True}}, "不是平台登记的闸键"),
    ({"version": ""}, "非空字符串"),
    ({"tools_required": [""]}, "非空字符串"),
])
def test_schema_rejects_illegal_declarations(manifest, keyword):
    issues = manifest_schema.validate_manifest_data(manifest)
    assert issues and any(keyword in i for i in issues)


# ---------- ③ step_done_conditions 消费 ----------


@pytest.fixture
def done_cond_env(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {
            "steps": {"1": "分析", "2": "规格"},
            "step_done_conditions": {"2": "spec"},
            "stages": {"spec": {"done": "document:定制规格.md"}},
        },
    })
    return monkeypatch


def test_step_done_consumes_declaration(done_cond_env):
    """step_done_conditions {step: 阶段键} → 该阶段客观探针是唯一事实源。"""
    with_spec = {"documents": [{"name": "定制规格.md"}]}
    assert po.step_done_declared("2", "X") == "spec"
    assert po.step_done("2", with_spec, "X") is True
    assert po.step_done("2", {"documents": []}, "X") is False
    # 未声明步 fail-closed（不猜）；三态探针区分「无声明」与「声明了未完成」
    assert po.step_done_declared("1", "X") is None
    assert po.step_done("1", with_spec, "X") is False
    assert po.step_done_probe("1", with_spec, "X") is None
    assert po.step_done_probe("2", {"documents": []}, "X") is False


def test_stage_done_declaration_channel_any_stage(done_cond_env):
    """声明探针通道任意阶段同构：flow.stages.spec.done 覆盖平台探针。"""
    assert po.stage_done("spec", {"documents": [{"name": "定制规格.md"}]}, "X") is True
    # 平台默认规格探针（Final_Video_Spec.md）在声明覆盖下不作数
    assert po.stage_done("spec", {"documents": [{"name": "Final_Video_Spec.md"}]}, "X") is False
    # 未声明阶段回落平台客观探针
    assert po.stage_done("analysis", {"analysis": {"summary": "s"}}, "X") is True


def test_current_flow_step_consumes_step_done_conditions(monkeypatch):
    """消费接线：gates_cards.current_flow_step 声明优先（注册钩子在
    pipeline_orchestrator 导入期落地），声明步可越过 v1 硬规则边界。"""
    assert gates_cards._STEP_DONE_PROBE is po.step_done_probe
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {
            "steps": {"1": "分析", "2": "规格", "3": "故事板", "4": "设定图"},
            "step_done_conditions": {"2": "spec", "4": "spec"},
        },
    })
    state = {
        "analysis": {"summary": "s"},
        "documents": [{"name": "Final_Video_Spec.md", "content": "画幅 16:9"}],
    }
    # step1 硬规则 + step2 声明探针通过；step3 未声明且故事板未完成 → 断在 2
    assert gates_cards.current_flow_step(state, "任意Skill") == 2
    # step4 声明驱动：越过 v1「step4+ 不判定」边界
    state2 = {"analysis": {"summary": "s"},
              "documents": [{"name": "Final_Video_Spec.md", "content": "画幅 16:9"}]}
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {
        "flow": {
            "steps": {"1": "分析", "2": "规格", "3": "故事板", "4": "设定图"},
            "step_done_conditions": {"2": "spec", "3": "spec", "4": "spec"},
        },
    })
    assert gates_cards.current_flow_step(state2, "任意Skill") == 4
