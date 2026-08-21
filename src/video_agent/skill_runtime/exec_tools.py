"""Skill 独立执行器（上传即注册后的真实工具运行时）。

每个执行器只注入自己对应的 Skill 章节（registry.tool_sections），
独立完成「读输入 → LLM 调用/组装 → 结构化校验 → 写状态」。
LLM 类执行器走结构化输出轨（response_format=json_object + 硬校验）。
"""
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type

from loguru import logger
from pydantic import BaseModel, Field

from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.models import (
    ALL_CATEGORIES_TUPLE, CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS,
)
from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core.token_budget import output_limit_for_model
from src.video_agent.skill_runtime.progress import (
    emit_progress,
    emit_state_refresh,
    emit_timeline_note,
    format_eta,
)
from src.video_agent.skill_runtime.registry import (
    fallback_skill_from_state,
    resolve_entry,
    tool_available,
    tool_sections,
)

from src.video_agent.skill_runtime import exec_common
from src.video_agent.skill_runtime import exec_spec



from src.video_agent.skill_runtime.exec_common import (
    SkillToolResult,
    _apply_actions,
    _build_script_hint,
    _executor_thinking,
    _find_uploaded_doc,
    _fmt_num,
    _is_truncated,
    _read_spec_doc,
    _resolve_cascade_fast,
    _resolve_chat_provider,
    _rollback_split_groups,
    _skill_system_prompt,
    _spec_override_clauses,
    _split_kinds_for_section,
    _stream_actions_progressive,
)

from src.video_agent.skill_runtime.exec_spec import (
    _build_state_context,
    _executor_actions_from_llm,
    _llm_json_call,
)


from src.video_agent.skill_runtime.exec_common import SkillToolInput  # 下沉后 re-export 保路径


class ScriptAnalyzeInput(SkillToolInput):
    doc_name: str = Field("", description="上传文档名称（剧本/音乐等，与清单一致）")
    doc_id: str = Field("", description="上传文档 ID（可选，doc_name 为空时用）")
    user_text: str = Field("", description="用户附加要求（可选）")


class StoryboardSplitInput(SkillToolInput):
    user_text: str = Field("", description="用户附加要求（可选）")




