"""
文档 & 生成 Tool — write_document / read_uploaded_doc / image_generate / workflow_pause
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete
from src.video_agent.core import ports, prompt_gates
from src.video_agent.core.spec_rules import IRON_RULES_HEADING, ensure_iron_rules_doc
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.base import (
    BaseTool,
    ProviderInjectionContext,
    StrictToolInput,
    ToolResult,
)
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.state.manager import StateManager
from src.video_agent.exceptions import GenerationError
from src.video_agent.core.provider_config import (
    first_available_image_provider,
    first_available_image_provider_async,
    resolve_provider_ref,
    spec_media_preference,
    spec_production_params,
)
from src.video_agent.utils import gen_id
from src.video_agent.utils.prompts import render_prompt_section


# ---------- Input Schemas ----------

# 写类 Input 继承 StrictToolInput（extra="forbid"，批 4b）；
# 只读/交互控制面（workflow_pause）保持 BaseModel 原样。

class WriteDocumentInput(StrictToolInput):
    name: str = Field(..., description="文档名称（如 Final_Video_Spec.md）")
    content: str = Field(..., description="文档 Markdown 全文")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class ReadUploadedDocInput(BaseModel):
    name: str = Field("", description="文档名称（与清单中的名称一致，优先）")
    doc_id: str = Field("", description="文档 ID（可选，name 为空时用）")
    start: int = Field(0, ge=0, description="读取起始位置（字符偏移）；正文超长时工具会返回下一段的 start 值，传入即可续读")


class ReadSkillInput(BaseModel):
    name: str = Field(..., description="Skill 名称（与 Skill 目录中的名称一致）")
    section: str = Field(
        "", description="可选：章节标题（以 Skill 正文里的标题为准，如 planner/提示词写法），"
        "传入则只返回该章节全文；不传返回 Skill 全文（或按 start 续读）")
    start: int = Field(
        0, ge=0, description="读取起始位置（字符偏移，相对全文原文）；正文超长时工具会返回"
        "下一段的 start 值，传入即可续读（section 指定时以该章节为基准续读）")
    resource: str = Field(
        "", description="可选：目录包 Skill 的附属资源路径（如 references/五行特效提示词库.md，"
        "主文对应环节会给出按需加载指引）；传入则只返回该资源文件内容（超长可按 start 续读），"
        "仅清单内资源可读；无附属资源的 Skill 不支持本参数")


class ReadProjectDocInput(BaseModel):
    name: str = Field(..., description="规格文档名称（如 Final_Video_Spec.md）")
    start: int = Field(0, ge=0, description="读取起始位置（字符偏移）；正文超长时工具会返回下一段的 start 值，传入即可续读")


class ListSkillsInput(BaseModel):
    """list_skills 无参数（只读全量名单）；保留空入参模型保 FC schema 形状一致。"""


class GetSkillAssetInput(BaseModel):
    name: str = Field(..., description="Skill 名称（与 Skill 目录中的名称一致）")
    path: str = Field(
        ..., description="目录包内素材相对路径（必须在 assets/ 下，如 assets/场景参考图.png）；"
        "文本参考资料不走本工具，用 read_skill(resource=…)")


class GenerateImageInput(StrictToolInput):
    mode: str = Field("batch", description="生图模式: batch=工作台批量出图（面向故事板草稿，默认）| single=对话内单张应急出图（需传 prompt）")
    # --- batch 模式参数 ---
    target: str = Field("all_keyElements", description="batch 模式目标: all_keyElements | all_shots | 具体 draft_id")
    provider_id: str = Field("", description="生图供应商 ID（可留空，系统自动回退草稿自带供应商或配置中首个可用生图供应商）")
    model: str = Field("", description="生图模型名（可留空，自动用供应商默认模型）")
    # --- single 模式参数 ---
    prompt: str = Field("", description="single 模式必填：图片生成的视觉提示词")
    reference_image: Optional[str] = Field(None, description="single 模式可选：参考图片的本地路径")
    adapter_provider: str = Field("", description="single 模式生图适配器名称（可留空，系统自动回退草稿/全局设置）")
    aspect_ratio: Optional[str] = Field(None, description="single 模式画面比例，如 16:9、9:16、1:1")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class WorkflowPauseInput(BaseModel):
    message: str = Field(
        "", description="给用户的补充说明（展示在正文；暂停卡上的问句由系统按阶段自动生成，无需撰写）。"
        "阶段成果（剧本分析要点等）由系统自动渲染进正文，"
        "message 中不要复述成果内容，只写与本次确认相关的补充说明，保持简短。"
    )

    options: List[Dict[str, str]] = Field(
        default_factory=list,
        description="引导选项（前端渲染为选择卡片，用户选择后作为回复发送），暂停时原则上必须提供："
        "每项 {label: 具体可选值（如「硬科幻」「16:9」）, description: 一句话说明, "
        "group: 所属维度标题（可选）}。多维度一次收集时每项带 group，"
        "前端渲染为分页向导卡片，用户逐页选完后一次性发回全部选择。",
    )


# ---------- Tool 实现 ----------

def _norm_name(s: str) -> str:
    """名称归一化：去空格/后缀/大小写，用于模糊匹配"""
    s = (s or "").strip().casefold()
    for ext in (".md", ".txt"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.replace(" ", "")


def _fuzzy_pick(items: List[Dict[str, Any]], wanted: str, keys: List[str]) -> Optional[Dict[str, Any]]:
    """从清单里按名称模糊定位一条记录：精确 → 归一化相等 → 双向包含。

    模型传的名称常与清单略有出入（带/不带后缀、别名），
    匹配失败会导致 read_* 读不到内容，渐进式披露直接失效，故尽量宽松。
    """
    wanted_norm = _norm_name(wanted)
    if not wanted_norm:
        return None

    def names(item: Dict[str, Any]) -> List[str]:
        return [str(item.get(k) or "") for k in keys]

    # 1. 精确匹配
    for item in items:
        if wanted in names(item):
            return item
    # 2. 归一化后相等（剧本 ≈ 剧本.md）
    for item in items:
        if any(_norm_name(n) == wanted_norm for n in names(item) if n):
            return item
    # 3. 双向包含（短名找长名 / 长名找短名），防止单字误匹配
    if len(wanted_norm) >= 2:
        for item in items:
            for n in names(item):
                nn = _norm_name(n)
                if nn and len(nn) >= 2 and (wanted_norm in nn or nn in wanted_norm):
                    return item
    return None

class DocumentWriteTool(BaseTool):
    name = "document_write"
    risk = "medium"  # §2.7（2026-09-07 外部标杆对齐）：写状态但可撤销（文档带修订记录），写入不设逐次确认闸
    detail_tier = "expand"  # 产出类：展开看输入参数+执行结果
    description = (
        "写入/更新项目文档工件（如制片规格、脚本大纲）。已存在同名文档则整篇覆盖"
        "（规格是活的：改分辨率/时长/声音方向等先更新规格再继续，系统自动留更新痕迹）。"
        "规格文档定位：写提示词、拆关键元素、拆分镜时按需自取的输入参照。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return WriteDocumentInput

    async def aexecute(self, params: WriteDocumentInput) -> ToolResult:
        svc = StateManager.get_instance()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = str(params.content or "")
        # 规格文档判定唯一口径（prompt_gates.is_spec_doc_name）：规格写入后同批补铁律
        is_spec = prompt_gates.is_spec_doc_name(str(params.name or ""))
        # 铁律文档保护：铁律由系统维护 + 用户在文档面板手改，
        # 模型只读不得整篇重写（会盖掉用户编辑）
        if IRON_RULES_HEADING in str(params.name or ""):
            return ToolResult(
                success=False,
                error=("《执行铁律.md》由系统维护、用户在文档面板手动编辑，模型不得整篇重写"
                       "（会盖掉用户的修改）。如需调整流程开关，按用户指令由系统幂等合并对应声明行即可。"),
            )

        async with svc.lock:
            docs = svc.state_dict.setdefault("documents", [])

            for d in docs:
                if d.get("name") == params.name:
                    d["content"] = content
                    d["updated_at"] = now
                    # 批 1 · A4：可更新留痕——覆盖式更新也留下修订次数
                    d["revisions"] = int(d.get("revisions") or 0) + 1
                    if is_spec:
                        ensure_iron_rules_doc(svc.state_dict)
                    svc.save()
                    return ToolResult(success=True, data={
                        "name": params.name, "action": "updated",
                        "revisions": int(d.get("revisions") or 0),
                    })

            docs.append({
                "id": gen_id("doc"),
                "name": params.name,
                "content": content,
                "created_at": now,
                "updated_at": now,
                "revisions": 0,
            })
            if is_spec:
                ensure_iron_rules_doc(svc.state_dict)
            svc.save()
        return ToolResult(success=True, data={"name": params.name, "action": "created", "revisions": 0})


class ReadUploadedDocTool(BaseTool):
    name = "read_uploaded_doc"
    risk = "low"  # §2.7：只读
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "读取用户上传的素材文档（故事/剧本等）全文。"
        "上传文档正文不自动注入上下文，清单里只有名称/字数/预览，"
        "需要全文时按 name 调用本工具；超长文档传 start 分段续读。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadUploadedDocInput

    async def aexecute(self, params: ReadUploadedDocInput) -> ToolResult:
        svc = StateManager.get_instance()
        docs = svc.state_dict.get("uploadedDocs") or []
        target, auto_note = _resolve_uploaded_doc(docs, params.name, params.doc_id)
        if target is None:
            available = "、".join(d.get("name", "") for d in docs[:10]) or "无"
            return ToolResult(success=False, error=f"未找到该文档。已存档文档：{available}")
        content = target.get("content", "") or ""
        max_chars = settings.max_doc_chars
        start = max(0, params.start)
        if start >= len(content) and content:
            return ToolResult(success=False, error=f"文档已读完（共 {len(content)} 字，无后续内容）")
        body = content[start:start + max_chars]
        end = start + len(body)
        # 分段续读：返回区间与下一段 start 值，超长文档不再丢尾部
        note = "" if end >= len(content) else (
            f"\n……（正文共 {len(content)} 字，本次返回第 {start}~{end} 字；"
            f"传 start={end} 继续读取剩余 {len(content) - end} 字）"
        )
        return ToolResult(success=True, data={
            "name": target.get("name", ""),
            "content": (auto_note + "\n" if auto_note else "") + body + note,
            "char_count": target.get("char_count", len(content)),
        })


def _resolve_uploaded_doc(docs: list, name: str, doc_id: str) -> tuple:
    """返回 (target, auto_note)：name/doc_id 皆空且恰有一个已存档文档时
    自动归位（掐掉空参试探的失败轮）；其余情形维持原匹配/报错路径。"""
    target = None
    if name:
        target = _fuzzy_pick(docs, name, ["name"])
    if target is None and doc_id:
        target = next((d for d in docs if d.get("id") == doc_id), None)
    auto_note = ""
    if target is None and not name and not doc_id and len(docs) == 1:
        target = docs[0]
        auto_note = f"（未传 name，已自动归位到唯一存档文档『{target.get('name', '')}』）"
    return target, auto_note


def _slice_content(content: str, start: int) -> tuple:
    """分段读取：返回 (切片正文, 续读提示)。超出上限时提示下一段 start 值，
    超长文档不再丢尾部"""
    max_chars = settings.max_doc_chars
    start = max(0, start)
    body = content[start:start + max_chars]
    end = start + len(body)
    note = "" if end >= len(content) else (
        f"\n……（正文共 {len(content)} 字，本次返回第 {start}~{end} 字；"
        f"传 start={end} 继续读取剩余 {len(content) - end} 字）"
    )
    return body, note


def _skill_source_note(skill_name: str) -> str:
    """外部来源标记（Skill 是指令性制作手册，决策史见 git tag adr-archive-20260901）：仅外部/社区来源附中性来源短句，
    文案同源外置 shared/skill_inject.md（不内联）；平台来源干净返回。"""
    try:
        source = (registry.skill_manifest_of(skill_name) or {}).get("source")
    except Exception:
        return ""
    if not isinstance(source, str) or not source.strip():
        return ""
    if source.strip().lower() == "platform":
        return ""
    return render_prompt_section(
        "shared/skill_inject.md", "READ_NOTE", source=source.strip())


class ReadSkillTool(BaseTool):
    name = "read_skill"
    risk = "low"  # §2.7：只读
    # 五项修法批 3：模型惯于并行连发的只读工具，可进有界并行池
    parallel_safe = True
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "Skill 正文/章节/附属资源按需读取。"
        "选中 Skill 已注入流程段全文与章节目录，其余章节传 section 读取，"
        "超长章节传 start 续读；未选中的 Skill 经本工具读全文；"
        "目录包附属资料（主文标注「按需加载」处）传 resource（如 references/…）读取。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadSkillInput

    async def aexecute(self, params: ReadSkillInput) -> ToolResult:
        # 经 skill_docs 端口消费（依赖倒置），消灭 tools→web 反向依赖
        sd = ports.skill_docs_port()

        wanted = (params.name or "").strip()
        # 与 Planner 选中项注入共用同一套解析（仅文档 Skill，模糊匹配）；
        # 可加载性门户在 resolve_skill_content 内收口（M2 停用=真停用）
        matched, content = sd.resolve_skill_content(wanted)
        if not content:
            # canonical 身份兜底（Rule2 v6）：模型逐字复制显示名的误差
            # （去连字符/空格归一）经 registry 定位同身份条目（同走门户）
            entry = registry.resolve_loadable_entry(wanted)
            if entry is not None and str(entry.content or "").strip():
                matched, content = entry.name, entry.content
        if not content:
            # 拒载文案外置 planner/skill_runtime.md（M3 批2）：三类语义区分——
            # 已停用（仅真停用才报，在册启用项不误报）/ 未注册被拒 / 未找到；
            # 外置文案空串时内置短句兜底，不降级空 error（文案兜底）
            _reg = registry.resolve_entry(wanted)
            if _reg is not None and _reg.slug in registry.disabled_slugs():
                return ToolResult(success=False, error=render_prompt_section(
                    "planner/skill_runtime.md", "DISABLED", name=wanted)
                    or f"Skill「{wanted}」已停用，不可读取（停用=真停用）")
            # 磁盘存在同名包但未注册/被拒注册（坏 frontmatter 等）：发现→注册→
            # 加载，未过注册不得加载；工作台 /api/skills/docs 仍可见供修复
            try:
                disk_docs = sd.list_skill_docs()
            except Exception:
                disk_docs = []
            if _fuzzy_pick(disk_docs, wanted, ["name", "slug"]) is not None:
                return ToolResult(success=False, error=render_prompt_section(
                    "planner/skill_runtime.md", "UNREGISTERED", name=wanted)
                    or f"Skill「{wanted}」未通过注册，不可加载（请到 Skill 工作台修复）")
            available = [e.name for e in registry.loadable_entries()]
            return ToolResult(success=False, error=render_prompt_section(
                "planner/skill_runtime.md", "NOT_FOUND",
                name=wanted, available="、".join(available) or "无")
                or f"未找到 Skill「{wanted}」")
        # read_skill 直接输出正文，不加任何前置包壳，
        # 仅外部来源附来源标记短句（同源外置）
        source_note = _skill_source_note(matched)
        # 目录包资源按需加载（P2-4）：resource 与正文/章节互斥，
        # 只放行资源清单内文件（fail-closed 归 registry.resolve_skill_resource）
        resource = (params.resource or "").strip()
        if resource:
            res_path, res_err = registry.resolve_skill_resource(wanted, resource)
            if res_path is None:
                return ToolResult(success=False, error=res_err)
            # 批4：二进制资源禁入文本通道——图/音/视频后缀只返回元数据描述符，
            # 不按文本读（防二进制垃圾进上下文）
            media_kind = registry.RESOURCE_MEDIA_SUFFIXES.get(res_path.suffix.lower())
            if media_kind is not None:
                try:
                    size = res_path.stat().st_size
                except OSError:
                    size = -1
                return ToolResult(success=True, data={
                    "name": matched, "resource": resource,
                    "media_kind": media_kind, "size": size,
                    "content": (
                        f"二进制资源元数据描述符：名称={resource}，类型={media_kind}，"
                        f"大小={size} 字节（图/音/视频资源按引用消费，不按文本读入）"),
                })
            try:
                res_text = res_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as e:
                return ToolResult(success=False, error=f"资源读取失败 {resource}: {e}")
            start = max(0, params.start)
            if start >= len(res_text) and res_text:
                return ToolResult(
                    success=False,
                    error=f"资源已读完（共 {len(res_text)} 字，无后续内容）")
            body, note = _slice_content(res_text, start)
            return ToolResult(success=True, data={
                "name": matched, "resource": resource, "content": body + note,
            })
        # 章节续读：section 命中章节目录时只返回该章节全文，
        # start 相对章节起点；未命中时回喂可用章节清单（不阻断，给模型纠错机会）
        section = (params.section or "").strip()
        if section:
            toc = sd.list_skill_sections(content)
            hit = next((s for s in toc if s["title"] == section), None)
            if hit is None:
                sec_norm = section.casefold().replace(" ", "")
                hit = next((s for s in toc
                            if s["title"].casefold().replace(" ", "") == sec_norm), None)
            if hit is None:
                titles = "、".join(s["title"] for s in toc[:20]) or "无"
                return ToolResult(
                    success=False,
                    error=f"未找到章节「{section}」。可用章节：{titles}",
                )
            sec_text = content[hit["start"]:hit["end"]]
            start = max(0, params.start)
            if start >= len(sec_text) and sec_text:
                return ToolResult(
                    success=False,
                    error=f"章节「{section}」已读完（共 {len(sec_text)} 字，无后续内容）")
            body, note = _slice_content(sec_text, start)
            out = body + note + ("\n" + source_note if source_note else "")
            return ToolResult(success=True, data={
                "name": matched, "section": hit["title"], "content": out,
            })
        # 全文按需读：start>0 时按字符偏移续读（复用 read_uploaded_doc 分段先例）
        start = max(0, params.start)
        if start >= len(content) and content:
            return ToolResult(
                success=False,
                error=f"Skill 已读完（共 {len(content)} 字，无后续内容）")
        body, note = _slice_content(content, start)
        out = body + note + ("\n" + source_note if source_note else "")
        return ToolResult(success=True, data={"name": matched, "content": out})


class ListSkillsTool(BaseTool):
    name = "list_skills"
    risk = "low"  # §2.7：只读无副作用（批5，对齐外部标杆 卡片开关的名单探针）
    # 五项修法批 3：模型惯于并行连发的只读工具，可进有界并行池
    parallel_safe = True
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "列出当前全部启用的 Skill（名称+摘要，只读）。经开关停用的 Skill 不在此列；"
        "目录段因预算截断未列全时，或需核对可用 Skill 名单时调用本工具；"
        "具体 Skill 全文仍经 read_skill 按需读取。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ListSkillsInput

    async def aexecute(self, params: ListSkillsInput) -> ToolResult:
        # 名单与 count 统一从可加载性门户派生（单一事实源：已注册 ∧ 未停用，
        # 开关活读；M2 停用=真停用，不再在本工具内联复述过滤）
        try:
            entries = registry.loadable_entries()
        except Exception as e:
            return ToolResult(success=False, error=f"Skill 名单读取失败：{e}")
        skills = [
            {
                "name": e.name,
                "slug": e.slug,
                "description": str((e.manifest or {}).get("description") or "").strip(),
            }
            for e in entries
        ]
        return ToolResult(success=True, data={"skills": skills, "count": len(skills)})


class GetSkillAssetTool(BaseTool):
    name = "get_skill_asset"
    risk = "low"  # §2.7：只读元数据（批6 素材描述符）
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "取 Skill 目录包 assets/ 下素材资源的描述符（路径/名/大小/类型）："
        "把其中 path 传给生成类工具（image_generate/generate_video 等）作参考素材；"
        "二进制内容不进对话上下文，文本参考资料经 read_skill(resource=…) 读取。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GetSkillAssetInput

    async def aexecute(self, params: GetSkillAssetInput) -> ToolResult:
        rel = (params.path or "").strip().replace("\\", "/")
        parts = [p for p in rel.split("/") if p and p != "."]
        if not parts or parts[0] != registry.ASSET_DIR_NAME:
            return ToolResult(
                success=False,
                error=(f"素材路径 {params.path!r} 非法（只允许包内 "
                       f"{registry.ASSET_DIR_NAME}/ 相对路径；文本参考走 "
                       "read_skill(resource=…)）"),
                error_code="validation", retryable=False,
            )
        # fail-closed 归单一实现（包内路径/符号链接/逃逸守卫同口径）
        res_path, res_err = registry.resolve_skill_resource(params.name, rel)
        if res_path is None:
            return ToolResult(success=False, error=res_err)
        kind = registry.ASSET_DESCRIPTOR_SUFFIXES.get(res_path.suffix.lower(), "")
        try:
            size = res_path.stat().st_size
        except OSError:
            size = -1
        # 描述符只含元数据（路径/名/大小/类型 + 版本锁声明）；二进制不进上下文，
        # 生成类工具经 path 按引用消费（宪法 Rule 4 走 Adapter 通道）
        entry = registry.resolve_entry(params.name)
        declared = (entry.declared_resources if entry else {}).get(
            "/".join(parts)) or {}
        sha = declared.get("sha256")
        data: Dict[str, Any] = {
            "skill": entry.name if entry else params.name,
            "name": res_path.name,
            "asset": rel,
            "path": str(res_path),
            "size": size,
            "media_kind": kind,
        }
        if isinstance(sha, str) and sha.strip():
            data["sha256"] = sha.strip()
        return ToolResult(success=True, data=data)


class ReadProjectDocTool(BaseTool):
    name = "read_project_doc"
    risk = "low"  # §2.7：只读
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "读取项目规格文档（document_write 产出，如 制片规格.md）全文。"
        "工作台状态 JSON 的 documents 节只有清单（名称/摘要），全文经本工具读取；"
        "超长文档传 start 分段续读。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadProjectDocInput

    async def aexecute(self, params: ReadProjectDocInput) -> ToolResult:
        svc = StateManager.get_instance()
        docs = svc.state_dict.get("documents") or []
        wanted = (params.name or "").strip()
        target = _fuzzy_pick(docs, wanted, ["name"])
        if target is None:
            available = "、".join(d.get("name", "") for d in docs[:10]) or "无"
            return ToolResult(success=False, error=f"未找到文档「{wanted}」。已有文档：{available}")
        full = target.get("content", "") or ""
        start = max(0, params.start)
        if start >= len(full) and full:
            return ToolResult(success=False, error=f"文档已读完（共 {len(full)} 字，无后续内容）")
        body, note = _slice_content(full, start)
        return ToolResult(success=True, data={
            "name": target.get("name", ""),
            "content": body + note,
            "updated_at": target.get("updated_at", ""),
        })


# T2 第一步：混合集 target 结构化校验——具体 draft_id 需为 ASCII 字母数字/
# 下划线/连字符/点号（不得含空格/中文等明显非法字符），长度≤64。
_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_TARGET_VALID_HINT = (
    "target 合法取值: all_keyElements | all_shots | 具体 draft_id"
    "（或「组号-卡序号」编号，如 '1-2'）"
)


def _sample_draft_ids(state: Dict[str, Any], limit: int = 5) -> str:
    """采样可用 draft_id 嵌入结构化报错文案，帮助模型一次改对。"""
    ids: List[str] = []
    for cat in ALL_CATEGORIES_TUPLE:
        for g in state.get(cat, []) or []:
            for d in g.get("drafts", []) or []:
                did = str(d.get("id") or "")
                if did and did not in ids:
                    ids.append(did)
                if len(ids) >= limit:
                    return "、".join(ids)
    return "、".join(ids) if ids else "无"


class ImageGenerateTool(BaseTool):
    name = "image_generate"
    risk = "high"  # §2.7：生成类（外部副作用/花钱），经生成确认闸覆盖；确认档由 risk 单轴推导（F1）
    costly = True  # 批 B 花钱生成声明轴：执行偏好三档可放宽其确认闸（留痕）
    detail_tier = "expand"  # 产出类
    provider_kind = "image"  # I-3 裁决 2026-09-03：provider 注入声明轴（single/batch 形态在 apply_provider_defaults 内消化）
    description = (
        "生图统一工具。mode='batch'（默认）：面向故事板草稿批量出图，"
        "target 传 all_keyElements / all_shots / 具体 draft_id，"
        "系统自动把草稿 sceneRefs 引用的元素概念图注入为参考图；"
        "mode='single'：按 prompt 生成单张图片并返回图片地址，每轮限一次。"
        "生成渠道优先级：用户当前消息显式指定 > 草稿自身参数 > 全局设置默认渠道，"
        "系统自动注入，规格文档与 Skill 不承载渠道参数。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageInput

    def apply_provider_defaults(self, args: Dict[str, Any], ctx: ProviderInjectionContext) -> None:
        """I-3：single/batch 双分支 provider 注入下沉到工具自身（调度器不感知形态）。

        优先级 = 草稿自身（中间面板直接选择，ctx.image_provider）> 全局设置
        （spec_media_preference）；single 补 adapter_provider/aspect_ratio，batch 补
        provider_id/model，防传空导致「供应商 '' 未配置」。经 provider_config 端口
        访问声明（依赖倒置，与 _execute_batch 同口径，保 monkeypatch 可见）。"""
        single = str(args.get("mode") or "batch").strip().lower() == "single"
        if single:
            if not str(args.get("adapter_provider") or "").strip():
                _sp, _sm = ports.provider_config_port().spec_media_preference(ctx.state)
                if ctx.image_provider:
                    args["adapter_provider"] = ctx.image_provider
                    logger.info("[image_generate] single provider 注入（草稿选择）: {}", ctx.image_provider)
                elif _sp:
                    args["adapter_provider"] = _sp
                    logger.info("[image_generate] single provider 注入（全局设置）: {}", _sp)
            if ctx.image_aspect_ratio and not args.get("aspect_ratio"):
                args["aspect_ratio"] = ctx.image_aspect_ratio
                logger.info("[image_generate] single 画幅注入（草稿选择）: {}", ctx.image_aspect_ratio)
        elif not str(args.get("provider_id") or "").strip():
            spec_pid, spec_model = ports.provider_config_port().spec_media_preference(ctx.state)
            if ctx.image_provider:
                args["provider_id"] = ctx.image_provider
                logger.info("[image_generate] batch provider 注入（草稿选择）: {}", ctx.image_provider)
            elif spec_pid:
                args["provider_id"] = spec_pid
                if spec_model and not str(args.get("model") or "").strip():
                    args["model"] = spec_model
                logger.info("[image_generate] batch provider 注入（全局设置）: {}/{}", spec_pid, spec_model)

    async def aexecute(self, params: GenerateImageInput) -> ToolResult:
        mode = str(params.mode or "batch").strip().lower()
        if mode == "single":
            return await self._execute_single(params)
        if mode != "batch":
            return ToolResult(
                success=False,
                error="Validation Error: mode 取值非法，仅支持 batch（批量）| single（单张应急）",
                error_code="validation", retryable=False,
            )
        return await self._execute_batch(params)

    async def _execute_single(self, params: GenerateImageInput) -> ToolResult:
        """single 模式：按提示词直出单张图（对话内单张应急轨）。"""
        if not (params.prompt or "").strip():
            return ToolResult(
                success=False,
                error="Validation Error: mode='single' 必须提供 prompt",
                error_code="validation", retryable=False,
            )
        if not (params.adapter_provider or "").strip():
            # T5：供应商未配置=入参/配置问题，改参（补 provider）后可重试
            return ToolResult(
                success=False,
                error="尚未配置生成供应商，请先到「设置」中配置生成供应商",
                error_code="validation", retryable=False,
            )
        try:
            adapter = AdapterFactory.get_adapter("image_generation", params.adapter_provider)
            extra: Dict[str, Any] = {}
            if params.aspect_ratio:
                extra["aspect_ratio"] = params.aspect_ratio
            result = await adapter.generate_image(
                prompt=params.prompt,
                reference_image=params.reference_image,
                **extra,
            )
            if result.status == "failed":
                # T5：上游明确失败，单次可再试（换参/重试一次）
                return ToolResult(
                    success=False, error=result.error_msg,
                    error_code="upstream", retryable=True,
                )
            # 同步完成的适配器（如 agy CLI 直接出图）：初始结果已带图片 URL，
            # 直接进入轮询会调到 fetch_result 拿到空列表，导致 image_urls 丢失
            if result.status in ("succeeded", "completed") and result.image_urls:
                completed_result = result
            else:
                completed_result = await wait_until_complete(adapter, result.task_id)
            return ToolResult(
                success=True,
                data={
                    "task_id": completed_result.task_id,
                    "image_urls": completed_result.image_urls,
                },
            )
        except GenerationCancelled:
            # 取消穿透：不得被错误兜底吞咽为失败结果，上抛收敛至停止分支
            raise
        except Exception as e:
            # T5：未分类异常兜底，不标可重试（防盲重试空转）
            return ToolResult(success=False, error=str(e), error_code="upstream")

    async def _execute_batch(self, params: GenerateImageInput) -> ToolResult:
        from src.video_agent.config import settings
        from src.video_agent.state import storyboard_ops as ops

        # 经 generation 端口消费（依赖倒置），消灭 tools→web 反向依赖
        gen = ports.generation_port()
        submit_image_task = gen.submit_image_task
        wait_image_task = gen.wait_image_task

        # 聊天框出图开关：关 = Agent 在对话中不主动触发生图；
        # T5：开关关闭属环境配置问题，原参重试无效，需用户到全局设置开启后重试
        if not settings.chat_image_enabled:
            return ToolResult(success=False, error=(
                "聊天框出图已在全局设置中关闭，如需生图请先在顶栏「全局设置」开启「聊天框出图」。"
            ), error_code="other")

        svc = StateManager.get_instance()
        state = svc.state_dict

        # 收集目标 (group, draft, draft_type) 三元组（只读，无需加锁）
        targets: List[tuple] = []
        if params.target in ("all_keyElements", "all_keyelements"):
            for g in state.get(CAT_KEY_ELEMENTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append((g, d, "keyElement"))
        elif params.target in ("all_shots", "all_shot"):
            for g in state.get(CAT_SHOTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append((g, d, "shot"))
        else:
            # T2 第一步：混合集 target 结构化校验——具体 draft_id 经
            # storyboard_ops.find_draft 既有路径校验存在性（引用不复制）；
            # 格式非法/未命中统一 error_code="validation"，文案附合法取值说明与采样
            target = str(params.target or "").strip()
            hint = f"{_TARGET_VALID_HINT}。可用 draft_id 采样: {_sample_draft_ids(state)}"
            if not _TARGET_ID_RE.match(target) or target == "current":
                return ToolResult(
                    success=False,
                    error=f"Validation Error: target 取值 '{target}' 格式非法（不得含空格/中文）。{hint}",
                    error_code="validation", retryable=False,
                )
            hit = ops.find_draft(state, target)
            if not hit:
                return ToolResult(
                    success=False,
                    error=f"Validation Error: target '{target}' 未命中任何草稿。{hint}",
                    error_code="validation", retryable=False,
                )
            group, draft = hit
            if not (draft.get("prompt") or "").strip():
                return ToolResult(
                    success=False,
                    error=f"Validation Error: 草稿 '{target}' 没有提示词，请先写入提示词（storyboard_patch_draft）再生图",
                    error_code="validation", retryable=False,
                )
            cat = next(
                (c for c in ALL_CATEGORIES_TUPLE
                 if any(g.get("id") == group.get("id") for g in state.get(c, []) or [])),
                CAT_KEY_ELEMENTS,
            )
            targets.append((group, draft, "shot" if cat == CAT_SHOTS else "keyElement"))

        if not targets:
            # T5：目标参数未命中带提示词的草稿，属入参定位问题（改参可重试）
            return ToolResult(
                success=False,
                error=(f"Validation Error: 未找到有提示词的草稿。{_TARGET_VALID_HINT}；"
                       f"可用 draft_id 采样: {_sample_draft_ids(state)}"),
                error_code="validation", retryable=False,
            )

        # 供应商回退链（唯一权威源=全局设置）：LLM 参数 → 全局设置 → 草稿自带 providerId
        # → 配置中首个可用生图供应商；LLM 常传空 provider，不回退会报「供应商 '' 未配置」
        provider_id = resolve_provider_ref(str(params.provider_id or "").strip())
        model = str(params.model or "").strip()
        if not provider_id:
            spec_pid, spec_model = spec_media_preference(state)
            if spec_pid:
                provider_id = spec_pid
                model = model or spec_model
                logger.info(f"[image_generate] provider 未指定，按全局设置回退: {spec_pid}/{model}")
        if not provider_id:
            for _g, d, _t in targets:
                pid = resolve_provider_ref(str(d.get("imageProviderId") or d.get("providerId") or "").strip())
                if pid:
                    provider_id = pid
                    logger.info(f"[image_generate] provider 未指定，回退草稿自带供应商: {pid}")
                    break
        if not provider_id:
            if settings.default_image_provider_id:
                provider_id = settings.default_image_provider_id
                model = model or settings.default_image_model
                logger.info(f"[image_generate] provider 未指定，回退全局设置默认出图渠道: {provider_id}/{model}")
        if not provider_id:
            provider_id, fb_model = await first_available_image_provider_async()
            if provider_id:
                model = model or fb_model
                logger.info(f"[image_generate] provider 未指定，回退配置首个可用生图供应商: {provider_id}/{model}")
        if not provider_id:
            # T5：供应商回退链全部落空属环境配置问题，原参重试无效，需先配置生图供应商再重试
            return ToolResult(success=False, error=(
                "当前工作区未配置任何可用的生图供应商，请先在 API 配置页添加供应商与 API Key。"
            ), error_code="other")

        # 规格制作参数：图片分辨率由规格文档优先，
        # 其次草稿自带，最后全局默认（回退链与供应商链口径一致）
        spec_image_res = str(spec_production_params(state).get("image_resolution") or "")

        # 统一任务管线提交：提交即记录生成日志 + SSE 点亮前端卡片读秒，
        # 与手动/批量生图行为一致；全部提交后再逐个等结果（任务是并发的）
        submitted: List[tuple] = []  # (draft, task_id)
        for group, draft, dtype in targets:
            refs = ops.resolve_scene_refs(state, group) if group else []
            eff_resolution = (
                spec_image_res or str(draft.get("imageResolution") or "")
                or settings.default_image_resolution or "1K"
            )
            draft["imageResolution"] = eff_resolution  # 参数栏同步可见
            task_id = submit_image_task(
                state, draft, provider_id, model, refs,
                aspect_ratio=(draft.get("aspectRatio") or "16:9"),
                resolution=eff_resolution,
                on_failure_save=svc.save_debounced,
                draft_type=dtype,
            )
            submitted.append((draft, task_id))
        svc.save()  # 持久化「生成中」标签与草稿参数回写
        
        # 实际使用的供应商/模型回写草稿（imgUrl/tag 已由任务管线 writeback 处理）
        async with svc.lock:
            for draft, _ in submitted:
                if provider_id:
                    draft["imageProviderId"] = provider_id
                    draft["providerId"] = provider_id
                if model:
                    draft["imageModel"] = model
                    draft["model"] = model
            svc.save()

        # 提交即返回：结果由前端 SSE + 轮询跟踪，
        # 避免 N×600s 工具轮阻塞 agent 循环
        return ToolResult(success=True, data={
            "submitted": len(submitted),
            "task_ids": [tid for _, tid in submitted],
            "detail": f"已提交 {len(submitted)} 个生图任务，结果将通过 SSE/轮询通知",
        })


class WorkflowPauseTool(BaseTool):
    name = "workflow_pause"
    risk = "medium"  # §2.7：写交互暂停态，用户回应即可撤销
    detail_tier = "expand"  # 关键交互：暂停请求展开可见输入
    description = (
        "暂停工作流并请求用户确认——真正的停 = 调用本工具（只在正文里写「请确认」不算暂停），"
        "成功发行后本轮立即结束。用于所用 Skill 声明的暂停点，或需向用户问询/确认时。"
        "同阶段收尾类工具（落账/写档）可与之同批提交（先收尾后暂停），无需为暂停单独跑一轮。"
        "message 是给用户的补充说明（卡片问句由系统按阶段自动生成，阶段成果由系统挂事件卡展示）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return WorkflowPauseInput

    async def aexecute(self, params: WorkflowPauseInput) -> ToolResult:
        """只提交审批事实，不写暂停状态（问即停事务写入）：
        awaiting_confirmation/confirmation_message/active_pause 由发行点
        （core/fc_tool_runner.py）在发行确认后经 reduce_interaction 一次
        原子写入，防「工具已写状态但卡片未达用户」的半提交态。"""
        return ToolResult(success=True, data={"paused": True, "message": params.message})


class RunSubagentInput(BaseModel):
    task: str = Field(
        ...,
        description="交给子代理的完整任务说明：目标、涉及范围（哪些章节/哪批卡）、"
        "验收标准。子代理看不到本对话，也不会看到已确认的规格与 Skill 章节——"
        "需它遵守的规范要点写进本说明（并告知 Skill 名，它可自行 read_skill 取读）。",
    )


class RunSubagentTool(BaseTool):
    name = "run_subagent"
    risk = "medium"  # 写工作台状态但可撤销（子级经故事板/文档工具落账）
    detail_tier = "expand"  # 关键控制流：展开可见委派任务与回摘要
    # 无 provider_kind / costly=False / parallel_safe=False（独占串行，屏障）。
    # 2026-09-11 批③A：具名类型退役 → 通用单一子代理（按工具面白名单限权）。
    # 委派策略的完整表述在主对话 `subagent` system 段（prompts/planner/subagent.md
    # :: SUBAGENT_POLICY），工具描述只留一句核心契约，不再内嵌花名册。
    # 2026-09-12 用户裁决（对齐外部标杆）：description 只写正面契约，
    # 删「不要用于确认类/花钱生成」禁令句——子级白名单无确认工具、无生成工具，
    # 结构上已锁死；说明层禁令经 3333 项目实证会吓退模型不敢委派。
    description = (
        "把一段自包含、可独立完成的批量工作委派给子代理：它在自己的上下文里"
        "连续执行到完成，不占用本对话的上下文，只回结果摘要、不回中间步骤。"
        "给它一份完整、独立的任务说明——它看不到本对话。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return RunSubagentInput

    async def aexecute(self, params: RunSubagentInput) -> ToolResult:
        """正常不经此：run_subagent 由 core/fc_tool_runner._dispatch_tool 在派发前
        经注入的 subagent_launcher 拦截执行（同 workflow_pause 属控制流伪工具）。
        直达本方法说明运行时未装配子代理能力，明确失败不静默。"""
        return ToolResult(
            success=False,
            error="run_subagent 由运行时执行；当前子代理能力未装配，不可用。",
            error_code="validation",
        )


# ---------- 注册 ----------

def register_document_tools():
    """注册文档 & 生成 & 暂停 Tool"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(DocumentWriteTool())
    ToolManager.register(ReadUploadedDocTool())
    ToolManager.register(ReadSkillTool())
    ToolManager.register(ListSkillsTool())
    ToolManager.register(GetSkillAssetTool())
    ToolManager.register(ReadProjectDocTool())
    ToolManager.register(ImageGenerateTool())
    ToolManager.register(WorkflowPauseTool())
    ToolManager.register(RunSubagentTool())
    logger.info("[Tools] 9 document/skill/generation/workflow tools registered")
