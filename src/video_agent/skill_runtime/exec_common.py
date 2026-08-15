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
    call_chat_completion_stream,
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






class SkillToolResult(BaseModel):
    """执行器工具结果（与 tools.base.ToolResult 同构，避免 tools 包循环导入）。"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def _resolve_chat_provider(provider: str = "", model: str = "") -> Tuple[str, str]:
    """聊天供应商解析（决策 E：优先用主模型一致的供应商/模型，缺失回退首个可用）。"""
    from src.video_agent.web.provider_config import (
        CLI_PROTOCOLS,
        get_provider_config,
        load_merged_providers,
    )

    if provider:
        cfg = get_provider_config(provider)
        if cfg and cfg.get("enabled", True) and (cfg.get("protocol") or "") != "mock":
            if model:
                return provider, model
            models = cfg.get("chat_models") or []
            if models:
                return provider, str(models[0])

    for p in load_merged_providers():
        if not p.get("enabled", True):
            continue
        if (p.get("protocol") or "") == "mock":
            continue
        models = p.get("chat_models") or []
        if models and (p.get("base_url") or (p.get("protocol") or "") in CLI_PROTOCOLS):
            return str(p.get("id") or ""), str(models[0])
    return "", ""


def _resolve_cascade_fast(main_provider: str, main_model: str) -> Tuple[str, str]:
    """誊写批级联快模型解析（业界基准 C5；B8 策略表化）。

    优先级：模型策略表 executor 角色（热更新可编辑）> settings.executor_fast_model
    （"provider" 或 "provider:model"，旧配置兼容）> 主模型（不级联）。
    零进展/被拒收的纠正重试由调用方升级回主推理模型；解析失败绝不阻断主流程。
    """
    from src.video_agent.core import model_policy

    role = model_policy.resolve_role("executor")
    if role:
        return role["provider"], role["model"]
    spec = str(getattr(settings, "executor_fast_model", "") or "").strip()
    if not spec:
        return main_provider, main_model
    try:
        from src.video_agent.web.provider_config import load_merged_providers

        pid, _, mdl = spec.partition(":")
        prov = next(
            (p for p in load_merged_providers()
             if str(p.get("id") or "") == pid and p.get("enabled", True)),
            None,
        )
        if not prov:
            return main_provider, main_model
        mdl = mdl.strip() or str((prov.get("chat_models") or [""])[0])
        if not mdl:
            return main_provider, main_model
        return pid, mdl
    except Exception:
        return main_provider, main_model


def _executor_thinking() -> Optional[str]:
    """执行器机械调用的思考档位（2222 二轮，10.9 模型分层；B8 策略表化）：

    拆解/提示词编写/自检/软参数出题等「照章办事」的结构化产出不需要深推理；
    降档缩短思考静默期，也防思考吃光输出预算导致截断（deepseek-v4-flash
    曾单次思考 2.6 万字把 16384 预算耗光、正文只出 7 个分镜）。
    优先级：策略表 executor 角色档位 > settings.executor_thinking_level > None。
    主聊天不受影响。
    """
    from src.video_agent.core import model_policy

    return model_policy.thinking_for("executor", settings.executor_thinking_level) or None


def _fmt_num(value) -> str:
    """数字规整：12.0 → "12"，避免注入文案出现「12.0 秒」。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else str(f)


