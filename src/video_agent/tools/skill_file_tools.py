# -*- coding: utf-8 -*-
"""Skill 目录内只读文件工具（dsh `read` / `read_image` 同构）。

边界：
- 只读当前技能包（`SKILL.md`、`references/`、`assets/`）；
- 只接受包内相对路径；拒绝绝对路径、盘符、`..`、符号链接逃逸、
  多硬链接文件（`st_nlink > 1`：同 inode 的第二个目录项可在包外，
  字符串与 `resolve()` 都判不出来，是 jail 唯一的绕过面）；
- 文本按行号返回，单次 2000 行 / 约 50KB / 单行 2000 字符；
- 图片走 `read_image`（PNG/JPEG/WebP/GIF），其它媒体只返回元信息；
- 媒体描述符给 `{media_kind, mime, size, url}`，其中 **url 只在
  `/api/skills/{slug}/file` 确实放行该文件时生成**（route jail 复用
  registry.resolve_skill_resource 单一裁决）——保证「给了 URL 就一定能取到」；
- `read_image` 在返回 data_uri **之前**检查当前对话模型是否声明接受图片输入
  （core/chat_port 的能力发布面），明确不支持时返回可行动错误、不产出
  images/data_uri；
- 不审批，risk=low，parallel_safe=True。
"""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type
from urllib.parse import quote

from loguru import logger
from pydantic import BaseModel, Field

from src.video_agent.core.chat_port import current_model_supports_image_input
from src.video_agent.skill_runtime import registry
from src.video_agent.storage.media_urls import MAX_IMAGE_BYTES, downscale_image
from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.agent_depth import is_subagent_context

_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv"})
# read_image 支持的图片格式 = 供应商多模态接口**实际接受**的集合。
# 刻意不含 `.bmp`：registry 把 bmp 归 image 媒体（可经 /skills/{slug}/file
# 按 URL 引用），但 OpenAI 兼容 vision 接口不接受 image/bmp——把 bmp 纳入
# read_image 只会产出一个必然被上游 400 拒收的 data URI。故口径取「描述符
# 提示与支持集一致」这一侧：bmp 的 detail 不再提示 read_image，改提示按
# URL 引用（见 _media_detail）。
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_MAX_LINES = 2000
_MAX_BYTES = 51200
_MAX_LINE_CHARS = 2000


class ReadFileInput(StrictToolInput):
    skill: str = Field(..., description="Skill 包标识（slug）")
    file_path: str = Field(
        ..., description="包内相对路径，如 SKILL.md、references/xxx.md、assets/xxx.png")
    # pydantic 约束兜住非法值（ge=1），不再只靠 _slice_lines 的 max(1,...) 兜底：
    # 非法入参在 schema 层就被拒收，模型拿到字段级错误可一次改对。
    # offset 不设上界：超过总行数由 _slice_lines 收敛到末行（读长文档尾部的
    # 正常用法），设上界会把「读第 3000 行」这种合法请求误拒。
    offset: int = Field(1, ge=1, description="起始行号（1-based）")
    # limit 上界 = 单次 2000 行（dsh read 口径，与 _MAX_LINES 同一事实源）
    limit: int = Field(_MAX_LINES, ge=1, le=_MAX_LINES,
                       description=f"最多返回行数（1-{_MAX_LINES}）")


class ReadImageInput(StrictToolInput):
    skill: str = Field(..., description="Skill 包标识（slug）")
    file_path: str = Field(..., description="包内相对图片路径，如 assets/参考图.png")


