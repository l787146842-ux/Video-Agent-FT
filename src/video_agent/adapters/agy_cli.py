"""
Antigravity CLI (agy) Adapter — 通过本机 agy CLI 调用 Gemini 生图。
"""
import asyncio
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


class AgyCliImageAdapter(BaseImageAdapter):
    """通过 agy CLI 的 -p (print) 模式直接调用 Gemini 生图"""

    async def generate_image(
        self, prompt: str, reference_image: Optional[str] = None, **kwargs
    ) -> ImageGenerationResponse:
        aspect_ratio = kwargs.get("aspect_ratio", "")
        agy_path = shutil.which("agy")
        if not agy_path:
            raise AdapterError("agy CLI 未安装或不在 PATH 中")

        aspect_hint = f"，画面比例 {aspect_ratio}" if aspect_ratio and aspect_ratio != "1:1" else ""
        full_prompt = f"画一张图片：{prompt}{aspect_hint}"
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

        # 4. brain 目录新文件检测
        if brain_dir.exists():
            await asyncio.sleep(1)
            for f in brain_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    if str(f) not in pre_existing_files:
                        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                        dest = ASSETS_DIR / f"{gen_id('gen', wide=True)}{f.suffix}"
                        dest.write_bytes(f.read_bytes())
                        logger.info(f"[AgyCli] 新图片检测到: {f.name} -> {dest.name}")
                        return ImageGenerationResponse(
                            task_id=f"agy-{int(time.time())}", status="completed", image_urls=[f"/workspace/assets/{dest.name}"]
                        )

        raise AdapterError(f"agy CLI 未返回图片（输出前200字: {output[:200]}）")

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """agy CLI 是同步返回，不需要轮询"""
        return ImageGenerationResponse(task_id=task_id, status="completed", image_urls=[])
