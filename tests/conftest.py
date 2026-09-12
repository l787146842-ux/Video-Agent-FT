import os
import shutil

import pytest

from pathlib import Path

# 六轮 S4/N2：测试进程不落生产日志文件——必须在任何项目模块导入（config
# settings 实例化）之前设置；避免 pytest 与运行中的服务争用同一日志文件
# 触发 loguru rotation rename 失败（WinError 32）。外部显式设置时从其值。
os.environ.setdefault("LOG_FILE_ENABLED", "false")

# P9：测试期关闭请求限流（0 = 不限流）——端点契约用例同进程内多次命中
# /api/agent/chat 等受限端点，不应撞 10 req/min 令牌桶（生产默认不变）
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")

# D-01：core 端口装配（测试侧装配点）——core 层经 core/ports.py 访问 web 层
# 实现（生成管线/供应商配置/生成日志/Skill 文档），任何测试导入前完成注入。
from src.video_agent.web.port_wiring import install_core_ports  # noqa: E402

install_core_ports()


@pytest.fixture(scope="session")
def _skill_mirror_dir(tmp_path_factory):
    """R2：测试期 Skill 目录镜像——生产 data/skills 与夹具桩拷入临时镜像，
    测试读写全部落镜像（含 .history 备份机制原样工作），生产目录零污染。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR
    from src.video_agent.skill_runtime.frontmatter import SKILL_DOC_NAME

    mirror = tmp_path_factory.mktemp("skills_mirror")
    # 批3 单一包形态：每个 Skill = <slug>/SKILL.md 目录包，生产目录与夹具
    # 桩一律整包入镜像（含 references/ 附属资源），平铺单文件形态已退役。
    for src_dir in (Path(REAL_DIR), Path(__file__).parent / "fixtures" / "skills"):
        for p in src_dir.iterdir():
            if not p.is_dir() or p.name.startswith("."):
                continue
            if (p / SKILL_DOC_NAME).exists():
                shutil.copytree(p, mirror / p.name)
    # 任务#5：声明与正文合一（文档头部 frontmatter），随 md 拷贝天然进镜像；
    # 原外置 sidecar 镜像块随 data/skills_manifests/ 退役删除
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
def _state_backend_baseline():
    """测试期状态后端基线（任务 #18 / P10 双维度守护）：
    - STATE_BACKEND env 未显式设置 → 钉 json（814E6 既有基线，默认行为不变）；
    - 显式设置（如 CI sqlite job 的 STATE_BACKEND=sqlite）→ 跟随 env，
      让全量套件真正跑在该后端上，守护生产默认路径（sqlite）。
    注意：env 须在进程启动前设置才影响 settings 单例初值；fixture 只负责
    把运行期漂移钉回基线口径。"""
    if os.environ.get("STATE_BACKEND"):
        yield
        return

    from src.video_agent.config import settings

    old = settings.state_backend
    object.__setattr__(settings, "state_backend", "json")
    yield
    object.__setattr__(settings, "state_backend", old)


@pytest.fixture(autouse=True)
def _trace_context_isolation():
    """逐测试隔离 tracer 的 contextvar 追踪绑定。

    部分用例直连 `AgentTracer()` 并 start_trace 但不 finish（如遥测类），会把带
    live current 的追踪态留在模块级 contextvar；同 worker 多文件共享上下文时会
    漂入下一条用例（D2 父帧链后尤其敏感）。此处入前置 None、出后还原，恢复隔离。"""
    from src.video_agent.core import tracer as _tr

    token = _tr._trace_ctx_var.set(None)
    yield
    _tr._trace_ctx_var.reset(token)


@pytest.fixture(autouse=True)
def _state_singleton_isolation(tmp_path):
    """任务 #18 / P10：StateManager 全局单例逐测试隔离到临时工作区。

    根因：未绑定单例的代码路径（如 fc_tool_runner 的 PauseSlot 互斥检查）
    经 get_instance() 惰性建实例时会落到真实 workspace/——sqlite 后端下
    读到生产库中真实状态（如 active_pause），json 后端下则可能读/写生产
    state.json；两者都是测试隔离缺陷。此夹具把单例钉到临时目录，
    行为对两种后端一致；自带 tmp 夹具显式绑定单例的测试不受影响。
    """
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    StateManager._instance = StateManager(str(tmp_path / "_singleton_ws"))
    yield
    StateManager.reset_instance()


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
    from src.video_agent.utils import live_metrics

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
