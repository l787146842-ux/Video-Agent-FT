"""core 层端口注册表（依赖倒置，action_executor 下沉 core）。

宪法铁律：core 层不得 import web 层（含延迟导入与 TYPE_CHECKING）。
core 需要 web 层提供的能力（生成管线 / 供应商配置 / 生成日志面板 /
Skill 文档域）时，经本注册表访问「端口」；端口实现由 web 层装配点
（`web/port_wiring.install_core_ports`）注入。

端口持有实现模块/对象的引用，属性在调用时解析——web 模块属性上的
monkeypatch 在测试期照常生效。

装配点（缺失端口时访问器抛 PortNotInstalledError）：
- web/app.py lifespan（生产服务）
- tests/conftest.py（测试进程）
- scripts/run_eval_pipeline.py（评测管线）

新入口接入规程：新增脚本/进程入口若触达端口，必须在入口处先调用
`web/port_wiring.install_core_ports()`（参照上述装配点）；仅读 Skill
文档目录的脚本优先改传显式目录参数绕过端口（不引入 web 依赖）。

各端口面（duck-typed，实现源）：
- generation      ：submit_image_task / submit_video_task /
                    collect_shot_video_refs（web/generation.py）
- provider_config ：load_merged_providers / get_provider_config /
                    spec_media_preference / spec_production_params /
                    stamp_draft_spec_preference / resolve_provider_ref
                    （core/provider_config.py）
- task_log        ：record_gate_gen_log(prompt, hard_errors)
                    （web 装配适配器 → task_manager.record_gen_log）
- skill_docs      ：list_skill_docs / resolve_skill_content /
                    split_skill_sections 等（web/skill_docs.py）
- assets          ：iter_items（本地素材库扫描；
                    web/routes/assets_library.py）
- task_stop       ：stop_bound_tasks（对象删除级联前掐停绑定在途任务；
                    web/agent_task_manager.py）
- canvas          ：online_cached（画布健康探测缓存，planner 工具裁剪用；
                    web/port_wiring → adapters.canvas_adapter.canvas_online_cached）
"""
from typing import Any, Dict, Optional


class PortNotInstalledError(RuntimeError):
    """端口未注入：web 层装配点（install_core_ports）尚未执行。"""


_PORTS: Dict[str, Any] = {}


def install_ports(
    *,
    generation: Optional[Any] = None,
    provider_config: Optional[Any] = None,
    task_log: Optional[Any] = None,
    skill_docs: Optional[Any] = None,
    assets: Optional[Any] = None,
    task_stop: Optional[Any] = None,
    canvas: Optional[Any] = None,
) -> None:
    """装配端口（幂等；只覆盖本次传入的非 None 端口）。"""
    if generation is not None:
        _PORTS["generation"] = generation
    if provider_config is not None:
        _PORTS["provider_config"] = provider_config
    if task_log is not None:
        _PORTS["task_log"] = task_log
    if skill_docs is not None:
        _PORTS["skill_docs"] = skill_docs
    if assets is not None:
        _PORTS["assets"] = assets
    if task_stop is not None:
        _PORTS["task_stop"] = task_stop
    if canvas is not None:
        _PORTS["canvas"] = canvas


def clear_ports() -> None:
    """清空全部端口（测试隔离用）。"""
    _PORTS.clear()


def _port(name: str) -> Any:
    port = _PORTS.get(name)
    if port is None:
        raise PortNotInstalledError(
            f"core 端口 '{name}' 未注入。修复指引：调用 "
            "web/port_wiring.install_core_ports()（web/app.py lifespan 与 "
            "tests/conftest.py 已自动装配）；脚本入口请在入口处补调用，"
            "或为脚本提供显式目录参数绕过端口"
        )
    return port


def generation_port() -> Any:
    """生成任务管线端口（任务提交/参考素材收集；实现 = web/generation.py）"""
    return _port("generation")


def provider_config_port() -> Any:
    """供应商配置端口（实现 = core/provider_config.py）"""
    return _port("provider_config")


def task_log_port() -> Any:
    """生成日志面板端口（record_gate_gen_log；实现 = web 装配适配器）"""
    return _port("task_log")


def skill_docs_port() -> Any:
    """Skill 文档域端口（实现 = web/skill_docs.py）"""
    return _port("skill_docs")


def assets_port() -> Any:
    """本地素材库端口（iter_items 扫描；实现 = web/routes/assets_library.py）"""
    return _port("assets")


def task_stop_port() -> Any:
    """在途任务掐停端口（stop_bound_tasks；实现 = web/agent_task_manager.py）"""
    return _port("task_stop")


def canvas_online_cached() -> Optional[bool]:
    """画布健康探测缓存端口（不触发网络请求；planner 工具裁剪用）。

    依赖倒置：core 不再 import adapters.canvas_adapter，改经本端口读取。
    返回 None = 端口未装配或从未探测（调用方保持现状、不裁剪工具，
    与下沉前 `canvas_online_cached() is False 才裁剪` 语义一致）；
    True/False = 最近一次探测结果。实现经 web/port_wiring.install_core_ports
    注入（→ adapters.canvas_adapter.canvas_online_cached）。
    """
    port = _PORTS.get("canvas")
    if port is None:
        return None
    return port.online_cached()