class ScriptAnalyzeTool:
    name = "script_analyze"
    description = (
        "解析用户上传的剧本/素材（文本/PDF/图片），输出结构化要点。"
        "Skill 对应章节自动注入，无需手动读取全文。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ScriptAnalyzeInput

    async def aexecute(self, params: ScriptAnalyzeInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 script_analyze 执行器")
        svc = StateManager.get_instance()
        doc = exec_common._find_uploaded_doc(svc.state_dict, params.doc_name, params.doc_id)
        if doc is None:
            return exec_common.SkillToolResult(success=False, error="未找到上传的剧本/素材文档，请先上传文件（txt/md/pdf 或图片）")
        content = str(doc.get("content") or "")
        if not content:
            return exec_common.SkillToolResult(success=False, error="上传文档没有可解析的文本内容（扫描版 PDF 需改用文本/图片上传）")
        # 幂等——同一剧本（内容指纹未变）且无附加要求时直接复用
        # 既有分析（零 LLM），防冗余重跑导致的耗时与正文重复总结
        _fp = hashlib.sha1(content[:12000].encode("utf-8", "ignore")).hexdigest()[:16]
        cached = svc.state_dict.get("analysis") or {}
        if (
            not str(params.user_text or "").strip()
            and cached.get("doc_name") == doc.get("name")
            and cached.get("fingerprint") == _fp
            and str(cached.get("summary") or "").strip()
        ):
            logger.info("[SkillExec] script_analyze 幂等命中：剧本未变，复用既有分析")
            return exec_common.SkillToolResult(success=True, data={
                "summary": cached["summary"],
                "key_points": cached.get("key_points") or [],
                "cached": True,
                "detail": (
                    # 回喂只陈述客观事实，展示职责归层 9 代码
                    f"《{doc.get('name')}》剧本未变更，复用既有分析。"
                    f"一句话总结：{cached['summary']}"
                ),
            })
        user = (
            f"请分析以下上传素材《{doc.get('name')}》并输出 JSON：\n"
            "{\"summary\": \"一句话故事总结\", \"key_points\": [\"关键信息要点...\"]}\n\n"
            f"素材全文：\n{content[:exec_common._script_inject_limit()]}\n\n"
            f"用户附加要求：{params.user_text or '无'}"
        )
        # 长任务进度上报：独立 LLM 调用前告知用户在等什么
        await emit_progress("正在解析剧本素材（独立 LLM 分析，预计数十秒）…")
        try:
            data = await exec_spec._llm_json_call(
                exec_common._skill_system_prompt(self.name, params.skill_name),
                user,
                max_tokens=4096,
                provider=params.chat_provider,
                model=params.chat_model,
            )
        except Exception as e:
            return exec_common.SkillToolResult(success=False, error=str(e))
        summary = str(data.get("summary") or "")
        key_points = data.get("key_points") or []
        if not summary:
            return exec_common.SkillToolResult(success=False, error="执行器未返回故事总结")
        svc.state_dict["analysis"] = {
            "doc_name": doc.get("name"),
            "summary": summary,
            "key_points": key_points,
            "fingerprint": _fp,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        svc.save_debounced()
        # 软参数候选出题已分离为 collect_spec 独立节点（Rule2 v6 批3）：
        # 由 workflow runtime 直跑分析后调度，不再藏进本工具耗时。
        return exec_common.SkillToolResult(success=True, data={
            "summary": summary,
            "key_points": key_points,
            # 去祈使化（总结展示归属机械链路，不在本层教模型）
            "detail": f"已分析《{doc.get('name')}》。一句话总结：{summary}",
        })


# 任务词与故事板拆解域实现体切出至 exec_split.py（文件瘦身）；
# 本文件尾部 re-export 保持既有引用路径不变（登记壳，见尾块注释）。

class StoryboardKeyElementsTool:
    name = "storyboard_key_elements"
    description = (
        "按当前 Skill 的「故事板设计·关键元素」章节，把剧本拆解为关键元素"
        "（角色/场景/道具）分组并写入工作台。只建结构，不建分镜与音频。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return StoryboardSplitInput

    async def aexecute(self, params: StoryboardSplitInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 {self.name} 执行器")
        return await _run_storyboard_split(self.name, params, _KE_TASK, _KE_BOUNDARY)


class StoryboardShotsTool:
    name = "storyboard_shots"
    description = (
        "按当前 Skill 的「故事板设计·镜头」章节，基于已确认的关键元素拆解分镜"
        "（镜头列表）分组并写入工作台。只建分镜结构，不改关键元素与音频。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return StoryboardSplitInput

    async def aexecute(self, params: StoryboardSplitInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 {self.name} 执行器")
        return await _run_storyboard_split(self.name, params, _SHOT_TASK, _SHOT_BOUNDARY)


class StoryboardAudioTool:
    name = "storyboard_audio"
    description = (
        "按当前 Skill 的「故事板设计·音频」章节，基于故事板拆解音频层"
        "（背景音乐/旁白/音效）分组并写入工作台。只建音频结构，不改关键元素与分镜。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return StoryboardSplitInput

    async def aexecute(self, params: StoryboardSplitInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 {self.name} 执行器")
        return await _run_storyboard_split(self.name, params, _AUDIO_TASK, _AUDIO_BOUNDARY)


def _resolve_section_text(entry: Optional[Any], section: str) -> str:
    """通用章节解析：stage key → flova tag → 标题关键字 → 任意 <tag>。

    未解析返回空串（调用方报错并附可用章节清单）。
    """
    if entry is None or not (section or "").strip():
        return ""
    sec = section.strip()
    if sec in (entry.sections or {}):
        return entry.sections[sec]
    from src.video_agent.web.skill_docs import SECTION_TAG_STAGES, _stage_from_heading

    low = sec.lower()
    for mapper in (SECTION_TAG_STAGES.get(low, ""), _stage_from_heading(sec)):
        stages = mapper if isinstance(mapper, tuple) else (mapper,)
        for s in stages:
            if s and s in (entry.sections or {}):
                return entry.sections[s]
    # 任意 <tag> 章节直取（通用：白名单外的自定义 tag 也能跑）
    m = re.search(rf"<{re.escape(low)}>(.*?)</{re.escape(low)}>", entry.content or "", re.S | re.I)
    if m:
        return m.group(1).strip()
    return ""


class SkillSectionRunInput(SkillToolInput):
    section: str = Field(..., description="章节标识：stage key（如 storyboard_ke）/ flova tag（如 write_media_prompt）/ 任意自定义 <tag> / 标题关键字")
    task: str = Field(..., description="本章节要执行的具体任务描述（系统自动附工作台状态 JSON）")


class SkillSectionRunTool:
    name = "skill_section_run"
    description = (
        "通用章节执行器：把当前 Skill 的任意章节作为唯一依据注入独立执行器，"
        "LLM 产出 studio-actions 后由系统应用并校验。适用于没有专属执行器的章节"
        "（自定义 tag / 本地改写标题）。返回 applied 数量与警告。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return SkillSectionRunInput

    async def aexecute(self, params: SkillSectionRunInput) -> SkillToolResult:
        svc = StateManager.get_instance()
        skill = params.skill_name or fallback_skill_from_state(svc.state_dict)
        entry = resolve_entry(skill)
        if entry is None:
            return exec_common.SkillToolResult(success=False, error=f"Skill「{skill or '未指定'}」未注册，请先选中 Skill")
        section_text = _resolve_section_text(entry, params.section)
        if not section_text:
            avail = ", ".join(sorted((entry.sections or {}).keys())) or "（无）"
            return exec_common.SkillToolResult(
                success=False,
                error=f"章节「{params.section}」未解析；可用 stage：{avail}",
            )
        user_prompt = (
            f"任务：{params.task}\n\n== 当前工作台状态 JSON ==\n{_build_state_context(svc)}"
        )
        applied, warnings = await _executor_actions_from_llm(
            self.name, skill, user_prompt, entry.content, svc,
            section_override=section_text,
            provider=params.chat_provider, model=params.chat_model,
        )
        if applied:
            return exec_common.SkillToolResult(success=True, data={"applied": applied, "warnings": warnings})
        return exec_common.SkillToolResult(success=False, error="; ".join(warnings or ["执行器未产出有效操作"]))


# 执行器→工作台产出客观判定（阶段同批完成度机器读出用）
_EXECUTOR_DONE_PROBES = {
    "script_analyze": lambda st: bool((st.get("analysis") or {}).get("summary")),
    "storyboard_key_elements": lambda st: bool(st.get(CAT_KEY_ELEMENTS)),
    "storyboard_shots": lambda st: bool(st.get(CAT_SHOTS)),
    "storyboard_audio": lambda st: bool(st.get(CAT_AUDIO_ITEMS)),
}


def _stage_done_by_executors(executors: List[str], state: Dict[str, Any]) -> Optional[bool]:
    """声明同批的阶段：全部执行器产出齐备才算完成；
    含无法客观判定的执行器时返回 None（回落既有判定，不猜）。"""
    probes = [_EXECUTOR_DONE_PROBES.get(t) for t in executors]
    if not executors or not all(probes):
        return None
    return all(p(state) for p in probes)


# 媒体生成族执行器实现体迁 exec_media_writer / exec_media_gen（注册表引用所需）
from src.video_agent.skill_runtime.exec_media_writer import WriteMediaPromptTool
from src.video_agent.skill_runtime.exec_media_gen import AudioGenerateTool, VideoAssemblerTool

EXECUTOR_TOOL_CLASSES = {
    "script_analyze": ScriptAnalyzeTool,
    "storyboard_key_elements": StoryboardKeyElementsTool,
    "storyboard_shots": StoryboardShotsTool,
    "storyboard_audio": StoryboardAudioTool,
    "write_media_prompt": WriteMediaPromptTool,
    "audio_generate": AudioGenerateTool,
    "video_assembler": VideoAssemblerTool,
}


def build_executor_tool(name: str):
    """按动作名构造执行器实例（文本动作轨用）；未知名返回 None。"""
    cls = EXECUTOR_TOOL_CLASSES.get(name)
    return cls() if cls else None
# 补：角标排序家族实现体在 exec_common，此处 re-export 保持既有直引
from src.video_agent.skill_runtime.exec_common import (
    _BADGE_CATEGORY_KEYS,
    _badge_category_rank,
    _sort_key_elements_by_badge,
)
# 任务词与故事板拆解域实现体在 exec_split.py，此处 re-export 保持
# 既有引用路径不变（宪法 §12 登记壳；壳到期制登记：长期保留·架构承重——
# executors/__init__ 与测试经 exec_tools.* / executors.* 引用，迁移需全量
# 改引用并同步 test patch 目标）
from src.video_agent.skill_runtime.exec_split import (
    _AUDIO_BOUNDARY,
    _AUDIO_TASK,
    _KE_BOUNDARY,
    _KE_SELFCHECK_BOUNDARY,
    _KE_TASK,
    _SHOT_BOUNDARY,
    _SHOT_TASK,
    _run_storyboard_split,
    _selfcheck_key_elements,
)

# 媒体提示词/媒体生成族实现体迁出后 re-export，保持既有引用路径不变
#（宪法 §12 登记壳；壳到期制登记：长期保留·架构承重——executors/__init__ 与
# 测试经 exec_tools.* 引用，迁移需全量改引用并同步 test patch 目标）
from src.video_agent.skill_runtime.exec_media_writer import (
    WriteMediaPromptInput,
    _coverage_categories,
    _prompt_coverage_note,
    _PROMPT_BATCH_SIZE,
    _PROMPT_BATCH_MAX_TOKENS,
    _PROMPT_MAX_BATCHES,
    _pending_prompt_groups,
    _production_param_note,
    _write_prompt_batch,
)
from src.video_agent.skill_runtime.exec_media_gen import (
    AudioGenerateInput,
    VideoAssemblerInput,
)
