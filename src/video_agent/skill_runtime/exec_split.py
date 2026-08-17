"""故事板拆解域（五轮 S5 自 exec_tools.py 切出，R4a 拆分模式延续）。

任务词（_KE_TASK 等）+ 三拆共用执行逻辑（_run_storyboard_split）+ 关键元素
自检补漏（_selfcheck_key_elements）。exec_tools 尾部 re-export 保持既有
引用路径不变（宪法 §12 登记壳）。
"""
import re
import time
from typing import List, Optional, Tuple

from loguru import logger

from src.video_agent.state.manager import StateManager
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.models import CAT_KEY_ELEMENTS
from src.video_agent.web import generation as _gen
from src.video_agent.skill_runtime.progress import (
    emit_progress,
    emit_state_refresh,
    emit_timeline_note,
)
from src.video_agent.skill_runtime.registry import resolve_entry

from src.video_agent.skill_runtime import exec_common
from src.video_agent.skill_runtime.exec_common import (
    SkillToolResult,
    _is_truncated,
)
from src.video_agent.skill_runtime.exec_spec import (
    _build_state_context,
    _executor_actions_from_llm,
)
# StoryboardSplitInput 定义在 exec_tools（schema 域）；exec_tools 对本模块的
# 引用在文件尾部（本模块顶层导入时 exec_tools 尚未执行到尾部 import，无环）
from src.video_agent.skill_runtime.exec_tools import StoryboardSplitInput


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


_AUDIO_BADGES = ("音频", "音频-角色", "音色")
_CHAR_BADGES = ("人物", "角色")
_SPEAKER_RE = re.compile(r"(?m)^\s*([一-鿿A-Za-z][一-鿿A-Za-z0-9_]{0,11})\s*[:：]")
_SPEAKER_STOP = frozenset({
    "场景", "地点", "时间", "人物", "画面", "镜头", "旁白", "画外",
    "音效", "音乐", "台词", "动作", "描述", "内容", "标题", "格式",
    "注意", "说明", "总结", "梗概", "正文", "剧本", "摘要", "预览",
})


def _script_speakers(script_text: str, limit: int = 20) -> List[str]:
    """0817：剧本原文客观提取台词人（行首 名字+冒号），作覆盖验收实体基线。"""
    out: List[str] = []
    for m in _SPEAKER_RE.finditer(str(script_text or "")):
        name = m.group(1).strip()
        if len(name) < 2 or any(w in name for w in _SPEAKER_STOP) or any(c.isdigit() for c in name):
            continue
        if name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def skill_declares_audio(skill_name: str) -> bool:
    """0817：Skill 是否声明音色登记（章节提及 key_element_audio/音色登记，
    或 manifest gates.require_audio_layer）——验收清单从 Skill 读，不拍脑袋。"""
    try:
        entry = resolve_entry(skill_name)
        content = entry.content if entry else ""
    except Exception:
        content = ""
    if not content:
        return False
    if "key_element_audio" in content or ("音色" in content and "登记" in content):
        return True
    try:
        from src.video_agent.core import prompt_gates
        return bool(prompt_gates.parse_gate_rules(content).get("require_audio_layer", False))
    except Exception:
        return False


def _coverage_missing_key_elements(svc: StateManager, skill_name: str) -> List[str]:
    """0817 机器覆盖验收（零 token，P2）：① 剧本台词人都有对应分组；
    ② Skill 声明音色时，每个人物组都有对应音色组。缺失才触发定向补拆。"""
    groups = [
        g for g in (svc.state_dict.get(CAT_KEY_ELEMENTS) or [])
        if isinstance(g, dict)
    ]
    titles = [str(g.get("title") or "").strip() for g in groups]
    missing: List[str] = []
    script = exec_common._build_script_hint(svc.state_dict)
    for sp in _script_speakers(script):
        if not any(t and (sp in t or t in sp) for t in titles):
            missing.append(f"角色「{sp}」（剧本台词人）未拆出分组")
    if skill_declares_audio(skill_name):
        audio_descs = [
            (str(a.get("title") or "") + str(a.get("desc") or ""))
            for a in groups
            if str(a.get("badgeLabel") or "").strip() in _AUDIO_BADGES
        ]
        for g in groups:
            badge = str(g.get("badgeLabel") or "").strip()
            t = str(g.get("title") or "").strip()
            if badge in _CHAR_BADGES and t and not any(t in d for d in audio_descs):
                missing.append(f"角色「{t}」缺对应音色组（key_element_audio）")
    return missing


async def _selfcheck_key_elements(
    tool_name: str,
    skill_name: str,
    skill_content: str,
    script_hint: str,
    svc: StateManager,
    provider: str,
    model: str,
    missing: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    """第二遍补漏：按机器验收缺失清单定向补建关键元素（0817：由常跑自检
    改为条件触发，缺失清单由 _coverage_missing_key_elements 零 token 产出）。"""
    if not script_hint and not missing:
        return 0, []
    existing = [
        str(g.get("title") or "").strip()
        for g in (svc.state_dict.get(CAT_KEY_ELEMENTS) or [])
    ]
    system = exec_common._skill_system_prompt(tool_name, skill_name, _KE_SELFCHECK_BOUNDARY)
    if missing:
        ask = (
            "\n\n机器验收发现以下缺失项（逐条补齐，缺什么补什么，"
            "不要重复已有分组）：\n" + "\n".join(f"- {m}" for m in missing)
        )
    else:
        ask = (
            "\n\n请按剧本逐场/逐段核对是否有遗漏的关键元素（补建粒度与克制要求按《执行铁律》第 2 条）。\n"
            "只输出遗漏元素的 studio-actions JSON 数组"
        )
    user = (
        "以下是本项目已拆出的关键元素分组：\n"
        + ("\n".join(f"- {t}" for t in existing) if existing else "（暂无）")
        + "\n\n" + script_hint + ask +
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
        # 0817：机器覆盖验收（Skill 声明驱动）替换常跑模型自检——
        # 核对零 token；无缺失直接省一轮模型调用（上下文净减少）
        missing = _coverage_missing_key_elements(svc, params.skill_name)
        if not missing:
            await emit_timeline_note("验收：机器交叉核对通过，无遗漏元素")
        else:
            try:
                provider, model = exec_common._resolve_chat_provider(params.chat_provider, params.chat_model)
                if provider:
                    await emit_progress(f"验收发现 {len(missing)} 项缺失，定向补拆…")
                    _sc_t0 = time.monotonic()
                    filled, sc_warns = await _selfcheck_key_elements(
                        tool_name, params.skill_name, skill_content, script_hint,
                        svc, provider, model, missing=missing,
                    )
                    _sc_ms = (time.monotonic() - _sc_t0) * 1000
                    warnings += sc_warns
                    if not filled:
                        await emit_timeline_note(
                            f"验收：发现 {len(missing)} 项缺失但补拆未产出，请审阅后口头补",
                            elapsed_ms=_sc_ms,
                        )
                    else:
                        exec_common._sort_key_elements_by_badge(svc)
                        svc.save_debounced()
                        applied += filled
                        detail += f"；验收定向补建了 {filled} 个遗漏元素"
                        await emit_timeline_note(
                            f"验收：补建 {filled} 个遗漏元素（已按类别归位）",
                            elapsed_ms=_sc_ms,
                        )
                        await emit_state_refresh(filled)
            except Exception as e:
                logger.warning(f"[SkillExec] 关键元素验收补漏失败（不影响首拆结果）: {e}")
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