def _resolve_skill_file(skill: str, file_path: str) -> Tuple[Optional[registry.SkillEntry], Optional[Path], str, str]:
    """解析技能包内文件：返回 (entry, target, rel, 错误)。

    路径 jail 双检：先做字符串形状校验，再 `resolve()` 确认仍在包根内；
    任一父目录是符号链接也拒绝（防白名单后缀链接越界）。
    """
    entry = registry.resolve_loadable_entry(skill)
    if entry is None:
        return None, None, "", f"未找到可加载的 Skill「{skill}」"
    # user-only 技能正文门禁（用户裁决 2026-11-12，见 ARCHITECTURE_RULES §2.8）：
    # 「用户手动触发、模型不可调用」的技能，**主代理**不得经 read_file/read_image
    # 自行加载其任何正文（含 SKILL.md 与分册）；**子代理**照常可读——保留
    # 「主代理把技能包路径交给子代理自读」的供给设计。判据两维缺一不可：
    # 目标条目 model_invocable=false **且** 当前委派深度为 0。
    # 文案与 read_skill 对齐（同一语义、同一句），便于模型形成单一心智。
    if (not entry.model_invocable) and not is_subagent_context():
        return (
            entry, None, "",
            f'skill "{entry.name}" is not available for model invocation',
        )
    root = entry.package_root
    if root is None:
        return entry, None, "", f"Skill「{entry.name}」主文档不在场，无法定位包根"
    raw = str(file_path or "").strip().replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p != "."]
    if not raw or not parts or ".." in parts:
        return entry, None, "", "文件路径非法：只允许包内相对路径（禁绝对路径/盘符/..）"
    if raw.startswith("/") or ":" in raw:
        return entry, None, "", "文件路径非法：只允许包内相对路径（禁绝对路径/盘符/..）"
    if parts[0] not in ("references", "assets") and raw != "SKILL.md":
        return entry, None, "", "只允许读取 SKILL.md、references/ 或 assets/ 下的文件"
    cur = root
    for p in parts:
        cur = cur / p
        if cur.is_symlink():
            return entry, None, "", "文件路径含符号链接，拒绝读取"
    target = (root / "/".join(parts))
    if not target.is_file():
        return entry, None, "", f"文件不存在：{raw}"
    # 硬链接逃逸（审计点名的唯一 jail 绕过）：同 inode 的**第二个目录项**可以
    # 落在包外，而路径字符串与 resolve() 都判不出来（resolve 只解符号链接）。
    # 包内普通文件 st_nlink 恒为 1；>1 = 该 inode 还有别的名字（可能在包外），
    # fail-closed 拒绝。
    try:
        if target.stat().st_nlink > 1:
            return entry, None, "", "文件为硬链接（同一 inode 存在包外目录项），拒绝读取"
    except OSError as e:
        return entry, None, "", f"文件状态读取失败：{e}"
    try:
        if not target.resolve().is_relative_to(root.resolve()):
            return entry, None, "", "文件解析后逃逸技能包根，拒绝读取"
    except OSError as e:
        return entry, None, "", f"文件解析失败：{e}"
    return entry, target, "/".join(parts), ""


def _slice_lines(text: str, offset: int, limit: int) -> Tuple[str, int, int, int]:
    """按行截取：返回 (带行号正文, 起始行, 结束行, 总行数)。

    上限三件套（dsh read 口径）：2000 行 / 约 51200 字节 / 单行 2000 字符。
    """
    lines = text.splitlines()
    total = len(lines)
    start = max(1, int(offset or 1))
    if start > total and total:
        start = total
    count = max(1, min(int(limit or _MAX_LINES), _MAX_LINES))
    end = min(total, start - 1 + count) if total else 0
    out: List[str] = []
    used = 0
    for i in range(start - 1, end):
        line = lines[i][:_MAX_LINE_CHARS]
        if len(lines[i]) > _MAX_LINE_CHARS:
            line += f"... (line truncated to {_MAX_LINE_CHARS} chars)"
        numbered = f"{i + 1}: {line}"
        size = len(numbered.encode("utf-8")) + 1
        if used + size > _MAX_BYTES:
            end = i
            break
        out.append(numbered)
        used += size
    body = "\n".join(out)
    if end < total:
        body += f"\n(Output capped. Showing lines {start}-{end}. Use offset={end + 1} to continue.)"
    elif total:
        body += f"\n(End of file - total {total} lines)"
    return body, start, end, total


