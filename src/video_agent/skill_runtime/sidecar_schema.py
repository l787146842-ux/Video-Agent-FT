# -*- coding: utf-8 -*-
"""sidecar schema v2/v3 校验器（手写 dataclass 级结构校验，零新依赖，禁 jsonschema）。

语义口径：
- fail-closed：已声明键形状非法 → 报出（注册期门禁告警、workflow 编译门禁拒入）；
- 未声明键合法：引擎零预设，回落旧行为（与 sidecar「零声明 = 最小闸」同构）。

v3 新增键（0822 任务#34 B1，Skill 通用化「全文注入+模型自主执行」地基）：
顶层 schema_version / kind / requires_inputs / language / pause_points /
scripts。全部可选、未声明=零预设；执行器一步退役（用户裁决），
故不设 execution.mode/strict 执行器名单。v2 键校验语义一律不动。

校验键清单（flow 下）：steps / dependencies / stage_executors / step_stages /
step_done_conditions / step_short_titles / stages.<规范键>.{done,skip,executors} /
布尔开关（spec_wizard/spec_gate/script_required）；顶层 pause.stage_pause；
顶层 custom_sections（自定义章节→通用执行器通道，P3-15）。
另含跨键一致性：步骤号引用必须落在 steps 内；step_stages×dependencies
翻译出的阶段 DAG 不得成环（成环 = 调度死锁，注册期即拒）。

规范阶段键单一事实源在 core.pipeline_orchestrator.CANONICAL_STAGES；
skill_runtime 不得反向 import core（分层约束），此处同值复制，
漂移由 tests/unit/test_sidecar_schema_v2.py 的锁源断言钉死。
"""
from typing import Any, Dict, List

# 与 pipeline_orchestrator.CANONICAL_STAGES 键序一致（漂移锁源见测试）
CANONICAL_STAGE_KEYS = (
    "analysis", "spec", "structure", "ke_media",
    "shot_media", "audio_assets", "assembly",
)

_FLOW_BOOL_KEYS = ("spec_wizard", "spec_gate", "script_required")
_STAGE_OVERRIDE_KEYS = ("done", "skip", "executors")
_DONE_PREFIX = "document:"
_PAUSE_KEYS = ("stage_pause",)

# custom_sections 声明的合法执行器白名单（P3-15 自定义章节通道）：
# 通道单一 = 通用章节执行器 skill_section_run（与 prompts/planner/
# executor_runtime.md「无专属执行器的章节用 skill_section_run」同源语义）；
# 未来若增专属通用执行器，先在此登记再允许声明（fail-closed）。
CUSTOM_SECTION_EXECUTORS = ("skill_section_run",)

# ---------- v3 新增键白名单（任务#34 B1） ----------
SCHEMA_VERSION = 3
_KIND_VALUES = ("pipeline", "style", "reference")
_REQUIRES_INPUT_TYPES = ("script", "music", "video", "image", "doc")
_LANGUAGE_VALUES = ("zh", "en", "auto")
_PAUSE_TRIGGER_VALUES = (
    "spec_finalized", "storyboard_structure_ready",
    "first_generation_call", "batch_boundary", "free_text",
)

# 公开别名（任务#35 B2/B3 消费端同源读取：registry 声明 API / guard 暂停点
# 清洗同读此白名单，消费侧不再各自硬编码；校验语义仍归本模块 _check_*）
KIND_VALUES = _KIND_VALUES
REQUIRES_INPUT_TYPES = _REQUIRES_INPUT_TYPES
LANGUAGE_VALUES = _LANGUAGE_VALUES
PAUSE_TRIGGER_VALUES = _PAUSE_TRIGGER_VALUES


def _step_nos_of(steps: Dict[str, Any]) -> set:
    return {str(k) for k in steps}


def _check_steps(steps: Any, issues: List[str]) -> Dict[str, Any]:
    if steps is None:
        return {}
    if not isinstance(steps, dict):
        issues.append("flow.steps 必须是对象（步骤号→标题）")
        return {}
    for k, v in steps.items():
        if not str(k).isdigit():
            issues.append(f"flow.steps 步骤号 {k!r} 必须是数字串")
        elif not isinstance(v, str) or not v.strip():
            issues.append(f"flow.steps[{k}] 标题必须是非空字符串")
    return steps


