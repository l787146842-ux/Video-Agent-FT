"""
有界并发通道（任务#11 拆分清偿，2026-08-23：generation.py 三段之二）。

BoundedChannel 三件套：信号量 + 429 退避 + 连败熔断。
自生图单点节流抽为通用通道并推广到媒体生成族（P3-13）：
image/video/audio 三通道各自独立信号量与熔断台账，互不干扰。
有界并发只作用于「模型发起的执行器批内部」的供应商调用，
runtime 自身不发起生成（ADR-0004）。
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.exceptions import GenerationError
from src.video_agent.config import settings
# 模块属性引用（非 from-import 绑定）：测试 patch
# generation_dispatch.generate_image_via_provider 须在本调用点生效
from src.video_agent.web import generation_dispatch

IMAGE_CIRCUIT_ERROR = (
    "出图渠道连败熔断：上游持续限流/报错。请约 1 分钟后重试，"
    "或在 API 配置/规格文档更换出图渠道。"
)
VIDEO_CIRCUIT_ERROR = (
    "视频生成渠道连败熔断：上游持续限流/报错。请约 1 分钟后重试，"
    "或在 API 配置/规格文档更换生视频渠道。"
)
AUDIO_CIRCUIT_ERROR = (
    "音频生成渠道连败熔断：上游持续限流/报错。请约 1 分钟后重试，"
    "或在 API 配置/规格文档更换音频渠道。"
)


class BoundedChannel:
    """有界并发通道：asyncio 信号量 + 429 指数退避 + 连败熔断（参数化三件套）。

    参数：并发上限 / 退避基数（秒）/ 最大尝试次数 / 熔断阈值（连败次数）/ 冷却秒数。
    - 并发上限：信号量只包住供应商调用本体；退避等待不占并发位（先释放再 sleep）；
    - 429 退避：命中 429 按 backoff_base * (attempt+1) 递增退避重试，总尝试 max_attempts 次；
    - 连败熔断：同供应商连败 ≥ 阈值且 window 秒内 → 熔断开路，新调用直接报错
      （确定性拦截，防模型轮反复触发整批）；任一成功清零连败台账。
    """

    def __init__(
        self,
        name: str,
        concurrency: int,
        *,
        backoff_base: float = 5.0,
        max_attempts: int = 3,
        circuit_threshold: int = 6,
        circuit_window: float = 60.0,
        circuit_error: str = "",
    ) -> None:
        self.name = name
        self.concurrency = max(1, int(concurrency))
        self.backoff_base = float(backoff_base)
        self.max_attempts = max(1, int(max_attempts))
        self.circuit_threshold = int(circuit_threshold)
        self.circuit_window = float(circuit_window)
        self.circuit_error = circuit_error or (
            f"{name} 生成渠道连败熔断：上游持续限流/报错，请约 1 分钟后重试。"
        )
        self._sem: Optional[asyncio.Semaphore] = None
        self._fail_streak: Dict[str, Dict[str, float]] = {}

    # -- 熔断台账（按供应商独立记账） --

    def circuit_open(self, provider_id: str) -> bool:
        st = self._fail_streak.get(provider_id or "")
        return bool(
            st and st["n"] >= self.circuit_threshold
            and (time.time() - st["ts"]) < self.circuit_window
        )

    def check_circuit(self, provider_id: str) -> None:
        """熔断开路时新调用直接报错（确定性拦截）。"""
        if self.circuit_open(provider_id):
            raise GenerationError(self.circuit_error)

    def _record(self, provider_id: str, ok: bool) -> None:
        st = self._fail_streak.setdefault(provider_id or "", {"n": 0.0, "ts": 0.0})
        if ok:
            st["n"] = 0.0
        else:
            st["n"] += 1
            st["ts"] = time.time()

    def reset(self) -> None:
        """清空熔断台账（测试隔离/渠道人工恢复后用）。"""
        self._fail_streak.clear()

    # -- 有界执行 --

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

    async def run(self, provider_id: str, fn, *args, **kwargs):
        """经通道执行一次供应商调用：信号量节流 + 429 退避 + 熔断记账。

        fn 为异步可调用；熔断开路时立即抛 GenerationError（不占并发位）。
        """
        self.check_circuit(provider_id)
        last: Optional[Exception] = None
        for attempt in range(self.max_attempts):
            try:
                async with self._get_sem():
                    result = await fn(*args, **kwargs)
                self._record(provider_id, True)
                return result
            except Exception as e:
                last = e
                self._record(provider_id, False)
                if "429" in str(e) and attempt < self.max_attempts - 1:
                    wait = self.backoff_base * (attempt + 1)
                    logger.warning(
                        f"[Generation] {self.name} 生成 429 限流，退避 {wait:g}s 重试（{provider_id}）"
                    )
                    await asyncio.sleep(wait)  # 退避等待不占并发位（信号量已释放）
                    continue
                raise
        raise last or GenerationError(f"{self.name} 生成失败")


# 三通道独立信号量：image 保持现值 4 不回归；video 保守起步 2（单发成本高、
# 供应商并发配额小）；audio 同口径预留（当前版本无真实音频文件生成调用）。
image_channel = BoundedChannel(
    "image", settings.image_gen_concurrency,
    circuit_error=IMAGE_CIRCUIT_ERROR,
)
video_channel = BoundedChannel(
    "video", settings.video_gen_concurrency,
    circuit_error=VIDEO_CIRCUIT_ERROR,
)
audio_channel = BoundedChannel(
    "audio", settings.audio_gen_concurrency,
    circuit_error=AUDIO_CIRCUIT_ERROR,
)


async def bounded_gather(channel: BoundedChannel, jobs: List[Tuple[str, Any]]) -> List:
    """同批多目标经通道限流并发执行（asyncio.gather + 通道）。

    jobs：[(provider_id, 零参异步可调用)]；结果按索引对应，失败项为
    Exception 实例（return_exceptions，批内不连锁取消）。
    """
    return await asyncio.gather(
        *(channel.run(pid, fn) for pid, fn in jobs),
        return_exceptions=True,
    )


def image_circuit_open(provider_id: str) -> bool:
    return image_channel.circuit_open(provider_id)


async def _gen_image_throttled(
    pid: str, mdl: str, prompt: str, *, size: str,
    aspect_ratio: str, resolution: str, reference_images: Optional[List] = None,
) -> str:
    """并发节流 + 429 退避的生图调用（经 image 通道；退避等待不占并发位）。

    经模块属性引用 generation_dispatch.generate_image_via_provider，
    保证测试对该符号的 monkeypatch 在本调用点生效。
    """
    async def _call():
        return await generation_dispatch.generate_image_via_provider(
            pid, mdl, prompt, size=size, aspect_ratio=aspect_ratio,
            resolution=resolution, reference_images=reference_images,
        )
    return await image_channel.run(pid, _call)
