"""媒体生成族（九轮 B3 自 exec_tools.py 切出，R4a 拆分模式延续）。

AudioGenerateTool + VideoAssemblerTool。exec_tools 尾部 re-export 保持
既有引用路径不变（宪法 §12 登记壳；零行为变更，代码逐字迁移）。
"""
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
    ALL_CATEGORIES_TUPLE, ASSEMBLY_PLAN_DOC_NAME, CAT_AUDIO_ITEMS,
    CAT_KEY_ELEMENTS, CAT_SHOTS,
)
from src.video_agent.config import settings
from src.video_agent.utils import gen_id
from src.video_agent.web import generation as _gen
from src.video_agent.web.generation import (
    call_chat_completion,
)
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
    _generate_soft_spec_candidates,
    _llm_json_call,
)
from src.video_agent.skill_runtime.exec_common import SkillToolInput


class AudioGenerateInput(SkillToolInput):
    target: str = Field("all_audio", description="目标音频草稿范围（默认 all_audio）")
    user_text: str = Field("", description="用户附加要求（可选）")


class VideoAssemblerInput(SkillToolInput):
    user_text: str = Field("", description="用户附加要求（可选）")


class AudioGenerateTool:
    name = "audio_generate"
    description = (
        "按当前 Skill 的「生成」章节为音频层生成可执行音频规划（旁白/BGM/音效），"
        "并支持绑定用户已上传音频；当前版本不调用真实 TTS/BGM 生成文件。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return AudioGenerateInput

    async def aexecute(self, params: AudioGenerateInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 audio_generate 执行器")
        svc = StateManager.get_instance()
        state_ctx = _build_state_context(svc)
        user = (
            "请按注入章节为项目的音频层生成可执行的音频规划："
            "若用户已上传音频素材，输出 bind_asset / update_draft 动作将其绑定到对应音频草稿；"
            "否则输出 update_draft/add_draft 写入旁白/BGM/音效的规划文本（含内容、音色、时间范围），"
            "不要声称已生成音频文件。只输出 studio-actions JSON 数组。\n\n"
            f"目标范围：{params.target}\n用户附加要求：{params.user_text or '无'}\n\n"
            f"当前工作台状态：\n{state_ctx}"
        )
        entry = resolve_entry(params.skill_name)
        skill_content = entry.content if entry else ""
        extra = (
            "【本阶段边界】本阶段只生成音频规划或绑定用户已上传音频，"
            "不调用真实 TTS/BGM 生成文件，也不触发生图/生视频动作。"
        )
        try:
            applied, warnings = await _executor_actions_from_llm(
                self.name, params.skill_name, user, skill_content, svc,
                max_tokens=4096,
                provider=params.chat_provider, model=params.chat_model,
                system_extra=extra,
            )
        except Exception as e:
            return exec_common.SkillToolResult(success=False, error=str(e))
        if not applied:
            return exec_common.SkillToolResult(success=False, error="；".join(warnings) or "音频规划未产出任何更新")
        return exec_common.SkillToolResult(success=True, data={
            "applied": applied,
            "detail": f"已生成音频规划（{applied} 个更新；未生成音频文件）",
            "warnings": warnings,
        })


class VideoAssemblerTool:
    name = "video_assembler"
    description = (
        "按当前 Skill 的「组装导出」章节，输出最终成片的素材清单、时间轴顺序与组装建议，"
        "供画布/剪辑软件组装；当前版本不自动合成视频。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return VideoAssemblerInput

    async def aexecute(self, params: VideoAssemblerInput) -> SkillToolResult:
        section = tool_sections(params.skill_name, self.name)
        if not section and params.skill_name:
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name}」未注册 video_assembler 执行器")
        svc = StateManager.get_instance()
        state = svc.state_dict
        lines: List[str] = []
        lines.append("# 最终成片组装方案")
        lines.append("")
        lines.append("## 分镜时间轴（按顺序）")
        shot_no = 0
        for g in state.get(CAT_SHOTS) or []:
            for d in g.get("drafts") or []:
                if not (d.get("videoUrl") or d.get("imgUrl")):
                    continue
                shot_no += 1
                url = d.get("videoUrl") or d.get("imgUrl") or ""
                lines.append(
                    f"{shot_no}. {g.get('title') or d.get('label') or '分镜'} "
                    f"（时长 {d.get('duration') or g.get('duration') or '?'}，素材 {url}）"
                )
        if shot_no == 0:
            lines.append("（暂无已生成的分镜视频素材）")
        lines.append("")
        lines.append("## 音频层")
        audio_no = 0
        for g in state.get(CAT_AUDIO_ITEMS) or []:
            for d in g.get("drafts") or []:
                audio_no += 1
                url = d.get("audioUrl") or ""
                lines.append(
                    f"{audio_no}. {g.get('title') or d.get('label') or '音频'} "
                    f"（范围 {d.get('timeRange') or g.get('timeRange') or '全局'}，素材 {url or '未绑定'}）"
                )
        if audio_no == 0:
            lines.append("（暂无音频层素材）")
        lines.append("")
        lines.append("## 组装建议")
        lines.append("- 按上述分镜顺序排列视频轨道，音频按时间范围叠加；")
        lines.append("- 字幕后期添加，不在生成阶段写入画面；")
        if section:
            lines.append("- 组装注意事项（来自 Skill 章节）：")
            for l in section.splitlines():
                l = l.strip()
                if l:
                    lines.append(f"  - {l}")
        plan = "\n".join(lines)
        # 批 6：组装方案落盘为客观产物（幂等 upsert）——assembly 阶段完成探针
        # 据此区分「已生成未组装」与「已组装」（Stop≠Done≠Verified：看产物证据）
        docs = state.setdefault("documents", [])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for d in docs:
            if d.get("name") == ASSEMBLY_PLAN_DOC_NAME:
                d["content"] = plan
                d["updated_at"] = now
                break
        else:
            docs.insert(0, {
                "id": gen_id("doc"), "name": ASSEMBLY_PLAN_DOC_NAME,
                "content": plan, "created_at": now, "updated_at": now,
            })
        svc.save_debounced()
        return exec_common.SkillToolResult(success=True, data={
            "plan": plan,
            "detail": f"已生成组装方案并写入 {ASSEMBLY_PLAN_DOC_NAME}（素材清单 + 时间轴顺序），可在画布中按此组装导出",
        })


