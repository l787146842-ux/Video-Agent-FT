"""输出预算查表回归（1111 项目事故）。

原事故：script_analyze 在 max_tokens=2048 上被推理模型思考占满额度。
修复的模型输出上限查表（token_budget.output_limit_for_model）是通用
能力，继续钉死；执行器侧的截断扩额重试用例（_llm_json_call）已随
任务#36 B5 执行器一步退役删除。
"""
from src.video_agent.config import settings
from src.video_agent.core.token_budget import output_limit_for_model


# ---------- 输出上限查表 ----------

def test_output_limit_known_models():
    assert output_limit_for_model("deepseek-v4-flash") == 8_192
    assert output_limit_for_model("gemini-3.1-pro") == 32_768
    assert output_limit_for_model("Qwen/Qwen3-235B-A22B") == 8_192


def test_output_limit_unknown_model_falls_back():
    assert output_limit_for_model("some-unknown-model") == settings.llm_output_limit
    assert output_limit_for_model("") == settings.llm_output_limit
