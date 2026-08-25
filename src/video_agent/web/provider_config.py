"""薄 re-export 壳。

provider_config 实为领域服务（仅依赖 adapters/config/state.models/utils），
实现体位于 src/video_agent/core/provider_config.py；
web 侧 12+ 消费方经本壳兼容，import 零改动。

属性查找归一：本壳不做绑定快照（import * 会冻结引用，patch 实现体到不了
经壳属性查找的调用方），改用模块 __getattr__ 实时转发至实现体——
monkeypatch 实现体 src.video_agent.core.provider_config 即对所有经本壳的
属性查找生效。from-import 消费方仍在导入时刻绑定
（既有行为不变）。
"""
from src.video_agent.core import provider_config as _core_pc

__all__ = [n for n in dir(_core_pc) if not n.startswith("_")]


def __getattr__(name: str):
    """属性查找实时转发实现体（PEP 562；单一事实源，无绑定快照）。"""
    return getattr(_core_pc, name)
