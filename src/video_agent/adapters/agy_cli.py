"""
Antigravity CLI (agy) Adapter — 通过本机 agy CLI 调用 Gemini 生图与聊天。

与画布行为对齐：Antigravity CLI 使用本机 agy 登录态，聊天与生图都走本机 CLI，
不走反代；model 为 "auto" 时不传 --model，由 agy 自行路由（既能聊天又能生图）。
"""
import asyncio
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from .base import BaseImageAdapter, ImageGenerationResponse
from .base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from .openai_compat import extract_base64_image, persist_data_uri, _HTTP_IMAGE_RE
from src.video_agent.utils.paths import ASSETS_DIR
from src.video_agent.utils import gen_id

# agy 繁忙/容量提示（与生图路径一致的降级检测）
_AGY_BUSY_MARKERS = ("暂时繁忙", "容量已满", "稍等")

# CLI 聊天历史回喂上限（对齐画布 MAX_HISTORY_MESSAGES 的取值思路）
_AGY_CHAT_HISTORY_LIMIT = 10

# 命令行参数长度保护：Windows CreateProcess 命令行上限约 32767 字符，
# 超限直接报 WinError 206（文件名或扩展名太长）。Planner 注入的工作台状态
# JSON + 聊天历史很容易超限，超过阈值时把 prompt 外置到临时文件，
# 命令行只传「读文件执行」的短指令（agy 具备本地文件读取能力，实测可用）
_AGY_PROMPT_ARG_LIMIT = 20000


def _externalize_prompt(prompt: str) -> tuple:
    """超长 prompt 外置到临时文件。返回 (实际传给 -p 的文本, 待清理文件路径或 None)"""
    if len(prompt) <= _AGY_PROMPT_ARG_LIMIT:
        return prompt, None
    tmp_dir = Path(tempfile.mkdtemp(prefix="agy_prompt_"))
    tmp_file = tmp_dir / "prompt.md"
    tmp_file.write_text(prompt, encoding="utf-8")
    ref = (
        f"你的完整任务输入（含系统要求、背景上下文与用户消息）已存放在本地文件：{tmp_file}\n"
        "请先读取该文件的全部内容，然后严格按其中的要求处理并输出结果。"
        "直接用文本回复，不要修改任何项目文件，也不要创建新文件。"
    )
    logger.info(f"[AgyCli] prompt 超长（{len(prompt)} 字符），已外置到临时文件: {tmp_file}")
    return ref, tmp_dir


def _cleanup_prompt_file(tmp_dir: Optional[Path]) -> None:
    """清理外置 prompt 的临时文件（失败仅记录，不阻断主流程）"""
    if tmp_dir is None:
        return
    try:
        for f in tmp_dir.rglob("*"):
            if f.is_file():
                f.unlink()
        tmp_dir.rmdir()
    except Exception as e:
        logger.debug(f"[AgyCli] 临时 prompt 文件清理失败: {e}")


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


def _flatten_messages(messages: List[Dict[str, Any]]) -> str:
    """把 OpenAI 风格 messages 压平为 agy -p 的单一 prompt。

    agy 的 print 模式只接受单条 prompt：system 部分前置为「系统要求」，
    历史对话按角色标注，多模态 content parts 只取文本部分。
    """
    system_parts: List[str] = []
    convo: List[str] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", "")) for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        text = str(content or "").strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        else:
            prefix = "用户" if role == "user" else "助手"
            convo.append(f"[{prefix}] {text}")
    parts: List[str] = []
    if system_parts:
        parts.append("系统要求：\n" + "\n".join(system_parts))
    if len(convo) > 1:
        parts.append("历史对话：\n" + "\n".join(convo[:-1][-_AGY_CHAT_HISTORY_LIMIT:]))
    if convo:
        parts.append(convo[-1].removeprefix("[用户] "))
    return "\n\n".join(parts)


class AgyCliChatAdapter(BaseChatAdapter):
    """通过本机 agy CLI 的 -p (print) 模式聊天（本机登录态，不走反代）。

    不支持 function calling：Planner 自动回退到 studio-actions 文本解析路径。
    """

    def __init__(self, model: str = "auto"):
        self.model = model or "auto"

    def _build_args(self, exe: str, prompt: str, timeout_seconds: int) -> List[str]:
        args = [exe, "--print-timeout", f"{int(timeout_seconds)}s"]
        # auto → 不传 --model，由 agy 自行路由（对齐画布 run_gemini_cli）
        if self.model and self.model != "auto":
            args.extend(["--model", self.model])
        args.extend(["-p", prompt])
        return args

    @staticmethod
    def _check_busy(output: str) -> None:
        if any(marker in output for marker in _AGY_BUSY_MARKERS):
            raise AdapterError("agy CLI 服务暂时繁忙，请稍后重试", retryable=True)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> ChatResponse:
        exe = _agy_executable()
        if not exe:
            raise AdapterError("agy CLI 未安装或不在 PATH 中，无法使用 Antigravity CLI 聊天")
        timeout_seconds = timeout or settings.llm_timeout
        prompt = _flatten_messages(messages)
        logger.info(f"[AgyCli] chat: model={self.model}, prompt={prompt[:80]}")
        prompt, tmp_dir = _externalize_prompt(prompt)

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._build_args(exe, prompt, timeout_seconds),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            raise AdapterError(f"agy CLI 聊天超时（{timeout_seconds}s）", retryable=True)
        except OSError as e:
            raise AdapterError(f"agy CLI 启动失败: {e}")
        finally:
            _cleanup_prompt_file(tmp_dir)

        output = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace")[:300]
            raise AdapterError(f"agy CLI 返回错误 (code={proc.returncode}): {err_text}")
        self._check_busy(output)
        return ChatResponse(content=output.strip(), finish_reason="stop")

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式：逐行读取 agy 输出实时下发（print 模式下通常末尾一次性产出）"""
        exe = _agy_executable()
        if not exe:
            raise AdapterError("agy CLI 未安装或不在 PATH 中，无法使用 Antigravity CLI 聊天")
        timeout_seconds = timeout or settings.llm_stream_timeout
        prompt = _flatten_messages(messages)
        logger.info(f"[AgyCli] chat(stream): model={self.model}, prompt={prompt[:80]}")
        prompt, tmp_dir = _externalize_prompt(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._build_args(exe, prompt, timeout_seconds),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            collected: List[str] = []
            try:
                async def _read_stream():
                    assert proc.stdout is not None
                    while True:
                        line = await proc.stdout.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace")
                        collected.append(text)
                        if text.strip():
                            yield text

                deadline = asyncio.get_event_loop().time() + timeout_seconds
                gen = _read_stream()
                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    try:
                        text = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    yield StreamChunk(type="text_delta", text=text)
                await asyncio.wait_for(proc.wait(), timeout=max(1.0, deadline - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                raise AdapterError(f"agy CLI 聊天超时（{timeout_seconds}s）", retryable=True)

            if proc.returncode != 0:
                err_bytes = await proc.stderr.read() if proc.stderr else b""
                raise AdapterError(
                    f"agy CLI 返回错误 (code={proc.returncode}): {err_bytes.decode('utf-8', errors='replace')[:300]}"
                )
            output = "".join(collected)
            self._check_busy(output)
            yield StreamChunk(type="done", finish_reason="stop")
        finally:
            # 无论正常结束/异常/消费方提前关闭，都清理外置 prompt 临时文件
            _cleanup_prompt_file(tmp_dir)

    async def close(self) -> None:
        """无持久连接，接口对齐用"""
        return None


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
