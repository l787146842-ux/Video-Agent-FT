"""core 端口装配（依赖倒置：web 层提供实现，装配点注入 core 端口）。

core 层不得 import web 层；本模块是唯一的「web → core 端口」接线处。
装配点：web/app.py lifespan / tests/conftest.py / scripts/run_eval_pipeline.py。
幂等：重复调用仅覆盖既有端口，无副作用。
provider_config 端口实现位于 core/provider_config.py
（批次E：web 层同名薄壳已清偿删除），仍由本装配点统一注入。
"""
from src.video_agent.core import ports, provider_config
from src.video_agent.web import generation, skill_docs
from src.video_agent.web.task_manager import get_task_manager


class _TaskLogPort:
    """闸机拦截 → 生成日志面板（web/task_manager 单例）。

    core/fc_tool_runner 以 (prompt, hard_errors) 调用；记录失败由调用方
    吞掉（不阻断主链路，与下沉前语义一致）。"""

    def record_gate_gen_log(self, prompt: str, hard_errors) -> None:
        get_task_manager().record_gen_log(
            media_type="prompt", status="failed", prompt=prompt,
            error="; ".join(hard_errors), source="agent",
        )


def install_core_ports() -> None:
    """把 web 层实现注入 core 端口注册表（幂等）。"""
    ports.install_ports(
        generation=generation,
        provider_config=provider_config,
        skill_docs=skill_docs,
        task_log=_TaskLogPort(),
    )
