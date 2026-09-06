"""模型单次输出上限查表 — 跨切面原语（utils 下沉层，宪法 §六）。

消费方：core/token_budget（预算口径）与 adapters/openai_compat（400 大
max_tokens 钳制分支）。表外置 data/model_output_limits.json，骨架同
model_context_windows：懒加载 + 缺失/损坏按空表降级 + 子串先到先得
（键序即优先级）。只收录保守的供应商文档保证值；未命中回落全局
LLM_OUTPUT_LIMIT。放 utils/ 而非 core/ 的原因：adapters 禁止依赖 core
具体实现（check_layer_imports R3），纯查表无 tracer/ports 依赖。
"""
import json
from typing import Dict, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.paths import DATA_DIR

_OUTPUT_LIMITS_FILE = DATA_DIR / "model_output_limits.json"
_MODEL_OUTPUT_LIMITS: Optional[Dict[str, int]] = None


def _load_output_limits() -> Dict[str, int]:
    """懒加载并缓存输出上限表；文件缺失/损坏时按空表降级（警告仅首载打一次）。"""
    global _MODEL_OUTPUT_LIMITS
    if _MODEL_OUTPUT_LIMITS is None:
        try:
            data = json.loads(_OUTPUT_LIMITS_FILE.read_text(encoding="utf-8"))
            _MODEL_OUTPUT_LIMITS = {str(k): int(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"[ModelLimits] 模型输出上限表加载失败，按空表降级: {e}")
            _MODEL_OUTPUT_LIMITS = {}
    return _MODEL_OUTPUT_LIMITS


def output_limit_for_model(model: str) -> int:
    """按模型名查单次输出 token 上限；未收录的模型回落 settings.llm_output_limit。"""
    m = (model or "").lower()
    for key, limit in _load_output_limits().items():
        if key in m:
            return limit
    return settings.llm_output_limit
