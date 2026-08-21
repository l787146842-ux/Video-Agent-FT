"""
Antigravity CLI (agy) Adapter — 通过本机 agy CLI 调用 Gemini 生图。

与画布行为对齐：Antigravity CLI 使用本机 agy 登录态，生图走本机 CLI，不走反代。

双轨退役（ADR-0001）：CLI 聊天适配器（AgyCliChatAdapter）
已删除——非 FC 通道不再承载对话；CLI 三协议仅保留生图职能。
"""
import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from .base import BaseImageAdapter, ImageGenerationResponse
from src.video_agent.exceptions import AdapterError
from .openai_compat import extract_base64_image, persist_data_uri, _HTTP_IMAGE_RE
from src.video_agent.utils.paths import ASSETS_DIR
from src.video_agent.utils import gen_id


# ---------- agy 生图并发保护 ----------
# agy 生图共用同一本地登录会话与同一个 brain 产出目录，并发任务的
# 「新文件检测」会抢到同一张图片伪装成多份产出（竞态缺陷）。
# 串行化「基线扫描 → CLI 执行 → 新文件检测」全程；已认领文件集合作纵深防御。
_AGY_IMAGE_LOCK = asyncio.Lock()
_AGY_CLAIMED_FILES: set = set()


def _agy_executable() -> str:
    """定位 agy 可执行文件（PATH 优先，兼容画布的 AGY_BIN/ANTIGRAVITY_BIN 配置）"""
    for key in ("ANTIGRAVITY_BIN", "AGY_BIN", "GEMINI_BIN"):
        configured = os.getenv(key, "").strip().strip('"')
        if configured and Path(configured).exists():
            return configured
    return shutil.which("agy") or ""


class AgyCliImageAdapter(BaseImageAdapter):
    """通过 agy CLI 的 -p (print) 模式直接调用 Gemini 生图（全局串行，防新文件检测竞态）"""

    async def generate_image(
        self, prompt: str, reference_image: Optional[str] = None, **kwargs
    ) -> ImageGenerationResponse:
        async with _AGY_IMAGE_LOCK:
            return await self._generate_image_locked(
                prompt, aspect_ratio=kwargs.get("aspect_ratio", ""), resolution=kwargs.get("resolution", "")
            )

    async def _generate_image_locked(self, prompt: str, aspect_ratio: str = "", resolution: str = "") -> ImageGenerationResponse:
        agy_path = _agy_executable()
        if not agy_path:
            raise AdapterError("agy CLI 未安装或不在 PATH 中")

        aspect_hint = f"，画面比例 {aspect_ratio}" if aspect_ratio and aspect_ratio != "1:1" else ""
        # 分辨率档位写进提示词：agy CLI 无 size 参数，只能靠模型感知
        res_hint = f"，分辨率 {resolution}" if resolution and resolution.upper() in ("1K", "2K", "4K") else ""
        full_prompt = f"画一张图片：{prompt}{aspect_hint}{res_hint}"
        logger.info(f"[AgyCli] 生图: prompt={full_prompt[:80]}")

        # 记录调用前 brain 目录下的最新文件，用于检测新生成的文件
        brain_dir = Path.home() / ".gemini" / "antigravity-cli" / "brain"
        pre_existing_files: set = set()
        if brain_dir.exists():
            for f in brain_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    pre_existing_files.add(str(f))

        try:
            proc = await asyncio.create_subprocess_exec(
                agy_path, "-p", full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            raise AdapterError("agy CLI 生图超时（180s）")
        except OSError as e:
            raise AdapterError(f"agy CLI 启动失败: {e}")

        output = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace")[:300]
            raise AdapterError(f"agy CLI 返回错误 (code={proc.returncode}): {err_text}")

        if "暂时繁忙" in output or "容量已满" in output or "稍等" in output:
            raise AdapterError("agy CLI 图像生成服务暂时繁忙，请稍后重试")

        # 1. base64 图片
        img_data = extract_base64_image(output)
        if img_data:
            url = persist_data_uri(img_data)
            return ImageGenerationResponse(task_id=f"agy-{int(time.time())}", status="completed", image_urls=[url])

        # 2. HTTP URL
        url_match = _HTTP_IMAGE_RE.search(output)
        if url_match:
            return ImageGenerationResponse(
                task_id=f"agy-{int(time.time())}", status="completed", image_urls=[url_match.group(0)]
            )

        # 3. 文件路径
        file_path_re = re.compile(r"([A-Za-z]:\\[^\s\)\"]+\.(?:png|jpg|jpeg|webp))")
        file_match = file_path_re.search(output)
        if file_match:
            fpath = Path(file_match.group(1))
            if fpath.exists():
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                dest = ASSETS_DIR / f"{gen_id('gen', wide=True)}.{fpath.suffix.lstrip('.')}"
                dest.write_bytes(fpath.read_bytes())
                logger.info(f"[AgyCli] 图片已复制: {dest.name}")
                return ImageGenerationResponse(
                    task_id=f"agy-{int(time.time())}", status="completed", image_urls=[f"/workspace/assets/{dest.name}"]
                )

        # 4. brain 目录新文件检测（取最新产出且未被其他任务认领的文件）
        if brain_dir.exists():
            await asyncio.sleep(1)
            candidates = [
                f for f in brain_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                and str(f) not in pre_existing_files
                and str(f) not in _AGY_CLAIMED_FILES
            ]
            candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            for f in candidates:
                _AGY_CLAIMED_FILES.add(str(f))
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                dest = ASSETS_DIR / f"{gen_id('gen', wide=True)}{f.suffix}"
                dest.write_bytes(f.read_bytes())
                logger.info(f"[AgyCli] 新图片检测到: {f.name} -> {dest.name}")
                return ImageGenerationResponse(
                    task_id=f"agy-{int(time.time())}", status="completed", image_urls=[f"/workspace/assets/{dest.name}"]
                )

        # 未产出任何图片：直接透出 LLM 上游原始返回文本（如配额耗尽/限流的
        # 原始报错），不再包一层包装文案，便于前端生成日志直接展示
        upstream = (output or "").strip()
        if upstream:
            raise AdapterError(upstream[:500])
        raise AdapterError("agy CLI 未返回图片")

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """agy CLI 是同步返回，不需要轮询"""
        return ImageGenerationResponse(task_id=task_id, status="completed", image_urls=[])