def _spec_override_clauses(raw_state: Dict[str, Any], kinds: Tuple[str, ...]) -> str:
    """五项制片规格覆盖注入（2222 二轮，【时长硬约束】模式扩展为统一实现点）。

    制片规格里已定的参数 → 注入一条覆盖句压过 Skill 章节写死的默认值
    （优先级链：制片规格 > Skill，由系统注入执行而非 prose 说教，10.12-G3）。
    kinds 取值：duration / image_resolution / video_resolution /
    image_channel / video_channel；规格未定的项不注入（章节默认值照常兜底）。
    """
    from src.video_agent.state.provider_prefs import resolve_spec_media_preference
    from src.video_agent.web.provider_config import load_merged_providers, spec_production_params

    params = spec_production_params(raw_state) or {}
    items: List[str] = []
    if "duration" in kinds:
        cap = params.get("shot_max_duration")
        if cap:
            items.append(f"分镜最大时长为 {_fmt_num(cap)} 秒（所有分镜 duration ≤ {_fmt_num(cap)} 秒）")
    if "image_resolution" in kinds:
        v = params.get("image_resolution")
        if v:
            items.append(f"图片分辨率为 {v}")
    if "video_resolution" in kinds:
        v = params.get("video_resolution")
        if v:
            items.append(f"视频分辨率为 {v}")
    if "image_channel" in kinds or "video_channel" in kinds:
        try:
            providers = load_merged_providers()
        except Exception:
            providers = []
        if providers:
            for kind, label in (("image", "出图渠道"), ("video", "出视频渠道")):
                if f"{kind}_channel" not in kinds:
                    continue
                pid, mdl = resolve_spec_media_preference(raw_state, providers, kind)
                if pid:
                    name = next(
                        (str(p.get("name") or p.get("id") or "") for p in providers
                         if p.get("id") == pid),
                        pid,
                    )
                    items.append(label + "为 " + " / ".join(x for x in (name, mdl) if x))
    if not items:
        return ""
    return (
        "\n\n【制片规格覆盖】" + "；".join(items)
        + "。注入章节里的对应条款与此冲突时以本条为准。"
    )


def _rollback_split_groups(svc: StateManager, split_kind: str, ids_before: set) -> int:
    """截断回滚（2222 二轮）：删除本次拆解新建的分组，恢复拆解前状态。

    与「拆解前 ID 快照」配套：流式首拆撞上限时已落盘的残品全部撤销，
    随后扩额整体重试，避免「首拆 7 个 + 补拆 6 个」式拼接结果。
    split_kind 支持逗号分隔多类别（边界自适应放行多类时同步回滚）。
    """
    removed = 0
    for kind in (str(split_kind or "").split(",") if split_kind else []):
        kind = kind.strip()
        cat = ops.category_for_group_type(kind) if kind else ""
        if not cat:
            continue
        added = [
            g for g in (svc.state_dict.get(cat) or [])
            if isinstance(g, dict) and g.get("id") not in ids_before
        ]
        for g in added:
            ops.delete_group(svc.state_dict, str(g.get("id") or ""), kind)
        removed += len(added)
    if removed:
        svc.save_debounced()
    return removed


# 拆解边界自适应（2222 二轮）：允许的分组类别以注入章节的客观文本为准
# （与 _skill_system_prompt 注入源唯一，不依赖 Skill 声明改动，10.12-G1）。
# 优先级：① 章节「本节职责：只创建 X 分组」显式边界声明（Skill 层 3 唯一源）；
# ② 无声明的合并章节按职责关键词检测（如「AI-短剧」storyboard_designer）。
_RESP_SCOPE_RE = re.compile(r"本节职责[^：:]*[:：]\s*只创建([^，。；;\n]*?)分组")


_KIND_DETECTORS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("keyElement", re.compile(r"key_?element", re.I)),
    ("shot", re.compile(r"\bshots?\b|分镜|镜头列表", re.I)),
    ("audio", re.compile(r"audio_?layers?\b|音频层|\baudio\b", re.I)),
)


_KIND_SPAN_DETECTORS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("keyElement", re.compile(r"key_?element|关键元素", re.I)),
    ("shot", re.compile(r"\bshots?\b|分镜", re.I)),
    ("audio", re.compile(r"\baudio\b|音频", re.I)),
)


def _split_kinds_for_section(tool_name: str, skill_name: str) -> List[str]:
    """执行器允许收进的分组类别，按注入章节的客观结构自适应。

    章节带「本节职责：只创建 X 分组」声明（如「剧本生视频」三个独立章节）→
    按声明精确放行，句内提到的其它类别是禁令不是职责；
    无声明的合并章节（如「AI-短剧」storyboard_designer 同含三块职责）→
    Skill 语义即"一起设计"，按关键词检测放行对应多类一次收进。
    本执行器自身类别恒定包含（检测漏判也不越权收紧）。
    """
    base = {
        "storyboard_key_elements": "keyElement",
        "storyboard_shots": "shot",
        "storyboard_audio": "audio",
    }.get(tool_name, "")
    if not base:
        return []
    try:
        section = tool_sections(skill_name, tool_name)
    except Exception:
        section = ""
    if not section:
        return [base]
    m = _RESP_SCOPE_RE.search(section)
    if m:
        span = m.group(1)
        kinds = [k for k, pat in _KIND_SPAN_DETECTORS if pat.search(span)]
        if kinds:
            if base not in kinds:
                kinds.append(base)
            return kinds
    kinds = [k for k, pat in _KIND_DETECTORS if pat.search(section)]
    if base not in kinds:
        kinds.append(base)
    return kinds


