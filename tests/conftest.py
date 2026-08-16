import os
import shutil

import pytest

from pathlib import Path

# 六轮 S4/N2：测试进程不落生产日志文件——必须在任何项目模块导入（config
# settings 实例化）之前设置；避免 pytest 与运行中的服务争用同一日志文件
# 触发 loguru rotation rename 失败（WinError 32）。外部显式设置时从其值。
os.environ.setdefault("LOG_FILE_ENABLED", "false")


@pytest.fixture(scope="session")
def _skill_mirror_dir(tmp_path_factory):
    """R2：测试期 Skill 目录镜像——生产 data/skills 与夹具桩拷入临时镜像，
    测试读写全部落镜像（含 .history 备份机制原样工作），生产目录零污染。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    mirror = tmp_path_factory.mktemp("skills_mirror")
    for f in Path(REAL_DIR).glob("*.md"):
        shutil.copy2(f, mirror / f.name)
    fixture_dir = Path(__file__).parent / "fixtures" / "skills"
    for f in fixture_dir.glob("*.md"):
        if f.name != "README.md":
            shutil.copy2(f, mirror / f.name)
    return mirror


@pytest.fixture(autouse=True)
def _test_skill_stubs(monkeypatch, _skill_mirror_dir):
    """测试期 SKILL_DOCS_DIR 指向镜像目录：save/delete/list/history 全路径
    与生产语义一致，但不触碰真实 data/skills（桩复活事故根因清偿）。"""
    from src.video_agent.web import skill_docs as sd

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", _skill_mirror_dir)
    # 注册表可能已按真实目录同步过（模块级缓存）：强制按镜像重同步
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()
    registry.sync_all(force=True)
    yield
    registry.reset_registry()



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
