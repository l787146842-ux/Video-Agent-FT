import pytest


@pytest.fixture(autouse=True)
def _disable_blackbox(monkeypatch):
    """测试期禁用黑匣子档案落盘：模拟截断/零产出的用例不得污染真实 logs 目录。

    executors 在函数内延迟 import dump_case，patch 模块属性即可全局生效。
    """
    from src.video_agent.skill_runtime import blackbox

    monkeypatch.setattr(blackbox, "dump_case", lambda *a, **k: "")