def _prompt_language_rule(skill_name: str) -> str:
    """提示词正文语言的单一事实源（业界基准 C1）。

    与 PromptGate 语言闸读同一份 parse_gate_rules 结果：cjk_min_ratio>0 =
    语言闸生效（中文正文），=0 = Skill 声明英文锁定。注入句是「事实陈述」
    而非待权衡的规则，章节英文模板只借结构不借语言。
    """
    lang = "中文"
    try:
        entry = resolve_entry(skill_name)
        rules = prompt_gates.parse_gate_rules(entry.content if entry else "")
        if float(rules.get("cjk_min_ratio", 0.15)) <= 0:
            lang = "英文"
    except Exception:
        lang = "中文"
    if lang == "英文":
        return "1. 提示词正文语言：英文（本 Skill 声明英文锁定、平台语言闸关闭，按章节模板书写）。"
    return (
        "1. 提示词正文语言：中文（平台语言闸生效，写入校验同此一源）。"
        "章节里的英文模板只借结构（三视图/四视图排布、一致性约束等），"
        "正文一律用中文书写，仅专业风格/光影/构图/渲染技术术语可保留英文原词。"
    )


def _style_memory_block(limit: int = 5) -> str:
    """项目风格记忆注入（814E3）：只认「风格偏好：」前缀条目（摘要提示词约定），
    按项目隔离，注入执行器 system prompt，保证跨会话风格连续性。"""
    try:
        if not settings.memory_enabled:
            return ""
        from src.video_agent.memory import MemoryManager

        pid = StateManager.get_instance().active_project_id or ""
        recs = MemoryManager.get_instance().list_records(project_id=pid)
    except Exception:
        return ""
    lines = [
        f"- {r.content}" for r in recs
        if (r.content or "").strip().startswith("风格偏好：")
    ][:limit]
    if not lines:
        return ""
    return (
        "\n== 项目风格记忆（用户确认过的风格偏好，提示词必须体现）==\n"
        + "\n".join(lines)
    )


def _skill_system_prompt(tool: str, skill_name: str, extra: str = "", section_override: Optional[str] = None) -> str:
    """执行器 system prompt：平台精简协议 + Skill 对应章节（只注入自己那一节）+ 铁律全文。

    section_override（814E1）：通用章节执行器直接注入任意章节文本，
    不经 tool_sections 的固定映射。"""
    section = section_override if section_override is not None else tool_sections(skill_name, tool)
    parts = [
        "你是本影视 Agent 工作台的独立执行器。",
        f"当前选中 Skill：「{skill_name or '未指定'}」。",
        "下面是该 Skill 中与本执行器唯一对应的章节，必须严格按它执行；"
        "不要调用本章节之外的其他 Skill 规则，也不要输出与任务无关的内容。",
        "",
        "== Skill 对应章节 ==",
        section or "（该 Skill 未提供本执行器对应章节）",
    ]
    # 铁律全文注入（宪法 D2/D5）：拆解粒度等生产契约的表述源在铁律，
    # 任务词不再复述；无铁律文档（测试/未开工项目）时静默跳过
    try:
        from src.video_agent.core.spec_rules import find_iron_rules_doc

        iron = find_iron_rules_doc(StateManager.get_instance().state_dict)
        iron_content = str((iron or {}).get("content") or "").strip()
        if iron_content:
            parts += ["", "== 项目《执行铁律》（生产契约，与章节冲突时以铁律为准）==", iron_content]
    except Exception as _e:
        logger.debug("[executors] 忽略异常: {}", _e)
    # 风格记忆注入（814E3）：跨会话风格连续性
    style_block = _style_memory_block()
    if style_block:
        parts.append(style_block)
    # 冲突裁决总则（888 事故：章节内中英规则打架、章节与规格时长数字并存，
    # 推理模型反复权衡耗掉万字思考）：把两处常见冲突收敛成一条确定规则，
    # 模型不再需要自行裁决。
    # 语言单一事实源（业界基准 C1，6666 二轮事故）：注入句与 PromptGate 校验
    # 读同一份 parse_gate_rules 结果——「章节模板是英文」不再构成例外，
    # 模型无需仲裁，两条平台表述 by construction 不可能再打架。
    parts += [
        "",
        "== 冲突裁决（无需自行权衡，直接按此执行）==",
        _prompt_language_rule(skill_name),
        "2. 时长/数量等硬参数：后续任务消息里的【制作参数】【时长硬约束】来自用户确认的"
        "制片规格，与章节数字冲突时以任务消息为准。",
    ]
    if extra:
        parts.append("")
        parts.append(extra)
    return "\n".join(parts)