def _check_dependencies(
    deps: Any, step_nos: set, has_steps: bool, issues: List[str],
) -> Dict[str, Any]:
    if deps is None:
        return {}
    if not isinstance(deps, dict):
        issues.append("flow.dependencies 必须是对象（步骤号→前置列表）")
        return {}
    for k, v in deps.items():
        if has_steps and str(k) not in step_nos:
            issues.append(f"依赖声明 {k}→… 的步骤 {k} 不在 steps 中")
        if not isinstance(v, list):
            issues.append(f"flow.dependencies[{k}] 必须是数组")
            continue
        for pre in v:
            if has_steps and str(pre) not in step_nos:
                issues.append(f"依赖 {k}→{pre} 的前置步骤 {pre} 不在 steps 中")
    return deps


def _check_step_keyed(
    name: str, raw: Any, step_nos: set, has_steps: bool,
    check_value, issues: List[str],
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append(f"flow.{name} 必须是对象（步骤号→声明值）")
        return
    for k, v in raw.items():
        if has_steps and str(k) not in step_nos:
            issues.append(f"flow.{name}[{k}] 的步骤 {k} 不在 steps 中")
        check_value(name, k, v, issues)


def _check_exec_list(name: str, k: Any, v: Any, issues: List[str]) -> None:
    if not isinstance(v, list) or not all(
        isinstance(x, str) and x.strip() for x in v
    ):
        issues.append(f"flow.{name}[{k}] 必须是非空字符串数组（执行器名）")


def _check_stage_value(name: str, k: Any, v: Any, issues: List[str]) -> None:
    if not isinstance(v, str) or v not in CANONICAL_STAGE_KEYS:
        issues.append(
            f"flow.{name}[{k}] 必须是规范阶段键（{'/'.join(CANONICAL_STAGE_KEYS)}）")


def _check_str_value(name: str, k: Any, v: Any, issues: List[str]) -> None:
    if not isinstance(v, str) or not v.strip():
        issues.append(f"flow.{name}[{k}] 必须是非空字符串")


def _check_custom_sections(raw: Any, issues: List[str]) -> None:
    """custom_sections：章节标识 → 通用执行器名（顶层声明）。

    未声明合法（回落现行为：固定章节词汇表）；已声明形状非法 fail-closed。
    """
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append("custom_sections 必须是 JSON 对象（章节标识→执行器名）")
        return
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            issues.append(f"custom_sections 章节标识 {k!r} 必须是非空字符串")
            continue
        if not isinstance(v, str) or v not in CUSTOM_SECTION_EXECUTORS:
            issues.append(
                f"custom_sections[{k}] 执行器必须是 "
                f"{'/'.join(CUSTOM_SECTION_EXECUTORS)} 之一（实际 {v!r}）")


def _check_schema_version(data: Dict[str, Any], issues: List[str]) -> None:
    """顶层 schema_version：整数，当前 3；缺省视为 v2 兼容（零预设）。"""
    v = data.get("schema_version")
    if v is None:
        return
    if isinstance(v, bool) or not isinstance(v, int):
        issues.append("schema_version 必须是整数（当前 3；缺省视为 v2 兼容）")
    elif v not in (2, SCHEMA_VERSION):
        issues.append(f"schema_version 取值 {v} 不受支持（当前 3，缺省视为 v2 兼容）")


def _check_kind(data: Dict[str, Any], issues: List[str]) -> None:
    """kind：枚举 pipeline|style|reference；非法值整体忽略该键并告警。"""
    v = data.get("kind")
    if v is None:
        return
    if v not in _KIND_VALUES:
        issues.append(
            f"kind 必须是 {'/'.join(_KIND_VALUES)} 之一"
            f"（非法值整体忽略，实际 {v!r}）")


def _check_requires_inputs(raw: Any, issues: List[str]) -> None:
    """requires_inputs：数组，每项 {type, required, hint}；
    type 白名单 script|music|video|image|doc，required 缺省 true。"""
    if raw is None:
        return
    if not isinstance(raw, list):
        issues.append("requires_inputs 必须是数组（每项 {type, required, hint}）")
        return
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            issues.append(f"requires_inputs[{i}] 必须是对象 {{type, required, hint}}")
            continue
        t = item.get("type")
        if t not in _REQUIRES_INPUT_TYPES:
            issues.append(
                f"requires_inputs[{i}].type 必须是 "
                f"{'/'.join(_REQUIRES_INPUT_TYPES)} 之一（实际 {t!r}）")
        req = item.get("required")
        if req is not None and not isinstance(req, bool):
            issues.append(f"requires_inputs[{i}].required 必须是布尔值（缺省 true）")
        hint = item.get("hint")
        if hint is not None and (not isinstance(hint, str) or not hint.strip()):
            issues.append(f"requires_inputs[{i}].hint 必须是非空字符串")


def _check_language(raw: Any, issues: List[str]) -> None:
    """language：对象 {prompt, output}，取值 zh|en|auto。"""
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append("language 必须是对象 {prompt, output}")
        return
    for key in ("prompt", "output"):
        v = raw.get(key)
        if v is not None and v not in _LANGUAGE_VALUES:
            issues.append(
                f"language.{key} 必须是 {'/'.join(_LANGUAGE_VALUES)} 之一"
                f"（实际 {v!r}）")


def _check_pause_points(raw: Any, issues: List[str]) -> None:
    """pause_points：数组，每项 {id, trigger, ...}；trigger 白名单制。

    batch_boundary 需附 description、free_text 需附 prose，
    缺失则该项注册期忽略并告警（fail-closed 口径）。
    """
    if raw is None:
        return
    if not isinstance(raw, list):
        issues.append("pause_points 必须是数组（每项 {id, trigger, ...}）")
        return
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            issues.append(f"pause_points[{i}] 必须是对象 {{id, trigger, ...}}")
            continue
        pid = item.get("id")
        if not isinstance(pid, str) or not pid.strip():
            issues.append(f"pause_points[{i}].id 必须是非空字符串")
        trigger = item.get("trigger")
        if trigger not in _PAUSE_TRIGGER_VALUES:
            issues.append(
                f"pause_points[{i}].trigger 必须是 "
                f"{'/'.join(_PAUSE_TRIGGER_VALUES)} 之一（实际 {trigger!r}）")
            continue
        if trigger == "batch_boundary":
            desc = item.get("description")
            if not isinstance(desc, str) or not desc.strip():
                issues.append(
                    f"pause_points[{i}] trigger=batch_boundary 需附 description"
                    "（缺失则该项忽略）")
        elif trigger == "free_text":
            prose = item.get("prose")
            if not isinstance(prose, str) or not prose.strip():
                issues.append(
                    f"pause_points[{i}] trigger=free_text 需附 prose"
                    "（缺失则该项忽略）")


def _check_scripts(raw: Any, issues: List[str]) -> None:
    """scripts：字段允许存在，但声明非空即注册期告警「暂不支持」
    （v3 第一版不消费；空声明 = 未声明，零预设）。"""
    if raw is None:
        return
    if raw:  # 非空对象/数组/字符串等均视为「已声明」
        issues.append("scripts 暂不支持（v3 第一版不消费该键，声明已忽略）")


def _check_stage_overrides(stages: Any, issues: List[str]) -> None:
    if stages is None:
        return
    if not isinstance(stages, dict):
        issues.append("flow.stages 必须是对象（规范阶段键→覆盖声明）")
        return
    for key, ov in stages.items():
        if key not in CANONICAL_STAGE_KEYS:
            issues.append(
                f"flow.stages.{key} 不是规范阶段键"
                f"（{'/'.join(CANONICAL_STAGE_KEYS)}）")
            continue
        if not isinstance(ov, dict):
            issues.append(f"flow.stages.{key} 必须是对象")
            continue
        done = ov.get("done")
        if done is not None and (
            not isinstance(done, str)
            or not done.startswith(_DONE_PREFIX)
            or not done[len(_DONE_PREFIX):].strip()
        ):
            issues.append(f"flow.stages.{key}.done 必须是 'document:<文档名>'")
        skip = ov.get("skip")
        if skip is not None and not isinstance(skip, bool):
            issues.append(f"flow.stages.{key}.skip 必须是布尔值")
        execs = ov.get("executors")
        if execs is not None:
            _check_exec_list(f"stages.{key}", "executors", execs, issues)


def _has_stage_cycle(deps: Dict[str, Any], step_stages: Dict[str, Any]) -> bool:
    """step_stages×dependencies 翻译的阶段 DAG 成环检测（环 = 调度死锁）。"""
    graph: Dict[str, List[str]] = {}
    for step_no, prereqs in deps.items():
        tgt = step_stages.get(str(step_no))
        if not isinstance(prereqs, list) or not tgt:
            continue
        for p in prereqs:
            src = step_stages.get(str(p))
            if src and src != tgt:
                graph.setdefault(tgt, [])
                if src not in graph[tgt]:
                    graph[tgt].append(src)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for nxt in graph.get(node, ()):
            c = color.get(nxt, WHITE)
            if c == GRAY or (c == WHITE and dfs(nxt)):
                return True
        color[node] = BLACK
        return False

    return any(
        color.get(n, WHITE) == WHITE and dfs(n) for n in list(graph)
    )


def validate_sidecar_data(data: Any) -> List[str]:
    """sidecar 全键 schema 校验；返回问题清单（空 = 合法）。None = 零声明合法。"""
    issues: List[str] = []
    if data is None:
        return issues
    if not isinstance(data, dict):
        return ["sidecar 根节点必须是 JSON 对象"]
    flow = data.get("flow")
    if flow is not None and not isinstance(flow, dict):
        issues.append("flow 必须是 JSON 对象")
        flow = None
    flow = flow or {}
    steps = _check_steps(flow.get("steps"), issues)
    step_nos = _step_nos_of(steps)
    has_steps = bool(steps)
    deps = _check_dependencies(
        flow.get("dependencies"), step_nos, has_steps, issues)
    _check_step_keyed(
        "stage_executors", flow.get("stage_executors"),
        step_nos, has_steps, _check_exec_list, issues)
    _check_step_keyed(
        "step_stages", flow.get("step_stages"),
        step_nos, has_steps, _check_stage_value, issues)
    _check_step_keyed(
        "step_done_conditions", flow.get("step_done_conditions"),
        step_nos, has_steps, _check_stage_value, issues)
    _check_step_keyed(
        "step_short_titles", flow.get("step_short_titles"),
        step_nos, has_steps, _check_str_value, issues)
    _check_stage_overrides(flow.get("stages"), issues)
    _check_custom_sections(data.get("custom_sections"), issues)
    for bk in _FLOW_BOOL_KEYS:
        v = flow.get(bk)
        if v is not None and not isinstance(v, bool):
            issues.append(f"flow.{bk} 必须是布尔值")
    step_stages = flow.get("step_stages")
    if (
        isinstance(step_stages, dict) and isinstance(deps, dict) and deps
        and _has_stage_cycle(deps, step_stages)
    ):
        issues.append("flow.step_stages×dependencies 翻译的阶段 DAG 成环（调度死锁）")
    pause = data.get("pause")
    if pause is not None:
        if not isinstance(pause, dict):
            issues.append("pause 必须是 JSON 对象")
        else:
            sp = pause.get("stage_pause")
            if sp is not None and not isinstance(sp, bool):
                issues.append("pause.stage_pause 必须是布尔值")
    # v3 新增键（任务#34 B1）：全部可选，未声明=零预设，非法 fail-closed
    _check_schema_version(data, issues)
    _check_kind(data, issues)
    _check_requires_inputs(data.get("requires_inputs"), issues)
    _check_language(data.get("language"), issues)
    _check_pause_points(data.get("pause_points"), issues)
    _check_scripts(data.get("scripts"), issues)
    return issues
