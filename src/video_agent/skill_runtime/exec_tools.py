"""Skill 独立执行器（上传即注册后的真实工具运行时）。

每个执行器只注入自己对应的 Skill 章节（registry.tool_sections），
独立完成「读输入 → LLM 调用/组装 → 结构化校验 → 写状态」。
LLM 类执行器不依赖模型 function calling，Planner/文本动作轨都可调用。
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
from src.video_agent.config import settings
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
    _parse_actions_from_text,
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


class SkillToolInput(BaseModel):
    skill_name: str = Field("", description="当前选中 Skill 名称（系统自动注入，一般无需填写）")
    chat_provider: str = Field("", description="当前对话使用的聊天供应商（系统自动注入，与主模型一致）")
    chat_model: str = Field("", description="当前对话使用的聊天模型（系统自动注入，与主模型一致）")


class ScriptAnalyzeInput(SkillToolInput):
    doc_name: str = Field("", description="上传文档名称（剧本/音乐等，与清单一致）")
    doc_id: str = Field("", description="上传文档 ID（可选，doc_name 为空时用）")
    user_text: str = Field("", description="用户附加要求（可选）")


class StoryboardSplitInput(SkillToolInput):
    user_text: str = Field("", description="用户附加要求（可选）")


class WriteMediaPromptInput(SkillToolInput):
    target: str = Field("", description="目标范围：all_keyElements / all_shots / all_audio / 具体 group_id、draft_id（空 = 全部待编写）")
    overwrite: bool = Field(
        False,
        description="重写模式：用户说重写/重新编写/重写一遍时必须传 true。"
                    "true 时目标范围内已有提示词的分组也纳入重写（直接覆盖，不先清空，"
                    "中断不丢旧提示词）；false 维持补写语义（只写没有提示词的分组）",
    )
    user_text: str = Field("", description="用户附加要求（可选）")


class AudioGenerateInput(SkillToolInput):
    target: str = Field("all_audio", description="目标音频草稿范围（默认 all_audio）")
    user_text: str = Field("", description="用户附加要求（可选）")


class VideoAssemblerInput(SkillToolInput):
    user_text: str = Field("", description="用户附加要求（可选）")


class ScriptAnalyzeTool:
    name = "script_analyze"
    description = (
        "解析用户上传的剧本/素材（文本/PDF/图片），输出一句话故事总结与关键信息要点。"
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
        user = (
            f"请分析以下上传素材《{doc.get('name')}》并输出 JSON：\n"
            "{\"summary\": \"一句话故事总结\", \"key_points\": [\"关键信息要点...\"]}\n\n"
            f"素材全文：\n{content[:12000]}\n\n"
            f"用户附加要求：{params.user_text or '无'}"
        )
        # 长任务进度上报（M6）：独立 LLM 调用前告知用户在等什么
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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        svc.save_debounced()
        # 软参数候选出题（888 豪华版）：声明 spec_wizard 的 Skill 才生成；
        # 内层模型按剧本给六维度出候选，校验后落 interaction.spec_soft_candidates，
        # 收集向导渲染；失败/校验不过静默回落平台默认候选，不阻断主流程
        await _generate_soft_spec_candidates(
            svc, params.skill_name, params.chat_provider, params.chat_model,
            summary, content,
        )
        return exec_common.SkillToolResult(success=True, data={
            "summary": summary,
            "key_points": key_points,
            "detail": (
                f"已分析《{doc.get('name')}》。一句话总结：{summary} "
                "（请在回复正文中把这句总结原样讲给用户）"
            ),
        })


_KE_TASK = (
    "把项目拆解为关键元素（角色/场景/道具）。每项为 add_group，group_type=keyElement，"
    "携带 title/desc/badgeLabel（字段规范与拆解粒度以注入章节和《执行铁律》为准）。"
)


_KE_BOUNDARY = (
    "【本阶段边界】本阶段只创建关键元素（keyElement）分组（title/desc）。"
    "（越界分组与内联提示词由系统自动拒收/剥离，无需自行克制）"
)


_KE_SELFCHECK_BOUNDARY = (
    "【自检任务边界】本轮是已完成的关键元素拆解的第二遍逐场核对："
    "只输出遗漏元素的 add_group keyElement 动作（带 title/desc）；没有遗漏时只输出空数组 []。"
    "（重复元素与越界分组由系统自动去重/拒收）"
)


_SHOT_TASK = (
    "基于已确认的关键元素拆解分镜（镜头列表）。每项为 add_group，group_type=shot，"
    "携带 title/shotType/sceneRefs/duration/roughDesc；sceneRefs 必须引用已有关键元素的 element_id。"
    "title 简洁概括本镜头（不超过 20 字）；roughDesc 只写一句话大概描述（不超过 80 字），"
    "逐条时间轴、对白、子镜头明细不放进 roughDesc——细节留给提示词编写阶段。"
)


_SHOT_BOUNDARY = (
    "【本阶段边界】本阶段只创建分镜（shot）分组；"
    "分镜的对话/旁白/动作结果与场景顺序必须忠实于剧本。"
    "（越界分组与内联提示词由系统自动拒收/剥离）"
)


_AUDIO_TASK = (
    "基于故事板拆解音频层（背景音乐/旁白/音效）。每项为 add_group，group_type=audio，"
    "携带 title/desc（风格、节奏、音色与时间范围）。"
)


_AUDIO_BOUNDARY = (
    "【本阶段边界】本阶段只创建音频（audio）分组。"
    "（越界分组与内联提示词由系统自动拒收/剥离）"
)


async def _selfcheck_key_elements(
    tool_name: str,
    skill_name: str,
    skill_content: str,
    script_hint: str,
    svc: StateManager,
    provider: str,
    model: str,
) -> Tuple[int, List[str]]:
    """第二遍自检：按剧本逐场核对补建遗漏的关键元素（防漏拆）。

    模型首遍拆解倾向概括收敛（网页端靠用户多轮催补，执行器需自动化这一步）；
    强制其对照已拆清单穷举核对。补建 0 个表示无遗漏，属正常结果。
    """
    if not script_hint:
        return 0, []
    existing = [
        str(g.get("title") or "").strip()
        for g in (svc.state_dict.get("keyElements") or [])
    ]
    system = exec_common._skill_system_prompt(tool_name, skill_name, _KE_SELFCHECK_BOUNDARY)
    user = (
        "以下是本项目已拆出的关键元素分组：\n"
        + ("\n".join(f"- {t}" for t in existing) if existing else "（暂无）")
        + "\n\n" + script_hint + "\n\n"
        "请按剧本逐场/逐段核对是否有遗漏的关键元素（补建粒度与克制要求按《执行铁律》第 2 条）。\n"
        "只输出遗漏元素的 studio-actions JSON 数组"
        "（add_group，group_type=keyElement，带 title/desc/badgeLabel；"
        "badgeLabel 必填：人物/场景/关键道具/载具 等类别标签）；"
        "没有遗漏时只输出 []。不要输出正文解释。"
    )
    content, _ = await _gen.call_chat_completion(
        provider,
        model,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=8192,
        timeout=180,
        thinking_level=exec_common._executor_thinking(),
    )
    actions = exec_common._parse_actions_from_text(content or "")
    if not actions:
        return 0, []
    # 客观去重：模型未对照已拆清单时，重复输出已有元素也不得重复建组
    existing_norm = {t.casefold() for t in existing if t}
    actions = [
        a for a in actions
        if not (
            str(a.get("action") or "") == "add_group"
            and str(a.get("title") or a.get("name") or "").strip().casefold() in existing_norm
        )
    ]
    if not actions:
        return 0, []
    # 阶段边界：自检轮只允许补建关键元素分组（代码校验，宪法 P2）
    applied, warnings = exec_common._apply_actions(
        svc, actions, skill_content, strip_prompts=True, only_group_type="keyElement",
    )
    if applied:
        logger.info(f"[SkillExec] 关键元素自检补漏：补建 {applied} 个遗漏元素")
    return applied, warnings








async def _run_storyboard_split(
    tool_name: str,
    params: StoryboardSplitInput,
    task_desc: str,
    boundary: str,
) -> SkillToolResult:
    """故事板三拆共用执行逻辑：注入对应章节 → LLM 产出 add_group → 应用并校验。

    关键元素拆解额外含第二遍自检补漏（防漏拆），且输出上限放宽到 16384
    （穷举 30+ 元素的 JSON 容易顶到 8192 导致模型提前收尾）。
    """
    svc = StateManager.get_instance()
    spec = exec_common._read_spec_doc(svc.state_dict)
    script_hint = exec_common._build_script_hint(svc.state_dict)
    state_ctx = _build_state_context(svc)
    # 剧本放在提示词靠后位置（近生成端）：模型对首尾注意力最高，
    # 全文贴近末尾可提升拆解穷举度；任务指令殿后确保输出格式不被稀释
    user = (
        "请严格按照注入章节的要求执行本次故事板拆解，只输出 studio-actions JSON 数组"
        "（每项为 add_group），不要输出正文解释。\n\n"
        f"规格文档：\n{spec or '（暂无规格文档，可直接按用户目标拆解）'}\n\n"
        f"用户附加要求：{params.user_text or '无'}\n\n"
        f"当前工作台状态：\n{state_ctx}\n\n"
        f"{script_hint or '（暂无剧本摘要）'}\n\n"
        f"【本次拆解任务】{task_desc}"
    )
    # 输出格式锚点（8888 事故：首拆 JSON 缺 title 字段全落默认标题）：
    # 只给关键元素拆解钉死示例，分镜/音频字段不同不适用
    if tool_name == "storyboard_key_elements":
        user += (
            "\n\n【输出格式锚点】每项动作格式如下（title 字段必须存在）：\n"
            '[{"action":"add_group","group_type":"keyElement","title":"程心",'
            '"badgeLabel":"人物","desc":"外观与声音描述…"}]'
        )
    # 制片规格覆盖注入（2222 二轮，统一 helper；原内联时长硬约束块并入此处）：
    # 规格已定的参数覆盖 Skill 章节写死的默认值（时长/分辨率/渠道）
    _override_kinds = {
        "storyboard_key_elements": ("image_resolution", "image_channel"),
        "storyboard_shots": ("duration", "video_resolution", "video_channel"),
        "storyboard_audio": (),
    }.get(tool_name, ())
    user += exec_common._spec_override_clauses(svc.state_dict, _override_kinds)
    entry = resolve_entry(params.skill_name)
    skill_content = entry.content if entry else ""
    # 输出预算（9999 事故：分镜拆解只给 8192，推理模型思考占满额度后零产出）：
    # 关键元素与分镜同档 16384（分钟级成片镜头数×单条 JSON 体量与 KE 相当），音频维持 8192
    max_tokens = 16384 if tool_name in ("storyboard_key_elements", "storyboard_shots") else 8192
    # 阶段边界的代码校验（宪法 P2）：允许的分组类别按注入章节结构自适应
    # （2222 二轮）——合并章节（Skill 说"一起设计"）放行对应多类，
    # 单一职责章节维持单类边界；逗号分隔串直接传 _apply_actions
    _split_kind = ",".join(exec_common._split_kinds_for_section(tool_name, params.skill_name))
    # 拆解前 ID 快照（回执实际建成清单 / 截断回滚用；覆盖全部放行类别）
    _ids_before = set()
    for _k in (_split_kind.split(",") if _split_kind else []):
        _cat_k = ops.category_for_group_type(_k) if _k else ""
        if _cat_k:
            _ids_before |= {g.get("id") for g in (svc.state_dict.get(_cat_k) or [])}
    provider, model = exec_common._resolve_chat_provider(params.chat_provider, params.chat_model)
    if not provider:
        return exec_common.SkillToolResult(success=False, error="当前工作区未配置可用的聊天供应商，请先在 API 配置页添加")
    # 长任务进度上报（M6）：拆解执行器单次 LLM 调用通常 30~90s，先告知在等什么
    await emit_progress(f"正在拆解故事板结构（{tool_name}，预计 30~90 秒）…")
    # 子步骤细分（2222 反馈）：时间线先记「首拆开始」，配合流式落盘批次子项
    # 与「首拆完成/自检」构成完整细分链路
    _split_cn = {"storyboard_key_elements": "关键元素",
                 "storyboard_shots": "分镜", "storyboard_audio": "音频"}.get(tool_name, "结构")
    await emit_timeline_note(f"首拆开始：模型流式生成{_split_cn}分组（边生成边写入）…")
    _t_first = time.monotonic()
    # 流式逐条落盘（Q5）：做好一个分组立即写入左侧，不等整次调用结束
    system = exec_common._skill_system_prompt(tool_name, params.skill_name, boundary)
    try:
        applied, warnings, _content, _finish = await exec_common._stream_actions_progressive(
            tool_name, params.skill_name, system, user, svc, skill_content,
            provider=provider, model=model, max_tokens=max_tokens, strip_prompts=True,
            only_group_type=_split_kind,
        )
    except Exception as e:
        applied, warnings, _finish = 0, [str(e)], ""
    # 截断保险（2222 二轮，与 _llm_json_call 策略对齐，10.12-G4 全局化）：
    # 流式路径撞 finish=length 不再收「部分成功」——回滚已写入残品，
    # 扩额整体重试一次；重试仍截断才记警告并走对账流程
    if _is_truncated(_finish):
        _rolled = exec_common._rollback_split_groups(svc, _split_kind, _ids_before)
        logger.warning(
            f"[SkillExec] {tool_name} 输出被截断（finish={_finish}，已写入 {applied}）："
            f"回滚 {_rolled} 个残品分组，扩额整体重试"
        )
        await emit_state_refresh(0)
        await emit_progress("拆解输出撞上限被截断，已回退写入部分，正在扩额重试…")
        try:
            applied, warnings, _content, _finish = await exec_common._stream_actions_progressive(
                tool_name, params.skill_name, system,
                user + "\n\n（系统）上一次输出撞上限被截断。本次请更紧凑地输出："
                "只保留必需字段、压缩每条描述篇幅，务必把所有分组完整输出，不要遗漏。",
                svc, skill_content,
                provider=provider, model=model,
                max_tokens=min(32768, max_tokens * 2), strip_prompts=True,
                only_group_type=_split_kind,
            )
        except Exception as e:
            applied, warnings, _finish = 0, warnings + [str(e)], "length"
        if _is_truncated(_finish):
            warnings.append("本次拆解扩额重试后仍撞上限被截断，已写入部分疑似不完整，请用 storyboard_overview 对账")
        elif applied:
            warnings.append("首拆输出曾被截断，已回退并扩额重试获得完整输出")
    if not applied:
        # 流式零产出（格式漂移/断流/思考占满额度，9999 事故）：回退非流式整体解析
        # 重试一次（P0-4 兜底）；预算翻倍给思考模型留够正文空间，并钉死「直接输出 JSON」
        try:
            applied, warnings2 = await _executor_actions_from_llm(
                tool_name, params.skill_name,
                user + "\n\n（系统）上一次输出未产出有效操作（可能缺失 title 字段、格式错误或"
                "思考耗尽了输出额度）。请直接输出 studio-actions JSON 数组，"
                "不要先输出长篇分析/推理过程；"
                "每个 add_group 必须携带 title 字段（简洁中文名）；不要输出正文解释。",
                skill_content, svc,
                max_tokens=min(32768, max_tokens * 2), strip_prompts=True,
                provider=provider, model=model,
                system_extra=boundary,
                only_group_type=_split_kind,
            )
            warnings += warnings2
        except Exception as e:
            return exec_common.SkillToolResult(success=False, error=str(e))
    if not applied:
        return exec_common.SkillToolResult(success=False, error="；".join(warnings) or "本次故事板拆解未产出任何分组")
    # 首拆即显（Q3）：落盘后立即下发状态快照，左栏分组当场亮出来，
    # 不等后续自检轮跑完；同时在时间线记一条子步骤明细（Q2）
    _first_ms = (time.monotonic() - _t_first) * 1000
    await emit_timeline_note(
        f"首拆完成：{applied} 个分组已写入故事板", elapsed_ms=_first_ms,
    )
    await emit_state_refresh(applied)
    detail = f"已按 Skill 章节拆解并写入 {applied} 个故事板分组"
    # 关键元素自检补漏（防漏拆）：对照剧本逐场核对，结果即时落盘。
    # 固定 1 轮（8888 事故：2 轮自检对短剧本是纯耗时，且失控补建了
    # 大量背景杂物元素；长剧本漏项可由用户审阅后口头补）
    if tool_name == "storyboard_key_elements":
        try:
            provider, model = exec_common._resolve_chat_provider(params.chat_provider, params.chat_model)
            if provider:
                await emit_progress("首拆完成，正在对照剧本逐场自检补漏…")
                _sc_t0 = time.monotonic()
                filled, sc_warns = await _selfcheck_key_elements(
                    tool_name, params.skill_name, skill_content, script_hint,
                    svc, provider, model,
                )
                _sc_ms = (time.monotonic() - _sc_t0) * 1000
                warnings += sc_warns
                if not filled:
                    await emit_timeline_note(
                        "自检：已对照剧本核对，无遗漏元素",
                        elapsed_ms=_sc_ms,
                    )
                else:
                    # 补漏元素不垫底（Q4）：按类别稳定排序归入同类，再快照即显
                    exec_common._sort_key_elements_by_badge(svc)
                    svc.save_debounced()
                    applied += filled
                    detail += f"；自检对照剧本补建了 {filled} 个遗漏元素"
                    await emit_timeline_note(
                        f"自检：补建 {filled} 个遗漏元素（已按类别归位）",
                        elapsed_ms=_sc_ms,
                    )
                    await emit_state_refresh(filled)
        except Exception as e:
            logger.warning(f"[SkillExec] 关键元素自检补漏失败（不影响首拆结果）: {e}")
    # 回执实际建成清单（888 事故：只回数量模型靠猜建成了哪几个，
    # 猜错产生重名卡/空卡）：对照拆解前 ID 快照求差集（含自检补建；
    # 边界自适应放行多类时逐类别收集，2222 二轮）
    _created_titles: List[str] = []
    for _k in (_split_kind.split(",") if _split_kind else []):
        _cat_key = ops.category_for_group_type(_k) if _k else ""
        if not _cat_key:
            continue
        _created_titles.extend(
            str(g.get("title") or "")
            for g in (svc.state_dict.get(_cat_key) or [])
            if g.get("id") not in _ids_before
        )
    if _created_titles:
        _titles_txt = "、".join(_created_titles[:40])
        if len(_created_titles) > 40:
            _titles_txt += f" 等 {len(_created_titles)} 个"
        detail += f"。实际新建：{_titles_txt}"
    # 截断事实进账本 / 完整完成则消解（888 事故：截断不得冒充完成）
    if _is_truncated(_finish):
        _kind_cn = {"storyboard_key_elements": "关键元素",
                    "storyboard_shots": "分镜", "storyboard_audio": "音频"}.get(tool_name, "结构")
        svc.record_flow_event(
            f"{tool_name}_truncated",
            f"上次{_kind_cn}拆解输出撞上限被截断，只写入 {applied} 个，疑似不完整，"
            "请先调用 storyboard_overview 对账并优先补齐缺失部分，不要直接删除重拆",
        )
        detail += f"（警告：本次输出被截断，已写入 {applied} 个疑似不完整，请对账补齐）"
    else:
        svc.clear_flow_events(f"{tool_name}_truncated")
    return exec_common.SkillToolResult(success=True, data={
        "applied": applied,
        "detail": detail,
        "warnings": warnings,
    })


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


def _coverage_categories(target: str) -> Tuple[str, ...]:
    """target 文案 → 状态类别键；无法判定时返回空元组（分母不可靠不校验）。"""
    t = (target or "").lower()
    if "keyelement" in t or "key_element" in t:
        return ("keyElements",)
    if "shot" in t:
        return ("shots",)
    if "audio" in t:
        return ("audioItems",)
    return ()


def _prompt_coverage_note(state: Dict[str, Any], target: str) -> str:
    """防虚报校验：统计目标类别中实际持有提示词的分组占比。

    覆盖异常（如提示词被集中塞进一个分组）时返回警示文案，空串表示正常；
    target 无法判定类别时不校验（分母不可靠）。
    """
    cats = _coverage_categories(target)
    if not cats:
        return ""
    total = with_prompt = 0
    for c in cats:
        for g in state.get(c, []) or []:
            total += 1
            if any(
                str(d.get("prompt") or "").strip()
                for d in (g.get("drafts") or []) if isinstance(d, dict)
            ):
                with_prompt += 1
    if total >= 2 and with_prompt < total:
        return (
            f"覆盖异常：写入后仅 {with_prompt}/{total} 个分组实际持有提示词，"
            "可能存在提示词被集中写入错误分组，请核对故事板并补写缺失分组"
        )
    return ""


# 提示词编写的分批参数（2222 事故：61 个元素一次生成提示词远超 120s 读超时）
# 888 事故复盘：每批 8 条长提示词+思考挤爆 8192 输出额度 → 缩到 4 条（甜点位：
# 每批输出三四千 token 不爆额度，失败时浪费更少、续写更顺；调用次数仅翻倍）
_PROMPT_BATCH_SIZE = 4    # 每批编写的分组数：单次调用输出小不超时，且每批落盘可中途审阅


_PROMPT_BATCH_MAX_TOKENS = 16384  # 批次输出预算（与拆解执行器同档；8192 是 888 事故遗漏）


_PROMPT_MAX_BATCHES = 48  # 分批循环上限（防无进展死循环；缩批后同步放宽）


def _pending_prompt_groups(
    state: Dict[str, Any], target: str, overwrite: bool = False,
) -> List[Tuple[str, Dict[str, Any]]]:
    """列出目标类别中待编写提示词的分组。

    overwrite=False（补写语义）：跳过已有提示词的分组，中断/超时后再次调用
    自然从缺失处续写。
    overwrite=True（重写语义，7777 事故）：目标范围内已有提示词的分组同样纳入，
    批次写入时以 update_draft 直接覆盖旧提示词——不先清空，未轮到的分组
    保留旧提示词，中断无损失。
    target 传具体 group_id/draft_id 时收窄到对应单个分组（单张重写入口）；
    无法判定类别且非具体 ID 时按「空=全部待编写」语义扫全部三类。
    """
    cats = _coverage_categories(target) or ("keyElements", "shots", "audioItems")
    t = (target or "").strip()
    # 具体 group_id / draft_id：收窄到单个分组（非 all_* / 非 current 的裸 ID）
    scoped_id = t if (t and not t.startswith("all_") and t.lower() != "current") else ""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for c in cats:
        for g in state.get(c, []) or []:
            if not isinstance(g, dict):
                continue
            if scoped_id and g.get("id") != scoped_id and not any(
                isinstance(d, dict) and d.get("id") == scoped_id
                for d in (g.get("drafts") or [])
            ):
                continue
            drafts = [d for d in (g.get("drafts") or []) if isinstance(d, dict)]
            if not overwrite and any(str(d.get("prompt") or "").strip() for d in drafts):
                continue
            out.append((c, g))
    return out


def _production_param_note(state: Dict[str, Any], has_ke: bool, has_shots: bool) -> str:
    """制作参数注入（7777 二轮）：Skill 要求每份 Prompt Draft 包含推荐模型与分辨率，
    从规格文档取真实渠道/分辨率/时长值给模型照抄，防止自行拍板。"""
    from src.video_agent.web.provider_config import spec_media_preference, spec_production_params

    params = spec_production_params(state)
    img_res = str(params.get("image_resolution") or "")
    vid_res = str(params.get("video_resolution") or "")
    cap = params.get("shot_max_duration")
    notes: List[str] = []
    if has_ke:
        pid, mdl = spec_media_preference(state, "image")
        rec = " / ".join(x for x in (mdl or pid, img_res) if x)
        if rec:
            notes.append(f"关键元素图像提示词末尾附一行「推荐模型与分辨率：{rec}」")
    if has_shots:
        pid, mdl = spec_media_preference(state, "video")
        rec = " / ".join(x for x in (mdl or pid, vid_res) if x)
        if rec:
            notes.append(f"分镜视频提示词末尾附一行「推荐模型与分辨率：{rec}」")
        if cap:
            notes.append(
                f"分镜最大时长已由制片规格定为 {exec_common._fmt_num(cap)} 秒，"
                f"提示词标注的镜头时长上限为 {exec_common._fmt_num(cap)} 秒"
            )
    if not notes:
        return ""
    return (
        "\n【制作参数】" + "；".join(notes)
        + "（注入章节里的推荐值与上述参数冲突时以上述参数为准）"
    )


async def _write_prompt_batch(
    tool_name: str,
    skill_name: str,
    skill_content: str,
    svc: StateManager,
    provider: str,
    model: str,
    batch: List[Tuple[str, Dict[str, Any]]],
    spec: str,
    analysis_hint: str,
    corrective: bool = False,
    max_tokens: int = _PROMPT_BATCH_MAX_TOKENS,
    corrective_reasons: Optional[List[str]] = None,
) -> Tuple[int, List[str], bool]:
    """单批提示词编写：只为本批分组写入，完成即落盘（分批防超时、可断点续写）。

    corrective=True 时为纠正重试：上一批零进展（建了空卡/未写入），
    在指令里点名问题并要求每个动作必须携带非空 prompt。
    corrective_reasons（业界基准 C2，结构化反馈回喂）：上一批被闸门/校验
    拒收的原因原文，纠正重试时逐条钉进指令，模型按因修复而非盲重。
    返回 (applied, warnings, truncated)：truncated=本批输出撞上限被截断。
    """
    lines: List[str] = []
    has_shots = False
    has_ke = False
    ke_groups = svc.state_dict.get("keyElements") or []
    for cat, g in batch:
        drafts = [d for d in (g.get("drafts") or []) if isinstance(d, dict)]
        ids = "、".join(str(d.get("id") or "") for d in drafts if d.get("id"))
        line = (
            f"- group_id={g.get('id')}（{g.get('title') or '未命名'}）"
            + (f"，已有草稿 draft_id={ids}，用 update_draft 写入"
               if ids else "，尚无草稿卡，用 add_draft 建卡并写入")
        )
        # 分镜：把 sceneRefs 解析为元素标题清单（@引用的名称依据，防模型自造）
        if cat == "shots":
            has_shots = True
        elif cat == "keyElements":
            has_ke = True
        if cat == "shots":
            titles: List[str] = []
            for ref in (g.get("sceneRefs") or []):
                ke = next(
                    (k for k in ke_groups
                     if k.get("id") == ref or k.get("title") == ref),
                    None,
                )
                titles.append(str((ke or {}).get("title") or ref))
            if titles:
                line += f"；本镜头出场元素：{'、'.join(titles)}"
        lines.append(line)
    # @引用规则移植（7777 事故）：写提示词的职能从主模型搬到执行器后，
    # planner/system.md 里的 @规则没有跟过来，导致分镜提示词不 @ 关键元素；
    # 此处显式注入，与主模型路径口径一致
    at_rule = (
        "\n【@引用规则】分镜视频提示词中出场的角色/场景/道具，必须写成 @元素标题"
        "（如 @罗辑）；元素标题以每行「本镜头出场元素」清单为准，自造名称会被系统判定为无引用。"
        "系统生成时会自动把对应素材作为参考素材随请求发送，并把 @名称 改写为"
        "[参考图N：元素标题] 位置标记，无需你手动处理参考素材。"
    ) if has_shots else ""
    # 制作参数注入（7777 二轮）：推荐模型/分辨率/时长上限取自规格文档
    prod_note = _production_param_note(svc.state_dict, has_ke, has_shots)
    system = exec_common._skill_system_prompt(
        tool_name, skill_name,
        "【分批任务边界】本轮只为本批列出的分组编写提示词：只输出 update_draft"
        "（缺卡片用 add_draft），每个 patch 必须含非空 prompt；"
        "本批之外的分组、新建故事板结构分组、触发生成都不属于本任务范围。"
        # 誊写任务直出指令（888 事故：推理模型把输出额度耗在思考上致零产出）：
        # 提示词编写是按规矩翻译的誊写题，推理收益极小，直出优先
        "\n【输出要求】直接输出 studio-actions JSON 结果，"
        "禁止先输出长篇分析/推理过程。"
        + ("\n【纠正】上一批输出只建了空草稿卡或未写入任何提示词，被判不合格；"
           "本次每个动作的 draft/patch 携带实际提示词全文（留空会被判不合格）。"
           if corrective else "")
        + ("\n【拒因回喂】上一批写入被系统校验拒收，原因如下，本次必须逐条修复：\n"
           + "\n".join(f"- {r}" for r in (corrective_reasons or [])[:6])
           if corrective and corrective_reasons else "")
        + "\n【卡片面纪律】draft 的 label 只允许 ≤12 字短语（如「程心三视图」「太空艇参考图」），"
        "分组标题不拼成长句；提示词正文相对分组描述增加增量信息"
        "（视角布局/背景与光效/一致性约束等模板结构），逐字誊写分组描述不符合要求。"
        + at_rule
        + prod_note,
    )
    state_ctx = _build_state_context(svc)
    user = (
        "请只为本批以下分组逐条编写提示词（严格遵循注入章节的提示词写法）：\n"
        + "\n".join(lines)
        + "\n\n只输出 studio-actions JSON 数组：update_draft 必须携带真实 draft_id"
        "（或所属分组的真实 group_id），patch 含 prompt/label/mediaType。不要输出正文解释。\n\n"
        f"规格文档：\n{spec or '（暂无规格文档）'}\n\n"
        f"{analysis_hint or '（暂无剧本分析摘要）'}\n\n"
        f"当前工作台状态：\n{state_ctx}"
    )
    # 流式逐卡落盘（Q5）：写好一张提示词卡立即写入左侧，不等本批全部生成完
    applied, warnings, content, finish = await exec_common._stream_actions_progressive(
        tool_name, skill_name, system, user, svc, skill_content,
        provider=provider, model=model, max_tokens=max_tokens, flush_n=2,
    )
    truncated = _is_truncated(finish)
    if truncated:
        warnings.append("本批输出撞上限被截断，已写入部分疑似不完整")
    if not applied:
        # 流式零产出回退整体解析（兼容非数组围栏输出）
        actions = exec_common._parse_actions_from_text(content or "")
        applied, warnings = exec_common._apply_actions(svc, actions, skill_content)
    if applied:
        logger.info(f"[SkillExec] 提示词分批写入：本批 {applied} 条已落盘")
    return applied, warnings, truncated


class WriteMediaPromptTool:
    name = "write_media_prompt"
    description = (
        "按当前 Skill 的「提示词写法」章节，为故事板草稿逐条编写生成提示词（元素图/分镜/音频），"
        "写入草稿卡并走结构校验。补写语义（默认）：只写还没有提示词的分组。"
        "重写语义：用户说重写/重新编写/重写一遍时，必须传 overwrite=true 并用 target 定范围："
        "全量重写传 all_shots/all_keyElements；单张/部分重写传具体 group_id、draft_id；"
        "范围含糊（未指明哪张/全部）时先问用户确认，再决定范围。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return WriteMediaPromptInput

    async def aexecute(self, params: WriteMediaPromptInput) -> SkillToolResult:
        if not tool_available(params.skill_name, self.name):
            return exec_common.SkillToolResult(success=False, error=f"当前 Skill「{params.skill_name or '未指定'}」未注册 write_media_prompt 执行器")
        svc = StateManager.get_instance()
        spec = exec_common._read_spec_doc(svc.state_dict)
        analysis = svc.state_dict.get("analysis") or {}
        analysis_hint = exec_common._build_script_hint(svc.state_dict)
        kp = analysis.get("key_points") or []
        if kp:
            analysis_hint += f"\n关键要点：{'；'.join(str(k) for k in kp[:6])}"
        try:
            provider, model = exec_common._resolve_chat_provider(params.chat_provider, params.chat_model)
        except Exception:
            provider, model = "", ""
        if not provider:
            return exec_common.SkillToolResult(success=False, error="当前工作区未配置可用的聊天供应商，请先在 API 配置页添加")
        # 级联（业界基准 C5）：常规批先走快模型，纠正重试升级回主推理模型
        fast_provider, fast_model = exec_common._resolve_cascade_fast(provider, model)
        entry = resolve_entry(params.skill_name)
        skill_content = entry.content if entry else ""

        pending = _pending_prompt_groups(svc.state_dict, params.target, overwrite=params.overwrite)
        if not pending:
            return exec_common.SkillToolResult(success=True, data={
                "applied": 0,
                "detail": ("目标范围内没有可重写的分组"
                           if params.overwrite else "目标范围内所有草稿均已持有提示词，无需编写"),
                "warnings": [],
            })
        # 分批编写（2222 事故：61 个元素一次生成提示词超 120s 读超时，重试三次全失败）。
        # 每批分组少、单次输出小不超时，写完即落盘：用户中途停止或单批超时
        # 都不丢已完成批次，再次调用时按客观状态从缺失分组自动续写。
        applied = 0
        warnings: List[str] = []
        total = len(pending)
        batch_no = 0
        batch_times: List[float] = []  # 各批耗时（M6：用于估算剩余时间）

        # 进度锚点分模式：
        # - 补写模式：客观重列"无提示词分组"（原逻辑）；
        # - 重写模式：目标终将全部持有提示词，"有无"不再是锚点，
        #   改用"批前后分组提示词签名是否变化"客观判定哪些已重写。
        all_targets = pending if params.overwrite else []
        done_ids: set = set()
        # 撞线即扩额（888 事故：出现一次撞上限就当预算不足处理）：
        # 后续批次预算翻倍，直到 32768 封顶
        batch_budget = _PROMPT_BATCH_MAX_TOKENS

        def _signatures(groups: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Tuple[str, ...]]:
            return {
                g.get("id"): tuple(
                    str(d.get("prompt") or "") for d in (g.get("drafts") or [])
                )
                for _, g in groups
            }

        def _remaining() -> List[Tuple[str, Dict[str, Any]]]:
            if params.overwrite:
                return [item for item in all_targets if item[1].get("id") not in done_ids]
            return _pending_prompt_groups(svc.state_dict, params.target)

        # 长任务进度上报（M6）：开局告知总批次规模，用户知道在等什么
        await emit_progress(
            f"开始分批{'重写' if params.overwrite else '编写'}提示词：{total} 个分组待写，"
            f"约 {math.ceil(total / _PROMPT_BATCH_SIZE)} 批（每批落盘，可中断可续写）…"
        )
        while pending and batch_no < _PROMPT_MAX_BATCHES:
            batch_no += 1
            batch = pending[:_PROMPT_BATCH_SIZE]
            logger.info(f"[SkillExec] 提示词分批编写：第 {batch_no} 批（本批 {len(batch)} 个，待写 {len(pending)} 个）")
            batch_t0 = time.monotonic()
            before_sigs = _signatures(batch) if params.overwrite else None
            try:
                filled_raw, warns, _trunc = await _write_prompt_batch(
                    self.name, params.skill_name, skill_content, svc,
                    fast_provider, fast_model, batch, spec, analysis_hint,
                    max_tokens=batch_budget,
                )
            except Exception as e:
                warnings.append(f"第 {batch_no} 批写入失败：{e}")
                logger.warning(f"[SkillExec] 提示词分批写入失败（第 {batch_no} 批）: {e}")
                break
            warnings += warns
            if _trunc:
                batch_budget = min(32768, batch_budget * 2)
                logger.info(f"[SkillExec] 提示词批次撞上限，后续批次预算提至 {batch_budget}")
            if params.overwrite:
                # 客观进展：本批中提示词签名发生变化的分组 = 已重写
                after_sigs = _signatures(batch)
                rewritten = [gid for gid, before in before_sigs.items()
                             if after_sigs.get(gid) != before]
                done_ids.update(rewritten)
                filled = len(rewritten)
            else:
                filled = filled_raw
            applied += filled
            new_pending = _remaining()
            if len(new_pending) >= len(pending):
                # 本批零进展（如写了空卡/写错分组）：先批内纠正重试一次
                #（3333 事故：直接判失败会把剩余批次也丢掉，交给外层重试又从头重来）；
                # 纠正后仍零进展才熔断，按未完成处理
                logger.warning(
                    f"[SkillExec] 提示词分批编写：第 {batch_no} 批零进展，立即纠正重试"
                )
                await emit_progress(f"第 {batch_no} 批零进展，正在纠正重试…")
                if (fast_provider, fast_model) != (provider, model):
                    logger.info(
                        f"[SkillExec] 级联升级：第 {batch_no} 批纠正重试由 "
                        f"{fast_provider}/{fast_model} 升级回主模型 {provider}/{model}"
                    )
                try:
                    filled2_raw, warns2, _ = await _write_prompt_batch(
                        self.name, params.skill_name, skill_content, svc,
                        provider, model, batch, spec, analysis_hint,
                        corrective=True, max_tokens=batch_budget,
                        corrective_reasons=warns,
                    )
                except Exception as e:
                    warnings.append(f"第 {batch_no} 批纠正重试失败：{e}")
                    logger.warning(f"[SkillExec] 提示词分批纠正重试失败（第 {batch_no} 批）: {e}")
                    pending = new_pending
                    break
                warnings += warns2
                if params.overwrite:
                    after_sigs = _signatures(batch)
                    rewritten2 = [gid for gid, before in before_sigs.items()
                                  if after_sigs.get(gid) != before and gid not in done_ids]
                    done_ids.update(rewritten2)
                    filled2 = len(rewritten2)
                else:
                    filled2 = filled2_raw
                applied += filled2
                new_pending = _remaining()
                if len(new_pending) >= len(pending):
                    pending = new_pending
                    break
            batch_times.append(time.monotonic() - batch_t0)
            # 完成一批即显（Q1）：本批提示词落盘后立即下发快照，左侧草稿卡
            # 逐批亮出来，不等全部写完；同时时间线记一条子步骤明细
            _batch_written = len(pending) - len(new_pending)
            if _batch_written > 0:
                await emit_timeline_note(
                    f"提示词编写第 {batch_no} 批：{_batch_written} 张提示词卡已写入故事板",
                    elapsed_ms=batch_times[-1] * 1000,
                )
                await emit_state_refresh(_batch_written)
            done = total - len(new_pending)
            if new_pending:
                avg = sum(batch_times) / len(batch_times)
                eta = format_eta(avg * math.ceil(len(new_pending) / _PROMPT_BATCH_SIZE))
                await emit_progress(f"提示词编写中：已完成 {done}/{total} 组，{eta}后完成")
            else:
                await emit_progress(f"提示词编写完成：{done}/{total} 组")
            pending = new_pending
        if pending:
            done = total - len(pending)
            lack = "未完成重写" if params.overwrite else "缺少提示词"
            note = f"覆盖异常：写入后仍有 {len(pending)}/{total} 个分组{lack}（已完成 {done} 个）"
            logger.warning(f"[SkillExec] {note}")
            # 部分完成事实进账本（888 事故：只写完 8/16 却无人知晓）：
            # 下一轮模型能从工作台状态直接看到「只完成了一半」
            svc.record_flow_event(
                "write_media_prompt_partial",
                f"上次提示词编写未完成：{done}/{total} 个分组已写入，"
                f"还有 {len(pending)} 个{lack}；再次调用 write_media_prompt 会从缺失处自动续写",
            )
            # 重写模式下续写必须再带 overwrite，否则剩余分组（持旧提示词）会被补写语义跳过
            again = ("请再次调用 write_media_prompt（重写任务需再带 overwrite=true），"
                     if params.overwrite else "请再次调用 write_media_prompt，")
            return exec_common.SkillToolResult(
                success=False,
                error=(f"提示词编写未完成：{note}。已写入部分已落盘不会丢失；"
                       f"{again}将从缺失分组自动续写"),
            )
        # 全部完成：消解历史的部分完成记录
        svc.clear_flow_events("write_media_prompt_partial")
        verb = "重写" if params.overwrite else "写入"
        detail = f"已按 Skill 提示词写法分 {batch_no} 批{verb} {applied} 张草稿提示词（每批落盘，可在故事板逐批审阅）"
        return exec_common.SkillToolResult(success=True, data={
            "applied": applied,
            "detail": detail,
            "warnings": warnings,
        })


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
        for g in state.get("shots") or []:
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
        for g in state.get("audioItems") or []:
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
        return exec_common.SkillToolResult(success=True, data={
            "plan": plan,
            "detail": "已生成组装方案（素材清单 + 时间轴顺序），可在画布中按此组装导出",
        })


def _resolve_section_text(entry: Optional[Any], section: str) -> str:
    """通用章节解析（814E1）：stage key → flova tag → 标题关键字 → 任意 <tag>。

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
    section: str = Field(..., description="章节标识：stage key（如 storyboard_ke）/ flova tag（如 write_the_prompt）/ 任意自定义 <tag> / 标题关键字")
    task: str = Field(..., description="本章节要执行的具体任务描述（系统自动附工作台状态 JSON）")