def _find_uploaded_doc(state: Dict[str, Any], name: str = "", doc_id: str = "") -> Optional[Dict[str, Any]]:
    """按名称/ID 模糊查找上传文档（与 read_uploaded_doc 同语义）。"""
    docs = state.get("uploadedDocs") or []

    def norm(s: str) -> str:
        return (s or "").strip().casefold().replace(" ", "")

    target = None
    if name:
        nn = norm(name)
        for d in docs:
            if norm(d.get("name") or "") == nn:
                target = d
                break
        if target is None:
            for d in docs:
                if nn and nn in norm(d.get("name") or ""):
                    target = d
                    break
    if target is None and doc_id:
        target = next((d for d in docs if d.get("id") == doc_id), None)
    if target is None and docs:
        target = docs[0]
    return target


def _read_spec_doc(state: Dict[str, Any]) -> str:
    """读取规格文档全文（制片规格 等）。"""
    for d in state.get("documents") or []:
        if prompt_gates.is_spec_doc_name(str(d.get("name") or "")):
            return str(d.get("content") or "")
    return ""


# 剧本正文注入上限（拆解/提示词阶段需按剧本忠实产出，仅摘要不足以覆盖台词与场次）
_SCRIPT_INJECT_LIMIT = 10000


def _build_script_hint(state: Dict[str, Any]) -> str:
    """剧本理解锚点：一句话总结 + 剧本正文（超长截断）。

    故事板拆解与提示词编写都要求忠实于剧本（台词/旁白/场景顺序），
    仅注入摘要会迫使模型凭空概括，故正文恒注入；摘要只作理解锚点。
    """
    parts: List[str] = []
    analysis = state.get("analysis") or {}
    if analysis.get("summary"):
        parts.append(f"剧本一句话总结：{analysis.get('summary')}")
    doc = _find_uploaded_doc(state)
    if doc:
        content = str(doc.get("content") or "")
        if content:
            body = content[:_SCRIPT_INJECT_LIMIT]
            suffix = (
                "\n……（剧本超长已截断，请优先保证已见内容的忠实度）"
                if len(content) > _SCRIPT_INJECT_LIMIT else ""
            )
            parts.append(f"剧本《{doc.get('name')}》正文：\n{body}{suffix}")
    return "\n\n".join(parts)


def _parse_actions_from_text(text: str) -> List[Dict[str, Any]]:
    """从 LLM 回复中提取 studio-actions JSON 数组（兼容围栏与裸 JSON）。"""
    from src.video_agent.web.action_parser import parse_actions_from_reply

    actions = parse_actions_from_reply(text)
    if actions:
        return actions
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except Exception as _e:
            logger.debug("[executors] 忽略异常: {}", _e)
    return []


# 流式逐条落盘参数（Q5：做好一个立即填入左侧故事板，不等整批生成完）
_PROGRESSIVE_FLUSH_N = 4        # 累积 N 个完整动作即应用一批


_PROGRESSIVE_FLUSH_SECS = 1.5   # 或距上次落盘超过该间隔（防尾部少量动作长期不刷新）