def _media_kind(rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    return str(registry.RESOURCE_MEDIA_SUFFIXES.get(suffix)
               or registry.ASSET_DOC_SUFFIXES.get(suffix) or "")


def _media_url(entry: registry.SkillEntry, rel: str) -> str:
    """媒体 URL：**只在该路由确实放行此文件时生成**，否则返回空串。

    jail 等价修复（2026-11-13）：`/api/skills/{slug}/file` 走
    `registry.resolve_skill_resource` 的 fail-closed 白名单（references/ 只
    放行文本清单 + 媒体后缀、assets/ 只放行媒体 + 文档素材后缀），而
    read_file 的 jail 更宽（references/ 任意文件都可读成元信息）。直接拼
    URL 会让 `references/x.pdf` 之类必然 404——「给了 URL 就要能取到」是
    契约，故此处**复用同一个裁决函数**判定可路由性（不放宽 jail，也不另
    写第二份白名单：单一事实源 = registry.resolve_skill_resource）。
    """
    try:
        resolvable, _err = registry.resolve_skill_resource(entry.slug, rel)
    except Exception:  # noqa: BLE001 —— 路由能力判定失败按「不可路由」降级
        return ""
    if resolvable is None:
        return ""
    return f"/api/skills/{quote(entry.slug)}/file?path={quote(rel)}"


def _media_detail(rel: str, kind: str, size: int, url: str) -> str:
    """媒体描述符的模型可见说明（与实际能力一致，不做空头指引）。"""
    can_read_image = Path(rel).suffix.lower() in _IMAGE_SUFFIXES
    if can_read_image:
        view = "图片可用 read_image 查看画面"
    elif kind == "image":
        # 图片媒体但不在 read_image 支持集（如 .bmp）：不给工具名指引
        # （点了必然被拒），只给可用路径。
        view = "该图片格式不支持加载进上下文，请按 URL 引用"
    else:
        view = "音频/视频/文档按 URL 引用"
    where = f"，URL：{url}" if url else "，该文件不提供 HTTP 访问（只给元信息）"
    return (f"{rel}：{kind} 媒体（{size} 字节）。二进制不读入文本；"
            f"{view}{where}。")


class ReadFileTool(BaseTool):
    name = "read_file"
    risk = "low"
    parallel_safe = True
    detail_tier = "output"
    description = (
        "读取当前技能包内的文件（SKILL.md、references/、assets/）。"
        "只接受包内相对路径；文本按行返回，图片/音频/视频只返回元信息。"
        "图片要看画面请用 read_image。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadFileInput

    def model_view(self, data: Optional[Dict]) -> str:
        data = data or {}
        view = str(data.get("content") or data.get("detail") or "").strip()
        if view:
            return view
        return json.dumps(data, ensure_ascii=False) if data else ""

    async def aexecute(self, params: ReadFileInput) -> ToolResult:
        entry, target, rel, err = _resolve_skill_file(params.skill, params.file_path)
        if err or entry is None or target is None:
            return ToolResult(success=False, error=err, error_code="validation")
        kind = _media_kind(rel)
        if kind:
            try:
                size = target.stat().st_size
            except OSError:
                size = -1
            url = _media_url(entry, rel)
            return ToolResult(success=True, data={
                "skill": entry.slug,
                "path": rel,
                "media_kind": kind,
                # mime（计划要求 {url, mime, size} 三件套）：walk 不到返回空串，
                # 不臆造 application/octet-stream（调用方据空串自行降级）。
                "mime": mimetypes.guess_type(target.name)[0] or "",
                "size": size,
                "url": url,
                "detail": _media_detail(rel, kind, size, url),
            })
        suffix = target.suffix.lower()
        if suffix not in _TEXT_SUFFIXES:
            return ToolResult(
                success=False,
                error=f"不支持读取该文件类型：{suffix or '无扩展名'}（只读文本/图片/媒体元信息）",
                error_code="validation",
            )
        try:
            text = target.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            return ToolResult(success=False, error=f"文件读取失败：{e}", error_code="upstream")
        body, start, end, total = _slice_lines(text, params.offset, params.limit)
        logger.info(f"[SkillFile] read_file {entry.slug}/{rel} 行 {start}-{end}/{total}")
        return ToolResult(success=True, data={
            "skill": entry.slug,
            "path": rel,
            "content": body,
            "start_line": start,
            "end_line": end,
            "total_lines": total,
            "detail": f"已读取 {entry.slug}/{rel} 第 {start}-{end} 行（共 {total} 行）",
        })


class ReadImageTool(BaseTool):
    name = "read_image"
    risk = "low"
    parallel_safe = True
    detail_tier = "output"
    description = (
        "读取技能包内的图片并加载进上下文（PNG/JPEG/WebP/GIF）。"
        "只接受 assets/ 或 references/ 下的相对路径。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadImageInput

    def model_view(self, data: Optional[Dict]) -> str:
        data = data or {}
        view = str(data.get("detail") or "").strip()
        if view:
            return view
        return json.dumps(data, ensure_ascii=False) if data else ""

    async def aexecute(self, params: ReadImageInput) -> ToolResult:
        entry, target, rel, err = _resolve_skill_file(params.skill, params.file_path)
        if err or entry is None or target is None:
            return ToolResult(success=False, error=err, error_code="validation")
        if target.suffix.lower() not in _IMAGE_SUFFIXES:
            return ToolResult(
                success=False,
                error=f"不是支持的图片类型：{target.suffix or '无扩展名'}（PNG/JPEG/WebP/GIF）",
                error_code="validation",
            )
        # 适配器能力闸（2026-11-13）：产出 data URI **之前**判定当前模型是否
        # 声明接受图片输入。三态语义见 core/chat_port：
        #   False（明确不支持）→ 明确报错，不产出 images/data_uri（否则下一轮
        #     请求被供应商 400 拒收，模型只看到「莫名失败」）；
        #   True / None（支持 / 未发布）→ 放行（None = 非对话路径/单测直连，
        #     不新增闸门，维持改动前行为）。
        if current_model_supports_image_input() is False:
            return ToolResult(
                success=False,
                error=("当前模型未声明图片输入能力（supports_image_input=False），"
                       "无法把图片加载进上下文。可改用 read_file 读取该图片的"
                       "元信息（mime/size/URL）按引用使用，或切换到支持视觉输入的模型。"),
                error_code="validation",
            )
        try:
            raw = target.read_bytes()
        except OSError as e:
            return ToolResult(success=False, error=f"图片读取失败：{e}", error_code="upstream")
        if len(raw) > MAX_IMAGE_BYTES:
            return ToolResult(
                success=False,
                error=f"图片超过 {MAX_IMAGE_BYTES // (1024 * 1024)}MB 上限，拒绝加载",
                error_code="validation",
            )
        scaled, mime_override = downscale_image(raw, target.suffix.lower())
        mime = mime_override or mimetypes.guess_type(target.name)[0] or "image/png"
        data_uri = f"data:{mime};base64," + base64.b64encode(scaled).decode("ascii")
        detail = f"已加载图片 {entry.slug}/{rel}（{len(scaled)} 字节，{mime}）"
        logger.info(f"[SkillFile] read_image {entry.slug}/{rel} ({len(raw)}→{len(scaled)} bytes)")
        return ToolResult(success=True, data={
            "images": [{"label": rel, "data_uri": data_uri}],
            "notes": [],
            "skill": entry.slug,
            "path": rel,
            "detail": detail,
        })


def register_skill_file_tools() -> None:
    ToolManager.register(ReadFileTool())
    ToolManager.register(ReadImageTool())
    logger.info("[Tools] 2 skill file tools registered（read_file/read_image）")
