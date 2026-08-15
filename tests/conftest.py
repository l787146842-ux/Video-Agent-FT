import pytest

from pathlib import Path


@pytest.fixture(autouse=True)
def _test_skill_stubs(monkeypatch):
    """B4/F31：测试桩 Skill 从 data/skills 迁至 tests/fixtures/skills。

    注册表按 slug 解析时优先查夹具目录（生产技能仍走 data/skills），
    测试按名称引用测试桩无需触碰生产目录；技能下拉框/目录不再含测试桩。"""
    from src.video_agent.web import skill_docs as sd

    fixture_dir = Path(__file__).parent / "fixtures" / "skills"
    orig = sd.get_skill_doc

    def patched(slug):
        f = fixture_dir / f"{slug}.md"
        if f.exists():
            return sd._parse_doc(slug, f.read_text(encoding="utf-8"))
        return orig(slug)

    monkeypatch.setattr(sd, "get_skill_doc", patched)


@pytest.fixture(autouse=True)
def _disable_blackbox(monkeypatch):
    """测试期禁用黑匣子档案落盘：模拟截断/零产出的用例不得污染真实 logs 目录。

    executors 在函数内延迟 import dump_case，patch 模块属性即可全局生效。
    """
    from src.video_agent.skill_runtime import blackbox

    monkeypatch.setattr(blackbox, "dump_case", lambda *a, **k: "")


@pytest.fixture(autouse=True)
def _state_backend_json():
    """测试期状态后端钉 json（814E6：生产默认 sqlite，测试基线保持 json；
    sqlite 行为由 test_repository_sqlite 直测覆盖）。"""
    from src.video_agent.config import settings

    old = settings.state_backend
    object.__setattr__(settings, "state_backend", "json")
    yield
    object.__setattr__(settings, "state_backend", old)


@pytest.fixture
def set_global_setting():
    """定点突破 frozen Settings（与 runtime_settings 热更新同法），测试结束恢复。"""
    from src.video_agent.config import settings

    applied: dict = {}

    def _set(key: str, value) -> None:
        if key not in applied:
            applied[key] = getattr(settings, key)
        object.__setattr__(settings, key, value)

    yield _set
    for key, old in applied.items():
        object.__setattr__(settings, key, old)
