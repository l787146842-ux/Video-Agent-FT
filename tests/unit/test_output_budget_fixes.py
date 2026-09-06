# -*- coding: utf-8 -*-
"""输出预算查表回归（1111 项目事故 + 4444 项目输出预算修法批 1）。

原事故：script_analyze 在 max_tokens=2048 上被推理模型思考占满额度。
修复的模型输出上限查表（output_limit_for_model）是通用能力，继续钉死；
2026-09-07 表外置 data/model_output_limits.json（骨架同
model_context_windows.json：懒加载 + 损坏降级空表 + 子串先到先得），
实现下沉 utils/model_limits（adapters 400 钳制分支同用，宪法 §六），
core/token_budget re-export 保持原导入路径。补录 glm/zhipu 保证值
（智谱开放平台文档：GLM-5/4.7/4.6 系列 128K、GLM-4.5 系列 96K 输出）。
llm_max_tokens 默认 256k 对齐 dsh（DEFAULT_MAX_TOKENS），400 拒收大值时
adapter 钳制分支按本表回落。
"""
import json

import pytest

import src.video_agent.utils.model_limits as model_limits
from src.video_agent.config import settings
from src.video_agent.core.token_budget import output_limit_for_model  # re-export 路径
from src.video_agent.utils.model_limits import output_limit_for_model as _direct


@pytest.fixture(autouse=True)
def _reset_output_limits_cache():
    """模块级懒加载缓存跨用例隔离（改指向文件后必须重置才重读）。"""
    model_limits._MODEL_OUTPUT_LIMITS = None
    yield
    model_limits._MODEL_OUTPUT_LIMITS = None


# ---------- 表值（外置 JSON） ----------

def test_output_limit_known_models():
    assert output_limit_for_model("deepseek-v4-flash") == 8_192
    assert output_limit_for_model("gemini-3.1-pro") == 32_768
    assert output_limit_for_model("Qwen/Qwen3-235B-A22B") == 8_192


def test_output_limit_glm_family():
    """glm/zhipu 保证值：具体键先到先得，家族键保守兜底。"""
    assert output_limit_for_model("glm-5.3-flash") == 131_072
    assert output_limit_for_model("glm-4.7") == 131_072
    assert output_limit_for_model("glm-4.6") == 131_072
    assert output_limit_for_model("glm-4.5") == 98_304
    assert output_limit_for_model("zhipu/glm-4.6") == 131_072
    assert output_limit_for_model("glm-4") == 98_304


def test_output_limit_unknown_model_falls_back():
    assert output_limit_for_model("some-unknown-model") == settings.llm_output_limit
    assert output_limit_for_model("") == settings.llm_output_limit


def test_reexport_path_same_function():
    """core/token_budget 的 re-export 与 utils 实现同源（旧导入路径不脱钩）。"""
    assert output_limit_for_model is _direct


def test_llm_max_tokens_default_is_256k():
    """批 1 止血：默认输出预算 256k（max_tokens 是上限不是目标；
    思考耗尽小帽子的 4444 事故根因①）。断言声明默认值（env 覆盖不算数）。"""
    from dataclasses import fields

    from src.video_agent.config import Settings

    f = {x.name: x for x in fields(Settings)}["llm_max_tokens"]
    assert f.default_factory() == 256_000


# ---------- 懒加载降级骨架（同 _load_context_windows） ----------

def test_missing_file_degrades_to_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(model_limits, "_OUTPUT_LIMITS_FILE", tmp_path / "absent.json")
    assert output_limit_for_model("glm-4.6") == settings.llm_output_limit


def test_corrupt_file_degrades_to_empty(tmp_path, monkeypatch):
    bad = tmp_path / "model_output_limits.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(model_limits, "_OUTPUT_LIMITS_FILE", bad)
    assert output_limit_for_model("glm-4.6") == settings.llm_output_limit


def test_production_table_file_loads():
    """生产表必须可解析且含 glm 键（防外置文件损坏入库）。"""
    data = json.loads(model_limits._OUTPUT_LIMITS_FILE.read_text(encoding="utf-8"))
    assert data["deepseek"] == 8_192
    assert "glm-5" in data and "glm" in data
