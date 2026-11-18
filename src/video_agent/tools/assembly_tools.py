"""组装导出 Tool — video_assembler。

把故事板里已生成的镜头视频按顺序合成为成片（ffmpeg），落盘到
workspace/assets/，写《成片组装方案》（Final_Assembly_Plan.md），
并把成片作为 video 节点推送到 infinite-canvas。

边界：
- 只消费已存在的镜头视频；任何镜头缺 videoUrl 即 fail-closed（不带缺口组装）。
- 合成在本项目进程内完成（ffmpeg 经 FFMPEG_PATH / PATH / imageio-ffmpeg 解析），
  画布只承担「成片节点落位」，不承担合成（画布工具闭集无导出能力）。
- 方案文档经 DocumentWriteTool 唯一写入口落盘，探针据此判 assembly 完成。
"""
import asyncio
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger
from pydantic import Field

try:  # 可选依赖：自带跨平台 ffmpeg 二进制；未装时回落 PATH/FFMPEG_PATH
    import imageio_ffmpeg  # type: ignore
except Exception:  # noqa: BLE001
    imageio_ffmpeg = None  # type: ignore

from src.video_agent.adapters.canvas_adapter import get_canvas_adapter
from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import ASSEMBLY_PLAN_DOC_NAME, CAT_SHOTS
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.tools.document_tools import (
    DocumentWriteTool, WriteDocumentInput,
)
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import ASSETS_DIR

_ASSETS_PREFIX = "/workspace/assets/"
_MAX_REMOTE_BYTES = 512 * 1024 * 1024
_FFMPEG_TIMEOUT = 900  # 单段/拼接单步上限（秒）
_PROBE_TIMEOUT = 60


class VideoAssemblerInput(StrictToolInput):
    shot_ids: List[str] = Field(
        default_factory=list,
        description="要组装的分镜草稿 id 列表，顺序即成片顺序；留空 = 按故事板"
        "全部镜头顺序（组序 → 卡序）。只接受已有视频的镜头。",
    )
    filename: str = Field(
        "", description="成片文件名（默认 assembled-<时间戳>.mp4，落在 workspace/assets/）")
    push_to_canvas: bool = Field(
        True, description="合成后是否把成片作为视频节点放到画布")
    canvas_id: str = Field(
        "", description="目标画布 ID；留空 = 当前活跃画布（画布离线时只落盘不推送）")
    bgm_url: str = Field(
        "", description="可选：整片背景音 URL（/workspace/assets/... 或 http(s)）；"
        "留空 = 只保留各镜头原声")
    bgm_volume: float = Field(
        0.6, ge=0.0, le=2.0, description="背景音音量系数（默认 0.6）")


