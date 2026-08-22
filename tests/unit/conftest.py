"""unit 级共享 fixture。"""
import pytest


@pytest.fixture(autouse=True)
def _fast_adapter_retry(monkeypatch):
    """单测收敛 adapter 瞬时故障重试退避（任务 #26）：重试次数不变，
    仅把指数退避等待压到可忽略，避免 transient 用例拖慢整个套件。"""
    from types import SimpleNamespace

    from src.video_agent.config import settings
    import src.video_agent.adapters.base_chat as bc

    monkeypatch.setattr(
        bc,
        "settings",
        SimpleNamespace(
            adapter_retry_max=settings.adapter_retry_max,
            adapter_retry_base_delay=0.001,
        ),
    )
