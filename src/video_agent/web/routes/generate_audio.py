"""/api/generate/audio — 音频生成端点（音色设计 / 语音合成 / 背景音乐 / 音效）。

与图片/视频同构：提交即返回 task_id，后台任务完成经 SSE + 生成日志闭环，
最后由 task_manager.writeback_if_complete 回写草稿 audioUrl（音色设计额外回写 voiceId）。

原则：
- 未配置供应商/模型 → 明确报错（不猜、不静默换模型）；
- 供应商失败 → 真实错误上抛（含 HTTP 状态），绝不回退假音频。
"""
import time

from fastapi import APIRouter

from loguru import logger

from src.video_agent.core.audio_channels import AUDIO_CHANNELS
from src.video_agent.exceptions import GenerationError, VideoAgentError
from src.video_agent.utils import gen_id
from src.video_agent.web.error_payload import LEGACY_VALIDATION_ERROR
from src.video_agent.web.generation_audio import (
    clone_voice_via_provider,
    generate_audio_via_provider,
    list_voices_via_provider,
)

from .generate_common import (
    AudioGenRequest,
    VoiceCloneRequest,
    _new_task,
    _notify_sse,
    _tm,
    _track_task,
    _writeback_if_complete,
    poll_task,
)

router = APIRouter()


@router.post("/generate/audio")
async def generate_audio(body: AudioGenRequest):
    """提交音频生成任务（真实供应商，失败如实报错）。"""
    channel = (body.channel or "").strip()
    if channel not in AUDIO_CHANNELS:
        raise VideoAgentError(
            f"未知音频通道 '{channel}'（合法值：{'/'.join(AUDIO_CHANNELS)}）",
            status_code=400, error_code=LEGACY_VALIDATION_ERROR)
    if not (body.provider_id or "").strip():
        raise VideoAgentError(
            "尚未配置音频供应商，请先到「设置」中配置音频模型",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")
    if not (body.model or "").strip():
        raise VideoAgentError(
            "尚未选择音频模型，请在参数栏选择后再生成",
            status_code=400, error_code=LEGACY_VALIDATION_ERROR)

    task_id = gen_id("aud")
    _new_task(
        task_id,
        status="processing",
        media_kind="audio",
        draft_id=body.draft_id,
        draft_type=body.draft_type,
        prompt=body.prompt,
        model=body.model,
        channel=channel,
        result=None,
    )

    async def _run_generation():
        t0 = time.monotonic()
        task = _tm.tasks.get(task_id)
        refs = [str(r.get("url") or "") for r in (body.references or []) if r.get("url")]
        try:
            payload = await generate_audio_via_provider(
                provider_id=body.provider_id,
                model=body.model,
                channel=channel,
                prompt=body.prompt,
                preview_text=body.preview_text,
                language=body.language,
                sample_rate=body.sample_rate,
                audio_format=body.audio_format,
                prefix=body.prefix,
                voice_id=body.voice_id,
                lyrics=body.lyrics,
                instrumental=body.instrumental,
                gender=body.gender,
                watermark=body.watermark,
                references=refs,
                channels=body.channels,
                volume=body.volume,
                rate=body.rate,
                speed=body.speed or None,
                pitch=body.pitch or None,
                emotion=body.emotion,
            )
            if task is None:
                return
            task["status"] = "succeeded"
            task["audio_url"] = payload["audio_url"]
            task["result"] = {
                "audio": payload["audio_url"],
                "voice_id": payload.get("voice_id", ""),
                "duration": payload.get("duration", 0.0),
            }
            task["elapsed"] = round(time.monotonic() - t0, 1)
            _writeback_if_complete(task_id)
            _notify_sse({
                "task_id": task_id, "status": "succeeded", "kind": "audio",
                "draft_id": body.draft_id, "result": task["result"],
                "elapsed": task["elapsed"],
            })
            _tm.record_gen_log(
                media_type="audio", status="succeeded", provider=body.provider_id,
                model=body.model, prompt=body.prompt, draft_id=body.draft_id,
                result_url=payload["audio_url"], elapsed=task["elapsed"],
                requested_size=channel, source="manual", task_id=task_id,
            )
            logger.info(
                f"[Generate] 音频生成成功({channel}, {task['elapsed']}s): "
                f"{payload['audio_url'][:80]}")
        except GenerationError as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = str(e)
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({
                    "task_id": task_id, "status": "failed", "kind": "audio",
                    "draft_id": body.draft_id, "error": str(e),
                    "elapsed": task["elapsed"],
                })
                _tm.record_gen_log(
                    media_type="audio", status="failed", provider=body.provider_id,
                    model=body.model, prompt=body.prompt, draft_id=body.draft_id,
                    error=str(e), elapsed=task["elapsed"], requested_size=channel,
                    source="manual", task_id=task_id,
                )
            logger.warning(f"[Generate] 音频生成失败({channel}): {e}")
        except Exception as e:  # 兜底：保证任务终态闭环，不把卡片挂在「生成中」
            if task is not None:
                task["status"] = "failed"
                task["error"] = f"服务端异常: {e}"
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({
                    "task_id": task_id, "status": "failed", "kind": "audio",
                    "draft_id": body.draft_id, "error": task["error"],
                    "elapsed": task["elapsed"],
                })
                _tm.record_gen_log(
                    media_type="audio", status="failed", provider=body.provider_id,
                    model=body.model, prompt=body.prompt, draft_id=body.draft_id,
                    error=task["error"], elapsed=task["elapsed"],
                    requested_size=channel, source="manual", task_id=task_id,
                )
            logger.exception(f"[Generate] 音频生成异常({channel}): {e}")

    _tm.record_gen_log(
        media_type="audio", status="started", provider=body.provider_id,
        model=body.model, prompt=body.prompt, draft_id=body.draft_id,
        requested_size=channel, source="manual", task_id=task_id,
    )
    _notify_sse({
        "task_id": task_id, "status": "started", "kind": "audio",
        "draft_id": body.draft_id,
    })
    _track_task(_run_generation())
    return {"task_id": task_id, "status": "processing"}


@router.get("/generate/audio/{task_id}")
async def poll_audio_task(task_id: str):
    """轮询音频生成任务状态"""
    return await poll_task(task_id)


@router.get("/audio/voices")
async def list_voices(provider_id: str = "", model: str = ""):
    """拉取平台账号下的音色清单（选择 + 试听）；不支持列表的供应商明确报错。"""
    if not provider_id.strip():
        raise VideoAgentError(
            "尚未选择音频供应商，请先在参数栏选择",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")
    if not model.strip():
        raise VideoAgentError(
            "尚未选择语音合成模型（音色列表与合成模型绑定）",
            status_code=400, error_code=LEGACY_VALIDATION_ERROR)
    try:
        return {"voices": await list_voices_via_provider(
            provider_id=provider_id.strip(), model=model.strip())}
    except GenerationError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code="VOICE_LIST_FAILED") from e


@router.post("/audio/voices")
async def clone_voice(body: VoiceCloneRequest):
    """上传参考音频创建音色（声音复刻），同步返回 voice_id + 试听音频。

    不走生成任务队列：语音合成参数栏上传后立即回填音色 ID，用户再点合成。
    """
    if not (body.provider_id or "").strip():
        raise VideoAgentError(
            "尚未选择音频供应商，请先在参数栏选择",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")
    if not (body.target_model or "").strip():
        raise VideoAgentError(
            "尚未选择语音合成模型（音色需要与合成模型绑定）",
            status_code=400, error_code=LEGACY_VALIDATION_ERROR)
    if not (body.audio_url or "").strip():
        raise VideoAgentError(
            "请先上传参考音频（mp3/wav/m4a 等）",
            status_code=400, error_code=LEGACY_VALIDATION_ERROR)
    try:
        return await clone_voice_via_provider(
            provider_id=body.provider_id,
            target_model=body.target_model,
            audio_url=body.audio_url,
            preview_text=body.preview_text,
            language=body.language,
        )
    except GenerationError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code="VOICE_CLONE_FAILED") from e
