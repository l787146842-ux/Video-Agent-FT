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
    GenerationError,
    call_chat_completion,
)
from src.video_agent.core import prompt_gates
from src.video_agent.core.token_budget import output_limit_for_model
from src.video_agent.skill_runtime.progress import (
    emit_progress,
)
from src.video_agent.skill_runtime.registry import (
    tool_sections,
)

from src.video_agent.skill_runtime import exec_common



from src.video_agent.skill_runtime.exec_common import (
    _apply_actions,
    _build_script_hint,
    _executor_thinking,
    _is_truncated,
    _parse_actions_from_text,
    _resolve_chat_provider,
    _skill_system_prompt,
)


async def _llm_json_call(
    system: str,
    user: str,
    max_tokens: int = 4096,
    provider: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """独立 LLM 调用并解析 JSON 输出（无 function calling 依赖）。

    预算策略（1111 事故：推理模型思考占满 2048 额度，四次连续截断失败）：
    - 初始预算先钳到模型输出上限（output_limit_for_model 查表）；
    - finish_reason 撞上限被截断、或思考耗尽预算返回空内容 → 自动翻倍扩额重试一次；
    - 扩到上限仍截断 → 抛明确的截断错误，不把残品 JSON 塞给解析器。
    """
    provider, model = exec_common._resolve_chat_provider(provider, model)
    if not provider:
        raise RuntimeError("当前工作区未配置可用的聊天供应商，请先在 API 配置页添加")
    ceiling = output_limit_for_model(model)
    budget = max(min(int(max_tokens or ceiling), ceiling), 1024)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    content = ""
    for attempt in (1, 2):
        try:
            content, finish = await _gen.call_chat_completion(
                provider,
                model,
                messages,
                max_tokens=budget,
                timeout=settings.llm_json_timeout,
                thinking_level=exec_common._executor_thinking(),
            )
        except GenerationError as e:
            # 空内容多为推理模型思考吃光预算；预算未到顶就扩额重试一次
            if attempt == 1 and "空内容" in str(e) and budget < ceiling:
                budget = min(budget * 2, ceiling)
                logger.warning(
                    f"[SkillExec] LLM 返回空内容（疑输出预算耗尽），自动扩额至 {budget} 重试"
                )
                continue
            raise
        if _is_truncated(finish):
            if attempt == 1 and budget < ceiling:
                budget = min(budget * 2, ceiling)
                logger.warning(
                    f"[SkillExec] LLM 输出被截断（finish={finish}），自动扩额至 {budget} 重试"
                )
                continue
            raise RuntimeError(
                f"执行器 LLM 输出在模型输出上限（{budget} tokens）处被截断，"
                "请缩短素材或改用输出上限更大的模型"
            )
        break
    m = re.search(r"\{[\s\S]*\}", content or "")
    if not m:
        raise RuntimeError("执行器 LLM 未返回 JSON 结果")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"执行器 LLM 返回的 JSON 无法解析: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("执行器 LLM 返回的 JSON 不是对象")
    return data


async def _generate_soft_spec_candidates(
    svc: StateManager,
    skill_name: str,
    chat_provider: str,
    chat_model: str,
    summary: str,
    script_content: str,
) -> None:
    """软制作参数候选出题（888 豪华版）：内层模型按剧本给六个维度各出
    2~4 个候选，校验后落 interaction.spec_soft_candidates 供收集向导渲染。

    规格流程按客观特征自动检测启用（2222 二轮）；维度来自 Skill 规格步骤
    客观提取（4444：平台不预设维度）；任何失败静默回落（向导不渲染该维度）。
    """
    try:
        from src.video_agent.skill_runtime.registry import spec_wizard_active

        if not spec_wizard_active(skill_name):
            return
        dims = prompt_gates.skill_spec_dimensions(skill_name)
        if not dims:
            return
        provider, model = exec_common._resolve_chat_provider(chat_provider, chat_model)
        if not provider:
            return
        # 剧本体量客观边界（4444：1197 字剧本出 10 分钟候选的闹剧；
        # 9999 二轮：旧 3 字/秒是旁白朗读速率，1197 字微剧本算出 7 分钟
        # 上限仍不合理）——剧情类成片约 600 字剧本/分钟；按剧本正文实测，
        # 收卷时超限候选剔除，全超则回落确定性梯度（不再出题给模型）
        script_len = len(str(script_content or "").strip())
        dur_cap_min = max(1, round(script_len / 600)) if script_len else 0
        dur_note = (
            f"（剧本约 {script_len} 字，剧情类成片约 600 字剧本/分钟，"
            f"合理成片时长上限约 {dur_cap_min} 分钟；"
            "含「时长」维度的候选必须落在该上限内，用「约 N 秒/分钟」表述）"
            if dur_cap_min else ""
        )
        aspect_note = (
            "（含「画幅」的维度候选只能从标准画幅比例中选："
            "16:9、9:16、1:1、4:3、2.35:1，可附不超过 4 字的修饰）"
            if any(_is_aspect_dim(d) for d in dims) else ""
        )
        # 长任务进度上报（2222 反馈）：内层候选出题 LLM 调用常耗时数十秒，
        # 与 script_analyze 主调用一样先告知用户在等什么
        await emit_progress("正在生成制片规格候选（独立 LLM 调用，预计数十秒）…")
        data = await _llm_json_call(
            "你是制片规格助手，只输出 JSON，不输出推理过程。",
            (
                "根据以下剧本，为下列制片维度各提出 2~4 个贴合题材与基调的候选值，"
                "每个候选不超过 12 字。维度：" + "、".join(dims) + "。"
                + dur_note + aspect_note + "\n"
                "输出 JSON 对象，键为维度名，值为候选字符串数组。\n\n"
                f"一句话总结：{summary}\n剧本开头：{script_content[:4000]}"
            ),
            max_tokens=4096,
            provider=chat_provider,
            model=chat_model,
        )
        cleaned: Dict[str, List[str]] = {}
        for dim in dims:
            vals = data.get(dim)
            if not isinstance(vals, list):
                continue
            vs: List[str] = []
            for v in vals:
                s = str(v or "").strip()
                if 1 < len(s) <= 24 and s not in vs:
                    # 时长类维度体量过滤：候选分钟数超剧本粗估上限则剔除
                    if dur_cap_min and "时长" in dim:
                        mins = _candidate_minutes(s)
                        if mins and mins > dur_cap_min:
                            continue
                    vs.append(s)
            if dur_cap_min and "时长" in dim:
                # 8888 二轮：时长候选按分钟值去重（「约 2 分钟」≈「约 120 秒」
                # 是同一档），表述归一，不再给用户出重复选项
                vs = _dedupe_duration_candidates(vs)
            if _is_aspect_dim(dim):
                # 画幅是渠道能力参数（确定性题）：模型自造的电影规格
                # （如 1.43:1 IMAX）生成渠道出不了，归一到标准画幅白名单
                vs = _normalize_aspect_candidates(vs)
            elif dur_cap_min and "时长" in dim and len(vs) < 2:
                # 模型候选全部超限：确定性梯度兜底（系统算，不再问模型）
                vs = _duration_ladder(dur_cap_min)
            if len(vs) >= 2:
                cleaned[dim] = vs[:4]
        if cleaned:
            inter = svc.state_dict.setdefault("interaction", {})
            inter["spec_soft_candidates"] = cleaned
            svc.save_debounced()
            logger.info(f"[SkillExec] 软参数候选已出题：{'、'.join(cleaned)}")
    except Exception as e:
        logger.warning(f"[SkillExec] 软参数候选出题失败（回落：向导不渲染软维度）: {e}")


def _candidate_minutes(text: str) -> float:
    """候选文案里的时长分钟数（「90 秒」→1.5，「10 分钟」→10）；解析不出返回 0。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|分|小时|秒)", str(text or ""))
    if not m:
        return 0.0
    n = float(m.group(1))
    unit = m.group(2)
    return n * 60 if unit == "小时" else n / 60 if unit == "秒" else n


def _dedupe_duration_candidates(vals: List[str]) -> List[str]:
    """8888 二轮：时长候选按分钟值去重（同值留首个）并归一表述
    （<1 分钟用「约 N 秒」，其余「约 N 分钟」）；解析不出分钟的原样保留。"""
    out: List[str] = []
    seen: set = set()
    for v in vals:
        mins = _candidate_minutes(v)
        if mins <= 0:
            if v not in seen:
                seen.add(v)
                out.append(v)
            continue
        key = round(mins * 4) / 4
        if key in seen:
            continue
        seen.add(key)
        if key < 1:
            label = f"约 {int(key * 60)} 秒"
        else:
            label = f"约 {int(key)} 分钟" if key == int(key) else f"约 {key} 分钟"
        out.append(label)
    return out


# ---------- 画幅候选客观归一（9999 二轮） ----------
# 画幅比例是生成渠道的能力参数，属确定性题（13.5 三问 1+2）：
# 候选只能命中标准画幅白名单，模型只选不造；有效候选不足时兜底平台标准集。
_ASPECT_RATIO_WHITELIST: Tuple[str, ...] = (
    "16:9", "9:16", "1:1", "4:3", "3:4", "2.35:1", "21:9",
)


_ASPECT_RATIO_LABELS: Dict[str, str] = {
    "16:9": "16:9 横屏", "9:16": "9:16 竖屏", "1:1": "1:1 方形",
    "4:3": "4:3 经典", "3:4": "3:4 竖屏", "2.35:1": "2.35:1 宽银幕",
    "21:9": "21:9 宽银幕",
}


_ASPECT_DIM_HINTS = ("画幅", "比例", "aspect")


_ASPECT_RATIO_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*[:：]\s*(\d{1,2}(?:\.\d+)?)")


def _is_aspect_dim(dim: str) -> bool:
    low = str(dim or "").lower()
    return any(h in low for h in _ASPECT_DIM_HINTS)


def _normalize_aspect_candidates(vals: List[str]) -> List[str]:
    """归一画幅候选到标准比例；有效命中不足 2 个时兜底平台标准四选。"""
    out: List[str] = []
    for v in vals:
        m = _ASPECT_RATIO_RE.search(str(v or ""))
        if not m:
            continue
        ratio = f"{m.group(1)}:{m.group(2)}"
        if ratio not in _ASPECT_RATIO_WHITELIST:
            continue
        label = _ASPECT_RATIO_LABELS.get(ratio, ratio)
        if label not in out:
            out.append(label)
        if len(out) >= 4:
            break
    if len(out) < 2:
        out = ["16:9 横屏", "9:16 竖屏", "1:1 方形", "4:3 经典"]
    return out


def _duration_ladder(cap_min: int) -> List[str]:
    """时长确定性候选（模型候选全部超上限时兜底）：上限以下均匀取档。"""
    if cap_min <= 1:
        return ["约 30 秒", "约 60 秒"]
    out: List[str] = []
    for v in (cap_min / 2, cap_min * 0.75, float(cap_min)):
        v = round(v * 2) / 2
        label = f"约 {int(v)} 分钟" if v == int(v) else f"约 {v} 分钟"
        if label not in out:
            out.append(label)
    return out


async def _fill_spec_values(
    skill_name: str, dims: List[str], raw_state: Dict[str, Any],
) -> Dict[str, str]:
    """方案乙：未选软维度由模型按剧本填值（只出值、不出文档，4444）。"""
    if not dims:
        return {}
    provider, model = exec_common._resolve_chat_provider("", "")
    if not provider:
        return {}
    hint = exec_common._build_script_hint(raw_state)
    data = await _llm_json_call(
        "你是制片规格助手，只输出 JSON，不输出推理过程。",
        (
            "根据以下剧本，为每个制片维度填一个简洁值（≤20 字）。"
            "维度：" + "、".join(dims) + "。输出 JSON 对象，键为维度名。\n\n"
            f"剧本概要：{hint[:2000]}"
        ),
        max_tokens=1024,
        provider=provider,
        model=model,
    )
    return {
        d: str(data.get(d) or "").strip()[:40]
        for d in dims if str(data.get(d) or "").strip()
    }


def _build_state_context(svc: StateManager, limit: int = 12000) -> str:
    """工作台状态 JSON（紧凑注入，超长截断）。"""
    try:
        ctx = svc.build_agent_context("bound") or ""
    except Exception:
        ctx = ""
    return ctx[:limit] + ("\n……（状态超长已截断）" if len(ctx) > limit else "")


async def _executor_actions_from_llm(
    tool: str,
    skill_name: str,
    user_prompt: str,
    skill_content: str,
    svc: StateManager,
    max_tokens: int = 8192,
    strip_prompts: bool = False,
    provider: str = "",
    model: str = "",
    system_extra: str = "",
    only_group_type: str = "",
    section_override: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """通用执行器：注入章节 → LLM 产出 studio-actions → 应用并校验。"""
    system = exec_common._skill_system_prompt(tool, skill_name, system_extra, section_override=section_override)
    provider, model = exec_common._resolve_chat_provider(provider, model)
    if not provider:
        return 0, ["当前工作区未配置可用的聊天供应商，请先在 API 配置页添加"]
    warnings: List[str] = []
    last_content, last_finish = "", ""
    for attempt in (1, 2):
        content, finish = await _gen.call_chat_completion(
            provider,
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            timeout=180,
            thinking_level=exec_common._executor_thinking(),
        )
        last_content, last_finish = content or "", finish or ""
        actions = exec_common._parse_actions_from_text(content or "")
        applied, warns = exec_common._apply_actions(
            svc, actions, skill_content, strip_prompts=strip_prompts,
            only_group_type=only_group_type,
        )
        warnings += warns
        if applied:
            return applied, warnings
        # 自动重试一次（P0-4：失败兜底，禁止让主模型绕过执行器手动代拆）
        user_prompt = (
            user_prompt
            + "\n\n（系统）上一次执行器输出未通过校验或未产出有效操作，"
            "请严格按注入章节重新输出 studio-actions JSON；不要输出正文解释。"
        )
    # 黑匣子（888 事故）：非流式兜底路径异常也存档，取证链不留死角
    from src.video_agent.skill_runtime.blackbox import dump_case
    
    dump_case(
        kind=tool,
        reason=("fallback_truncated" if _is_truncated(last_finish)
                else "fallback_zero_output"),
        system=system,
        user=user_prompt,
        content=last_content,
        finish=last_finish,
        extra={"skill": skill_name, "max_tokens": max_tokens},
    )
    return 0, warnings or ["执行器两次尝试均未产出有效操作"]
