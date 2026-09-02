"""/api/generate 图片生成端点。

原则：
- 未配置供应商 → 明确报错（演示兜底已删除）；
- 真实供应商失败 → 返回真实错误（HTTP 4xx/5xx + detail），绝不回退假图。
"""
import time
from typing import Dict, List

from fastapi import APIRouter

from loguru import logger

from src.video_agent.exceptions import GenerationError, VideoAgentError
from src.video_agent.web.error_payload import LEGACY_VALIDATION_ERROR
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, ALL_CATEGORIES_TUPLE
from src.video_agent.utils import gen_id
from src.video_agent.web.generation import generate_image_via_provider, image_size_for

from .generate_common import (
    ImageGenRequest,
    BatchImageGenRequest,
    _new_task,
    _notify_sse,
    _tm,
    _track_task,
    _writeback_if_complete,
    poll_task,
)

router = APIRouter()


@router.post("/generate/image")
@router.post("/canvas-image-tasks")
async def generate_image(body: ImageGenRequest):
    """
    提交图片生成任务。
    真实供应商：OpenAI 兼容 /images/generations，失败回退 chat 生图；再失败 → 报错。
    未配置供应商：明确报错。
    """
    if not body.prompt.strip():
        raise VideoAgentError(
            "提示词不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )

    # 空供应商：明确报错（不再有演示兜底）
    if not (body.provider_id or "").strip():
        raise VideoAgentError(
            "尚未配置生成供应商，请先到「设置」中配置生成供应商",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")

    # ---------- 真实供应商：异步任务（立即返回 task_id，前端轮询进度与耗时） ----------
    task_id = gen_id("img")
    _new_task(
        task_id,
        status="processing",
        draft_id=body.draft_id,
        draft_type=body.draft_type,
        prompt=body.prompt,
        model=body.model,
        result=None,
    )

    async def _run_generation():
        t0 = time.monotonic()
        task = _tm.tasks.get(task_id)
        # 提取参考素材 URL（@ 引用的素材），随请求发送给多模态模型
        ref_urls = [r.get("url", "") for r in (body.reference_images or []) if r.get("url")]
        try:
            image_url = await generate_image_via_provider(
                body.provider_id,
                body.model,
                body.prompt,
                size=body.size or "1024x1024",
                aspect_ratio=body.aspect_ratio,
                resolution=body.resolution,
                reference_images=ref_urls,
            )
            if task is None:
                return
            task["status"] = "succeeded"
            task["result"] = {"images": [image_url]}
            task["elapsed"] = round(time.monotonic() - t0, 1)
            _writeback_if_complete(task_id)
            _notify_sse({"task_id": task_id, "status": "succeeded", "kind": "image",
                         "draft_id": body.draft_id, "result": task["result"], "elapsed": task["elapsed"]})
            _tm.record_gen_log(
                media_type="image", status="succeeded", provider=body.provider_id, model=body.model,
                prompt=body.prompt, draft_id=body.draft_id, result_url=image_url,
                elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                task_id=task_id,
            )
            logger.info(f"[Generate] 图片生成成功({task['elapsed']}s): {image_url[:80]}")
        except GenerationError as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = str(e)
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({"task_id": task_id, "status": "failed", "kind": "image",
                             "draft_id": body.draft_id, "error": str(e), "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="image", status="failed", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, error=str(e),
                    elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                    task_id=task_id,
                )
            logger.warning(f"[Generate] 图片生成失败: {e}")
        except Exception as e:
            if task is not None:
                task["status"] = "failed"
                task["error"] = f"服务端异常: {e}"
                task["elapsed"] = round(time.monotonic() - t0, 1)
                _notify_sse({"task_id": task_id, "status": "failed", "kind": "image",
                             "draft_id": body.draft_id, "error": str(e), "elapsed": task["elapsed"]})
                _tm.record_gen_log(
                    media_type="image", status="failed", provider=body.provider_id, model=body.model,
                    prompt=body.prompt, draft_id=body.draft_id, error=str(e),
                    elapsed=task["elapsed"], requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
                    task_id=task_id,
                )
            logger.exception(f"[Generate] 图片生成异常: {e}")

    # 生成日志：提交即记录 started；SSE 同步通知前端点亮转圈
    _tm.record_gen_log(
        media_type="image", status="started", provider=body.provider_id, model=body.model,
        prompt=body.prompt, draft_id=body.draft_id,
        requested_size=f"{body.size} ({body.aspect_ratio})", source="manual",
        task_id=task_id,
    )
    _notify_sse({"task_id": task_id, "status": "started", "kind": "image", "draft_id": body.draft_id})
    _track_task(_run_generation())
    return {"task_id": task_id, "status": "processing"}


@router.get("/generate/image/{task_id}")
@router.get("/canvas-image-tasks/{task_id}")
async def poll_image_task(task_id: str):
    """轮询图片生成任务状态"""
    return await poll_task(task_id)


@router.post("/generate/batch-image")
async def batch_generate_image(body: BatchImageGenRequest):
    """批量提交图片生成（仅服务前端“批量生成”按钮：人发起=已同意，不设闸）。

    Agent/模型发起的批量出图不走本路由，而是走 image_generate 工具
    （fc_tool_runner 闸机链 → generation_submit.submit_image_task）并经确认闸。"""
    svc = StateManager.get_instance()
    state = svc.state_dict

    # 确定目标 drafts
    targets: List[tuple] = []  # (group, draft)
    if body.target in ("all_keyElements", "all_keyelements"):
        for g in state.get(CAT_KEY_ELEMENTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append((g, d))
    elif body.target in ("all_shots", "all_shot"):
        for g in state.get(CAT_SHOTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append((g, d))
    else:
        # 逗号分隔的 draft_id
        ids = [x.strip() for x in body.target.split(",") if x.strip()]
        for cat in ALL_CATEGORIES_TUPLE:
            for g in state.get(cat, []):
                for d in g.get("drafts", []):
                    if d.get("id") in ids and (d.get("prompt") or "").strip():
                        targets.append((g, d))

    if not targets:
        return {"task_ids": [], "count": 0, "detail": "未找到有提示词的草稿"}

    if not (body.provider_id or "").strip():
        raise VideoAgentError(
            "尚未配置生成供应商，请先到「设置」中配置生成供应商",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")

    task_ids: List[str] = []
    for group, draft in targets:
        # 自动注入 sceneRefs 参考图
        refs: List[Dict[str, str]] = []
        for ref_title in (group.get("sceneRefs") or []):
            for ke in state.get(CAT_KEY_ELEMENTS, []):
                if ke.get("title") == ref_title:
                    for kd in ke.get("drafts", []):
                        if kd.get("imgUrl"):
                            refs.append({"url": kd["imgUrl"], "role": "reference"})
                            break
                    break

        task_id = gen_id("img")
        _new_task(
            task_id,
            status="processing",
            draft_id=draft.get("id", ""),
            draft_type="shot" if group in state.get(CAT_SHOTS, []) else "keyElement",
            prompt=draft.get("prompt", ""),
            model=body.model,
            result=None,
        )
        task_ids.append(task_id)
        draft["tag"] = "生成中"

        # 异步执行
        prompt_text = draft["prompt"]
        provider_id = body.provider_id
        model_name = body.model
        # 按草稿自身 比例 + 分辨率档位 计算尺寸（缺失时回退请求参数）
        aspect_ratio = (draft.get("aspectRatio") or "").strip() or body.aspect_ratio
        resolution = (draft.get("imageResolution") or "").strip().upper()
        if resolution not in ("1K", "2K", "4K"):
            resolution = "1K"
        size = image_size_for(aspect_ratio, resolution)
        size_note = f"{size} ({aspect_ratio}, {resolution})"

        async def _run(tid=task_id, p=prompt_text, pid=provider_id, m=model_name, s=size, ar=aspect_ratio, res=resolution, sn=size_note, did=draft.get("id", "")):
            t0 = time.monotonic()
            task = _tm.tasks.get(tid)
            try:
                url = await generate_image_via_provider(pid, m, p, size=s, aspect_ratio=ar, resolution=res)
                if task:
                    task["status"] = "succeeded"
                    task["result"] = {"images": [url]}
                    task["elapsed"] = round(time.monotonic() - t0, 1)
                    _writeback_if_complete(tid)
                    _notify_sse({"task_id": tid, "status": "succeeded", "kind": "image",
                                 "draft_id": did, "result": {"images": [url]}, "elapsed": task["elapsed"]})
                    _tm.record_gen_log(
                        media_type="image", status="succeeded", provider=pid, model=m, prompt=p,
                        draft_id=did, result_url=url, elapsed=task["elapsed"],
                        requested_size=sn, source="batch",
                        task_id=tid,
                    )
            except Exception as e:  # 统一兜底（GenerationError 是 Exception 子类），保证任务状态闭环
                if task:
                    task["status"] = "failed"
                    task["error"] = str(e)
                    task["elapsed"] = round(time.monotonic() - t0, 1)
                    _notify_sse({"task_id": tid, "status": "failed", "kind": "image",
                                 "draft_id": did, "error": str(e), "elapsed": task["elapsed"]})
                    _tm.record_gen_log(
                        media_type="image", status="failed", provider=pid, model=m, prompt=p,
                        draft_id=did, error=str(e), elapsed=task["elapsed"],
                        requested_size=sn, source="batch",
                        task_id=tid,
                    )

        # 批量提交即记录 started 并通知前端点亮转圈
        _tm.record_gen_log(
            media_type="image", status="started", provider=provider_id, model=model_name,
            prompt=prompt_text, draft_id=draft.get("id", ""),
            requested_size=size_note, source="batch",
            task_id=task_id,
        )
        _notify_sse({"task_id": task_id, "status": "started", "kind": "image", "draft_id": draft.get("id", "")})
        _track_task(_run())

    svc.save()
    return {"task_ids": task_ids, "count": len(task_ids)}
