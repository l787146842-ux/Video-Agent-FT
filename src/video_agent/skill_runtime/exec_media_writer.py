"""媒体提示词编写族（九轮 B3 自 exec_tools.py 切出，R4a 拆分模式延续）。

write_prompt 批处理支撑（_coverage_categories/_prompt_coverage_note/
_pending_prompt_groups/_production_param_note/_write_prompt_batch）+
WriteMediaPromptTool。exec_tools 尾部 re-export 保持既有引用路径不变
（宪法 §12 登记壳；零行为变更，代码逐字迁移）。
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
    ALL_CATEGORIES_TUPLE, CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS,
)
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
from src.video_agent.skill_runtime.exec_common import SkillToolInput


class WriteMediaPromptInput(SkillToolInput):
    target: str = Field("", description="目标范围：all_keyElements / all_shots / all_audio / 具体 group_id、draft_id（空 = 全部待编写）")
    overwrite: bool = Field(
        False,
        description="重写模式：用户说重写/重新编写/重写一遍时必须传 true。"
                    "true 时目标范围内已有提示词的分组也纳入重写（直接覆盖，不先清空，"
                    "中断不丢旧提示词）；false 维持补写语义（只写没有提示词的分组）",
    )
    user_text: str = Field("", description="用户附加要求（可选）")


def _coverage_categories(target: str) -> Tuple[str, ...]:
    """target 文案 → 状态类别键；无法判定时返回空元组（分母不可靠不校验）。"""
    t = (target or "").lower()
    if "keyelement" in t or "key_element" in t:
        return (CAT_KEY_ELEMENTS,)
    if "shot" in t:
        return (CAT_SHOTS,)
    if "audio" in t:
        return (CAT_AUDIO_ITEMS,)
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
    cats = _coverage_categories(target) or ALL_CATEGORIES_TUPLE
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
    ke_groups = svc.state_dict.get(CAT_KEY_ELEMENTS) or []
    for cat, g in batch:
        drafts = [d for d in (g.get("drafts") or []) if isinstance(d, dict)]
        ids = "、".join(str(d.get("id") or "") for d in drafts if d.get("id"))
        line = (
            f"- group_id={g.get('id')}（{g.get('title') or '未命名'}）"
            + (f"，已有草稿 draft_id={ids}，用 update_draft 写入"
               if ids else "，尚无草稿卡，用 add_draft 建卡并写入")
        )
        # 分镜：把 sceneRefs 解析为元素标题清单（@引用的名称依据，防模型自造）
        if cat == CAT_SHOTS:
            has_shots = True
        elif cat == CAT_KEY_ELEMENTS:
            has_ke = True
        if cat == CAT_SHOTS:
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
            # 0817 B17：语言闸拒收也触发批内即时纠正——全英文等硬拒带上拒因
            # 立即重写，不再走「全部写完再拦 → 整工具失败从头重做」的高成本路径
            _gate_rejects = [str(w) for w in warns
                             if prompt_gates.LANG_EN_HARD_PREFIX in str(w)]
            _zero_progress = len(new_pending) >= len(pending)
            if _zero_progress or _gate_rejects:
                if _zero_progress:
                    # 本批零进展（如写了空卡/写错分组）：先批内纠正重试一次
                    #（3333 事故：直接判失败会把剩余批次也丢掉，交给外层重试又从头重来）；
                    # 纠正后仍零进展才熔断，按未完成处理
                    logger.warning(
                        f"[SkillExec] 提示词分批编写：第 {batch_no} 批零进展，立即纠正重试"
                    )
                    await emit_progress(f"第 {batch_no} 批零进展，正在纠正重试…")
                else:
                    logger.warning(
                        f"[SkillExec] 提示词分批编写：第 {batch_no} 批撞语言闸 "
                        f"{len(_gate_rejects)} 次，批内即时纠正重写"
                    )
                    await emit_progress(f"第 {batch_no} 批提示词语言未过闸，正在纠正重写…")
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
                        corrective_reasons=(_gate_rejects[:6] if _gate_rejects else warns),
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


