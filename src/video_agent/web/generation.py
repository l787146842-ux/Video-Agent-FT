"""供应商调用管线 re-export 承重壳。

实现按职责切分为三段（对外符号不变）：
- `web/generation_dispatch.py`：端点解析 / Chat Completions / 生图供应商
  路由 / 同模型跨厂商降级判定；
- `web/generation_channel.py`：BoundedChannel 有界并发三件套
  （信号量 + 429 退避 + 连败熔断）与 image/video/audio 三通道；
- `web/generation_submit.py`：生图/生视频统一提交管线、任务等待与
  分镜视频参考素材收集。

本壳仅为存量消费方（routes/、tools/、eval/、core 端口装配 port_wiring、
测试夹具）保留既有导入路径 `src.video_agent.web.generation`。
"""
import asyncio  # noqa: F401  # 测试经 gen_mod.asyncio 打桩，保留模块属性

from src.video_agent.web.generation_dispatch import (  # noqa: F401
    _IMAGE_1K_SIZES,
    _RESOLUTION_MULTIPLIERS,
    _try_canvas_image_generation,
    call_chat_completion,
    call_chat_completion_stream,
    generate_image_via_provider,
    image_size_for,
    resolve_openai_endpoint,
    resolve_openai_endpoint_async,
)
from src.video_agent.web.generation_channel import (  # noqa: F401
    AUDIO_CIRCUIT_ERROR,
    IMAGE_CIRCUIT_ERROR,
    VIDEO_CIRCUIT_ERROR,
    BoundedChannel,
    _gen_image_throttled,
    audio_channel,
    bounded_gather,
    image_channel,
    image_circuit_open,
    video_channel,
)
from src.video_agent.web.generation_submit import (  # noqa: F401
    _AUDIO_URL_EXTS,
    collect_shot_video_refs,
    is_audio_url,
    submit_image_task,
    submit_video_task,
    wait_image_task,
)
# 存量消费方经本模块转引的邻居符号（保持导入路径兼容）
from src.video_agent.web.task_manager import get_task_manager  # noqa: F401
from src.video_agent.core.provider_config import (  # noqa: F401
    resolve_provider_ref,
    resolve_provider_ref_async,
)