def _extract_complete_objects(buf: str, pos: int) -> Tuple[List[str], int]:
    """从流式累积文本的 JSON 数组内部（pos 起）提取已闭合的对象文本。

    返回 (对象文本列表, 新扫描位置)：对象未闭合时停在原地，
    等后续增量补齐再续扫；字符串内的花括号不计入层级。
    """
    objects: List[str] = []
    n = len(buf)
    while True:
        while pos < n and buf[pos] in " \t\r\n,":
            pos += 1
        if pos >= n or buf[pos] != "{":
            break
        depth, in_str, esc = 0, False, False
        start = i = pos
        complete = False
        while i < n:
            c = buf[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    objects.append(buf[start:i + 1])
                    pos = i + 1
                    complete = True
                    break
            i += 1
        if not complete:
            break
    return objects, pos


def _is_truncated(finish: str) -> bool:
    """finish_reason 是否为撞输出上限被截断（888 事故：截断残品被当成品收下）。"""
    return (finish or "").strip().lower() in (
        "length", "max_tokens", "max_output_tokens", "content_filter",
    )


async def _stream_actions_progressive(
    tool_name: str,
    skill_name: str,
    system: str,
    user: str,
    svc: StateManager,
    skill_content: str,
    *,
    provider: str,
    model: str,
    max_tokens: int,
    strip_prompts: bool = False,
    flush_n: int = _PROGRESSIVE_FLUSH_N,
    only_group_type: str = "",
) -> Tuple[int, List[str], str, str]:
    """流式生成 studio-actions 并逐批落盘（Q5）：模型每吐完几个完整动作就立即
    写入故事板并下发快照，左侧卡片逐个亮出来，不再干等整次调用结束。

    返回 (applied, warnings, 完整文本, finish_reason)；零产出时由调用方回退整体解析重试。
    finish_reason 供截断检测（length=撞输出上限，888 事故）。
    截断/零产出时自动落黑匣子档案（完整指令+输出+思考，888 事故）。
    """
    buf_parts: List[str] = []
    scan = {"pos": 0, "arr_started": False}
    pending: List[Dict[str, Any]] = []
    counters = {"applied": 0, "last_flush": time.monotonic(), "last_note": time.monotonic()}
    warnings: List[str] = []

    async def flush(force: bool = False) -> None:
        if not pending:
            return
        if (
            not force
            and len(pending) < flush_n
            and time.monotonic() - counters["last_flush"] < _PROGRESSIVE_FLUSH_SECS
        ):
            return
        batch, pending[:] = pending[:], []
        n, warns = _apply_actions(
            svc, batch, skill_content, strip_prompts=strip_prompts,
            only_group_type=only_group_type,
        )
        warnings.extend(warns)
        counters["applied"] += n
        counters["last_flush"] = time.monotonic()
        svc.save_debounced()
        if n:
            await emit_state_refresh(n)
            await emit_progress(f"已写入 {counters['applied']} 条，模型继续生成中…")
            # 子步骤细分（2222 反馈）：每批流式落盘在时间线记一条子项，
            # 长拆解过程不再只有「首拆完成」一个粗粒度节点
            _note_ms = (time.monotonic() - counters["last_note"]) * 1000
            counters["last_note"] = time.monotonic()
            await emit_timeline_note(
                f"流式落盘：本批写入 {n} 个分组（累计 {counters['applied']}）",
                elapsed_ms=_note_ms,
            )

    async def on_delta(text: str) -> None:
        buf_parts.append(text)
        buf = "".join(buf_parts)
        pos = scan["pos"]
        if not scan["arr_started"]:
            i = buf.find("[")
            if i < 0:
                return
            scan["arr_started"] = True
            pos = i + 1
        objs, pos = _extract_complete_objects(buf, pos)
        scan["pos"] = pos
        for obj_text in objs:
            try:
                obj = json.loads(obj_text)
            except json.JSONDecodeError:
                continue  # 单条格式坏不影响其余条目（结尾整体回退兑底）
            if isinstance(obj, dict):
                pending.append(obj)
        await flush()

    _reasoning: List[str] = []
    content, finish = await _gen.call_chat_completion_stream(
        provider,
        model,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        timeout=180,
        on_delta=on_delta,
        reasoning_sink=_reasoning,
        thinking_level=_executor_thinking(),
    )
    await flush(force=True)
    # 黑匣子（888 事故）：截断/零产出时完整取证落盘，事后可直接看模型在纠结什么
    if _is_truncated(finish) or counters["applied"] == 0:
        from src.video_agent.skill_runtime.blackbox import dump_case

        dump_case(
            kind=tool_name,
            reason=("output_truncated" if _is_truncated(finish) else "zero_output"),
            system=system,
            user=user,
            content=content or "",
            finish=finish,
            reasoning=_reasoning,
            extra={
                "applied": counters["applied"],
                "max_tokens": max_tokens,
                "skill": skill_name,
                "reasoning_chars": sum(len(r) for r in _reasoning),
            },
        )
    return counters["applied"], warnings, content or "", finish


# 执行器批次可识别的标题字段（与 action_executor 兜底链同义）：
# 模型用这些键之外的字段名携带标题时，执行器直接拒收而非静默落默认标题
_TITLE_KEYS = (
    "title", "name", "label", "element_id", "element_name", "element_title",
    "group_name", "group_title",
)


def _action_has_title(action: Dict[str, Any]) -> bool:
    """add_group 是否携带可识别的标题字段（含嵌套 group/data/patch）。"""
    nested = action.get("group") or action.get("data") or {}
    patch = action.get("patch") or {}
    for src in (action, nested, patch):
        if any(str(src.get(k) or "").strip() for k in _TITLE_KEYS):
            return True
    return False


def _apply_actions(
    svc: StateManager,
    actions: List[Dict[str, Any]],
    skill_content: str,
    strip_prompts: bool = False,
    only_group_type: str = "",
) -> Tuple[int, List[str]]:
    """执行 LLM 产出的 studio-actions（走既有闸机与持久化，未命中返回警告）。

    only_group_type（非空时）：阶段边界的代码校验（宪法 P2 下沉）——
    只允许指定类别的 add_group，越界分组拒收并回喂，替代 boundary prose 说服。
    支持逗号分隔多类别（2222 二轮边界自适应）：Skill 章节同时覆盖多类分组
    职责时放行对应类别，单一职责章节仍传单类别。
    """
    from src.video_agent.web.action_executor import StudioActionExecutor

    if not actions:
        return 0, ["执行器未产出有效操作（JSON 缺失或格式错误）"]
    warnings: List[str] = []
    # 阶段边界拒收（宪法 P2）：KE 执行器里建分镜/音频等越界分组直接丢弃
    if only_group_type:
        _wants = {
            prompt_gates.normalize_structure_kind(k)
            for k in str(only_group_type).split(",") if k.strip()
        }
        _wants.discard("")
        _off = [
            a for a in actions
            if str(a.get("action") or "") == "add_group"
            and prompt_gates.normalize_structure_kind(a.get("group_type") or "") not in _wants
        ]
        if _off:
            actions = [a for a in actions if a not in _off]
            warnings.append(
                f"{len(_off)} 个越界分组被拒收（本阶段只允许 {only_group_type} 类别，请重新执行对应阶段执行器）"
            )
            logger.warning(f"[SkillExec] 拒收越界 add_group {len(_off)} 个（只允许 {only_group_type}）")
    # 分镜完整度校验（4444 P7，require_at_ref 同款机械模式）：shot 的 sceneRefs
    # 必须非空且覆盖标题提及的关键元素（标题点名的角色漏引 = 跨镜一致性断链）
    if only_group_type and "shot" in {
        prompt_gates.normalize_structure_kind(k)
        for k in str(only_group_type).split(",") if k.strip()
    }:
        _ke_map = [
            (str(k.get("title") or "").strip(), str(k.get("id") or ""))
            for k in (svc.state_dict.get("keyElements") or [])
            if isinstance(k, dict)
        ]
        _bad: List[Dict[str, Any]] = []
        _bad_detail: List[str] = []
        for a in actions:
            if str(a.get("action") or "") != "add_group":
                continue
            if prompt_gates.normalize_structure_kind(a.get("group_type") or "") != "shot":
                continue
            src = a.get("group") or a.get("data") or a
            refs = [str(r) for r in (src.get("sceneRefs") or []) if r]
            title = str(src.get("title") or a.get("title") or "")
            missing = [t for t, kid in _ke_map if t and t in title and kid not in refs]
            if not refs or missing:
                _bad.append(a)
                _bad_detail.append(
                    f"「{title[:12]}」缺 sceneRefs" if not refs
                    else f"「{title[:12]}」漏引 {'、'.join(missing[:3])}"
                )
        if _bad:
            actions = [a for a in actions if a not in _bad]
            warnings.append(
                f"{len(_bad)} 个分镜分组因 sceneRefs 缺失/漏引被拒收"
                f"（{'；'.join(_bad_detail[:4])}）。sceneRefs 须非空并覆盖标题提及的"
                "角色/场景，请补全引用后重试。"
            )
            logger.warning(f"[SkillExec] 分镜完整度校验拒收 {len(_bad)} 个：{'；'.join(_bad_detail[:4])}")
    # 无标题 add_group 拒收（8888 事故：首拆 20 组全落默认标题「Agent 新建分组」，
    # 自检按标题去重又完全失效导致重复建卡）：宁缺毋滥，零产出时由
    # 调用方的回退重试路径带「必须携带 title」提示重新生成
    untitled = [
        a for a in actions
        if str(a.get("action") or "") == "add_group" and not _action_has_title(a)
    ]
    if untitled:
        actions = [a for a in actions if a not in untitled]
        warnings.append(f"{len(untitled)} 个分组因未携带 title 字段被丢弃（将要求模型重试）")
        logger.warning(f"[SkillExec] 拒收无标题 add_group {len(untitled)} 个")
    if not actions:
        return 0, warnings or ["执行器产出的分组全部缺失 title 字段"]
    if strip_prompts:
        from src.video_agent.skill_runtime.guard import strip_structure_actions

        stripped = strip_structure_actions(actions)
        if stripped:
            warnings.append(f"已剥离结构阶段内联提示词 {stripped} 条（提示词由 write_media_prompt 阶段编写）")
    ex = StudioActionExecutor(svc, gate_enabled=True)
    # 结构阶段内联提示词剥离只在结构执行器启用（write_media_prompt 等
    # 提示词阶段必须让 prompt 原样落盘，不能被结构纯净闸误剥）
    ex.structure_phase = bool(strip_prompts)
    ex.gate_rules = prompt_gates.parse_gate_rules(skill_content)
    ex.gate_override = False
    applied = ex.execute(actions)
    warnings += list(ex.gate_warnings)
    if applied < len(actions):
        warnings.append(f"{len(actions) - applied} 个操作未匹配到目标或执行失败")
    return applied, warnings


# R4a 补：关键元素角标排序（自 exec_tools 移入，控制文件行数红线）
# 关键元素类别排序（Q4 补漏元素不垫底）：人物→场景→道具→载具，其余保持原相对位置
_BADGE_CATEGORY_KEYS = (
    ("人物", "角色"),
    ("场景", "地点", "环境"),
    ("道具", "物品", "器物"),
    ("载具", "交通工具", "飞船", "车辆"),
)


def _badge_category_rank(label: str) -> int:
    """按徽标文案推断类别序；未命中的排在已知类别之后（稳定排序保序）。"""
    text = str(label or "")
    for i, keys in enumerate(_BADGE_CATEGORY_KEYS):
        if any(k in text for k in keys):
            return i
    return len(_BADGE_CATEGORY_KEYS)


def _sort_key_elements_by_badge(svc: StateManager) -> bool:
    """对关键元素列表按类别稳定排序（同类内部保持原有先后）。
    返回是否发生了顺序变化（无变化时不动状态，避免无谓重绘）。"""
    groups = svc.state_dict.get("keyElements") or []
    if len(groups) < 2:
        return False
    ordered = sorted(groups, key=lambda g: _badge_category_rank(str(g.get("badgeLabel") or "")))
    if [g.get("id") for g in ordered] == [g.get("id") for g in groups]:
        return False
    svc.state_dict["keyElements"] = ordered
    return True
