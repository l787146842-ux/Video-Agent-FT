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
    # 0818 架构板正批 B0：sidecar 声明随文档同镜像（registry 双读在测试期可见）
    real_sidecar = Path(REAL_DIR).parent / "skills_manifests"
    if real_sidecar.exists():
        sc = mirror.parent / "skills_manifests"
        sc.mkdir(exist_ok=True)
        for f in real_sidecar.glob("*.json"):
            shutil.copy2(f, sc / f.name)
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



# （原 _disable_blackbox fixture 已随任务#36 B5 执行器退役删除：
# 黑匣子档案（skill_runtime/blackbox.py）唯一消费方为 exec_spec/exec_common，
# 随执行器族一并退役。）


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


@pytest.fixture(autouse=True)
def _degradation_watchdog(request):
    """批5 劣化即红守卫（全 tests/ 覆盖：unit + integration）。

    核心探测点的「预期外降级」遥测（record_degradation）一旦在单测运行期间
    触发即测试失败——承重接线断裂不再静默存活（对齐评测驱动公理，宪法 §2.6）。
    有意触发降级的故障注入测试用 @pytest.mark.allow_degradation 豁免。"""
    from src.video_agent.core import live_metrics

    live_metrics.reset_degradations()
    yield
    if request.node.get_closest_marker("allow_degradation"):
        live_metrics.reset_degradations()
        return
    hits = live_metrics.get_degradations()
    live_metrics.reset_degradations()
    assert not hits, (
        "承重接线意外降级（劣化即红）: "
        + ", ".join(f"{h['point']}×{h['count']}" for h in hits)
        + "；确属有意的故障注入请加 @pytest.mark.allow_degradation"
    )