class VideoAssemblerTool(BaseTool):
    name = "video_assembler"
    risk = "medium"  # 写产物与画布节点；成片可重新生成，不花钱
    detail_tier = "expand"
    description = (
        "组装导出：把故事板镜头视频按顺序合成为成片，写入《成片组装方案》"
        "（Final_Assembly_Plan.md），并把成片作为视频节点推到画布。"
        "调用前确认所有目标镜头都已有视频；任一镜头缺视频会整体拒收并列出缺失项。"
    )

    def get_input_schema(self):
        return VideoAssemblerInput

    async def aexecute(self, params: VideoAssemblerInput) -> ToolResult:
        svc = StateManager.get_instance()
        state = svc.state_dict

        clips, missing = _collect_clips(state, params.shot_ids)
        if missing:
            return ToolResult(
                success=False,
                error=(
                    "组装未执行：以下镜头还没有视频（不带缺口组装）："
                    + "、".join(missing[:20])
                    + ("……" if len(missing) > 20 else "")
                    + "。请先为这些镜头生成视频，或改用 shot_ids 只组装已就绪的镜头。"
                ),
                error_code="validation", retryable=False,
            )
        if not clips:
            return ToolResult(
                success=False,
                error="组装未执行：故事板里没有可用的镜头视频（先生成分镜视频）。",
                error_code="validation", retryable=False,
            )

        ffmpeg = _ffmpeg_exe()
        if not ffmpeg:
            return ToolResult(
                success=False,
                error=(
                    "组装未执行：未找到 ffmpeg。请安装 ffmpeg 并加入 PATH / 设置 FFMPEG_PATH，"
                    "或执行 pip install imageio-ffmpeg（自带 ffmpeg 二进制）后重启服务。"
                ),
                error_code="other", retryable=False,
            )

        filename = _safe_filename(
            params.filename.strip() or f"assembled-{int(time.time())}.mp4")
        output_path = ASSETS_DIR / filename
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

        # 1) 媒体本地化（/workspace/assets 直接读盘；远程下载到临时目录）
        tmpdir = Path(tempfile.mkdtemp(prefix="video_assembler_"))
        try:
            sources: List[Path] = []
            for clip in clips:
                path = await _resolve_source(clip["url"], tmpdir)
                if path is None:
                    return ToolResult(
                        success=False,
                        error=(
                            f"组装未执行：镜头「{clip['label']}」的视频不可读取"
                            f"（{clip['url']}）。请确认素材仍存在（远程链接需可下载）。"
                        ),
                        error_code="validation", retryable=False,
                    )
                sources.append(path)

            bgm_path: Optional[Path] = None
            if params.bgm_url.strip():
                bgm_path = await _resolve_source(params.bgm_url.strip(), tmpdir)
                if bgm_path is None:
                    return ToolResult(
                        success=False,
                        error=f"组装未执行：背景音不可读取（{params.bgm_url}）。",
                        error_code="validation", retryable=False,
                    )

            # 2) 合成（阻塞操作走线程，避免卡事件循环）
            try:
                total = await asyncio.to_thread(
                    _compose, ffmpeg, sources, output_path,
                    bgm_path, float(params.bgm_volume),
                )
            except _FFmpegError as exc:
                return ToolResult(
                    success=False, error=f"组装失败：{exc}", error_code="upstream",
                    retryable=False,
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        video_url = f"{_ASSETS_PREFIX}{filename}"

        # 3) 方案文档（唯一写入口 = DocumentWriteTool，探针据此判 assembly 完成）
        plan = _render_plan(filename, video_url, clips, total, params.bgm_url.strip())
        save_res = await DocumentWriteTool().aexecute(
            WriteDocumentInput(name=ASSEMBLY_PLAN_DOC_NAME, content=plan))
        if not save_res.success:
            return ToolResult(
                success=False,
                error=f"成片已合成（{video_url}），但《成片组装方案》落盘失败："
                f"{save_res.error}",
                error_code="other", retryable=False,
            )

        # 4) 成片落画布（视频节点；失败不推翻成片，只如实告知）
        canvas_note = "未推送画布（本次未请求）"
        canvas_id = ""
        node_id = ""
        if params.push_to_canvas:
            canvas_id, node_id, canvas_note = await _push_to_canvas(
                params.canvas_id.strip(), video_url, filename)

        total_shots = sum(
            len(g.get("drafts") or []) for g in (state.get(CAT_SHOTS) or [])
            if isinstance(g, dict))
        detail = (
            f"成片已生成：{filename}（{len(clips)} 个镜头，约 {total:.1f}s）"
            f"；{canvas_note}"
        )
        if total_shots and len(clips) < total_shots:
            # 平台偏差必须模型可见：子集组装不满足 assembly 阶段完成判据
            detail += (
                f"；本次只组装 {len(clips)}/{total_shots} 个镜头，"
                "组装阶段完成判据仍要求全部镜头就绪")
        return ToolResult(success=True, data={
            "url": video_url,
            "name": filename,
            "duration_seconds": round(total, 2),
            "clips": len(clips),
            "plan_doc": ASSEMBLY_PLAN_DOC_NAME,
            "canvas_id": canvas_id,
            "canvas_node_id": node_id,
            "chat_inserts": [{
                "kind": "video", "url": video_url, "name": filename, "thumb": "",
            }],
            "detail": detail,
        })


# ---------- 镜头收集 ----------


def _collect_clips(
    state: Dict[str, Any], shot_ids: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    """返回 (按成片顺序的镜头, 缺失视频的镜头说明)。"""
    clips: List[Dict[str, str]] = []
    missing: List[str] = []
    wanted = [str(x).strip() for x in (shot_ids or []) if str(x).strip()]
    if wanted:
        for did in wanted:
            hit = ops.find_draft(state, did)
            if hit is None:
                missing.append(f"{did}（未找到该草稿）")
                continue
            _group, draft = hit
            label = str(draft.get("label") or did)
            url = str(draft.get("videoUrl") or "").strip()
            if not url:
                missing.append(f"{label}（{did}）")
                continue
            clips.append({"draft_id": did, "label": label, "url": url})
        return clips, missing

    for group in state.get(CAT_SHOTS) or []:
        if not isinstance(group, dict):
            continue
        for draft in group.get("drafts") or []:
            if not isinstance(draft, dict):
                continue
            label = str(draft.get("label") or draft.get("id") or "未命名镜头")
            url = str(draft.get("videoUrl") or "").strip()
            if not url:
                missing.append(label)
                continue
            clips.append({
                "draft_id": str(draft.get("id") or ""),
                "label": label,
                "url": url,
            })
    return clips, missing


# ---------- 媒体与 ffmpeg ----------


def _ffmpeg_exe() -> str:
    configured = str(getattr(settings, "ffmpeg_path", "") or "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        if imageio_ffmpeg is not None:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).is_file():
                return exe
    except Exception as exc:  # noqa: BLE001 - 缺依赖即回落结构化错误
        logger.debug("[video_assembler] imageio-ffmpeg 不可用: {}", exc)
    return ""


def _safe_filename(name: str) -> str:
    raw = Path(str(name or "").strip()).name
    stem = "".join(ch for ch in Path(raw).stem if ch.isalnum() or ch in "-_") or "assembled"
    suffix = Path(raw).suffix.lower() if raw else ""
    if suffix not in (".mp4",):
        suffix = ".mp4"
    return f"{stem}{suffix}"


def _local_asset(url: str) -> Optional[Path]:
    """把 /workspace/assets/... 或本机同源 URL 映射到本地文件（防目录穿越）。"""
    raw = str(url or "").strip()
    if not raw:
        return None
    path = urlparse(raw).path if "://" in raw else raw
    if not path.startswith(_ASSETS_PREFIX):
        return None
    rel = unquote(path[len(_ASSETS_PREFIX):]).split("?")[0]
    name = Path(rel).name
    if not name:
        return None
    p = (ASSETS_DIR / name).resolve()
    try:
        p.relative_to(ASSETS_DIR.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


async def _resolve_source(url: str, tmpdir: Path) -> Optional[Path]:
    local = _local_asset(url)
    if local is not None:
        return local
    if not url.lower().startswith(("http://", "https://")):
        return None
    target = tmpdir / f"src-{int(time.time() * 1000)}-{gen_id('m', wide=False)}.bin"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                total = 0
                with target.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_REMOTE_BYTES:
                            return None
                        fh.write(chunk)
        return target if target.is_file() and target.stat().st_size > 0 else None
    except Exception as exc:  # noqa: BLE001 - 远程素材不可读即结构化失败
        logger.warning("[video_assembler] 素材下载失败 {}: {}", url, exc)
        return None


class _FFmpegError(RuntimeError):
    pass


def _run(cmd: List[str], timeout: int = _FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise _FFmpegError((proc.stderr or proc.stdout or "ffmpeg 执行失败").strip()[:600])
    return proc


def _probe_duration(exe: str, path: Path) -> float:
    """解析 ffmpeg -i 输出的 Duration（无 ffprobe 依赖）。"""
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def _has_audio(exe: str, path: Path) -> bool:
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001
        return False
    return "Audio:" in (proc.stderr or "")


def _compose(
    exe: str,
    sources: List[Path],
    output: Path,
    bgm: Optional[Path],
    bgm_volume: float,
) -> float:
    """逐段归一化编码 → concat 拼接 →（可选）叠 BGM。返回总时长（秒）。"""
    tmpdir = Path(tempfile.mkdtemp(prefix="va_parts_"))
    try:
        parts: List[Path] = []
        for index, src in enumerate(sources):
            part = tmpdir / f"part_{index:03d}.mp4"
            cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
            if _has_audio(exe, src):
                cmd += ["-map", "0:v:0", "-map", "0:a:0"]
            else:
                cmd += [
                    "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                ]
            cmd += [
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(part),
            ]
            _run(cmd)
            parts.append(part)

        concat_file = tmpdir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        _run([
            exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(output),
        ])

        if bgm is not None:
            mixed = tmpdir / "mixed.mp4"
            _run([
                exe, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(output), "-stream_loop", "-1", "-i", str(bgm),
                "-filter_complex",
                f"[1:a]volume={bgm_volume:.2f}[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v:0", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(mixed),
            ])
            mixed.replace(output)

        duration = _probe_duration(exe, output)
        if duration <= 0:
            # 时长拿不到不阻断成片（文件已产出），仅记日志
            logger.warning("[video_assembler] 成片时长探测失败: {}", output)
        return duration
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------- 画布 ----------


async def _push_to_canvas(
    canvas_id: str, video_url: str, filename: str,
) -> Tuple[str, str, str]:
    """把成片作为 video 节点推到画布。返回 (canvas_id, node_id, 说明)。"""
    if not settings.canvas_enabled:
        return "", "", "未推送画布（画布功能未启用）"
    try:
        adapter = get_canvas_adapter()
        cid = canvas_id
        if not cid:
            target = await adapter.find_active_canvas()
            if not target:
                return "", "", "未推送画布（未找到活跃画布，成片已落盘）"
            cid = str(target.get("id") or "")
        res = await adapter.add_video_node(cid, url=video_url, name=filename)
        return cid, str(res.get("node_id") or ""), "成片已作为视频节点放到画布"
    except Exception as exc:  # noqa: BLE001 - 画布失败不推翻成片
        logger.warning("[video_assembler] 画布推送失败: {}", exc)
        return "", "", f"画布推送失败（成片已落盘）：{exc}"


def _render_plan(
    filename: str, video_url: str, clips: List[Dict[str, str]],
    total: float, bgm_url: str,
) -> str:
    lines = [
        "# 成片组装方案",
        "",
        f"- 成片文件：`{filename}`",
        f"- 成片地址：{video_url}",
        f"- 总时长：约 {total:.1f} 秒",
        f"- 镜头数：{len(clips)}",
        f"- 背景音：{bgm_url or '无（仅各镜头原声）'}",
        "",
        "## 时间轴（按成片顺序）",
        "",
        "| 序号 | 镜头 | 草稿 | 视频 |",
        "|---|---|---|---|",
    ]
    for index, clip in enumerate(clips, 1):
        lines.append(
            f"| {index} | {clip['label']} | `{clip['draft_id']}` | {clip['url']} |")
    lines += [
        "",
        "## 交付说明",
        "",
        "- 各段按故事板镜头顺序归一化（1280×720 / 30fps / AAC 48k 立体声）后拼接。",
        "- 无原声的镜头补静音轨，保证成片音轨连续。",
        "- 成片已写入本地素材库；请求推送时同一文件作为 video 节点落在画布。",
        "",
    ]
    return "\n".join(lines)


def register_assembly_tools() -> None:
    """注册组装导出工具（启动时调用，与其它工具注册同口径）。"""
    ToolManager.register(VideoAssemblerTool())
    logger.info("[Tools] 1 assembly tool registered (video_assembler)")