class SkillSectionRunTool:
    name = "skill_section_run"
    description = (
        "通用章节执行器（814E1）：把当前 Skill 的任意章节作为唯一依据注入独立执行器，"
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


class SkillPipelinePlanTool:
    name = "skill_pipeline_plan"
    description = (
        "依赖图调度（814E2）：解析当前 Skill <planner> 的步骤与依赖关系，"
        "结合工作台状态客观返回各步骤完成度与下一可执行批次（同批可并行）。"
        "按返回的 ready 批次推进，不要跳步。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return SkillToolInput

    async def aexecute(self, params: SkillToolInput) -> SkillToolResult:
        from src.video_agent.skill_runtime import dag
        from src.video_agent.skill_runtime.guard import skill_planner_flow

        svc = StateManager.get_instance()
        skill = params.skill_name or fallback_skill_from_state(svc.state_dict)
        flow = skill_planner_flow(skill)
        if not flow:
            return exec_common.SkillToolResult(success=False, error=f"Skill「{skill or '未指定'}」无 <planner> 流程章节")
        # B4b/F32：manifest 声明的 step_done_conditions（确定性评估优先于关键字猜测）
        from src.video_agent.skill_runtime.registry import resolve_entry
        conditions = None
        entry = resolve_entry(skill)
        if entry and entry.manifest:
            conditions = ((entry.manifest.get("flow") or {}).get("step_done_conditions")) or None
        status = dag.pipeline_status(flow, svc.state_dict, conditions)
        ready = [s for s in status if s["ready"]]
        batches = dag.topo_batches(dag.parse_steps(flow), dag.parse_dependencies(flow))
        return exec_common.SkillToolResult(success=True, data={
            "steps": status,
            "ready_batch": ready,
            "parallel_batches": batches,
        })


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
# R4a 补：角标排序家族实现体在 exec_common，此处 re-export 保持既有直引
from src.video_agent.skill_runtime.exec_common import (
    _BADGE_CATEGORY_KEYS,
    _badge_category_rank,
    _sort_key_elements_by_badge,
)
