# -*- coding: utf-8 -*-
"""Skill 声明 schema 校验器（手写结构校验，零新依赖，禁 jsonschema）。

任务#5 frontmatter 合一：声明唯一源 = Skill 文档头部 YAML frontmatter
（外置 JSON sidecar 随 data/skills_manifests/ 一并退役）。

语义口径：
- fail-closed：已声明键形状非法 → 报出（注册期门禁告警、workflow 编译门禁拒入）；
- 未声明键合法：引擎零预设，回落旧行为（「零声明 = 最小闸」同构）。

流程步骤抄本废除（用户裁决）：flow.steps / flow.step_stages /
flow.dependencies 通道废止——Skill 正文 planner 是唯一流程源，
frontmatter 声明这三键 = fail-hard 报出（注册期拒注册）。
step 键控声明（stage_executors/step_done_conditions/step_short_titles）
保留形状校验但不再对照 steps 检查引用（steps 已废除）。

校验键清单（flow 下）：stage_executors / step_done_conditions /
step_short_titles / stages.<规范键>.{done,skip,executors} /
布尔开关（spec_wizard/spec_gate/script_required）；顶层 pause.stage_pause；
顶层 custom_sections（自定义章节→通用执行器通道，P3-15）；
顶层 gates（键白名单 fail-hard）/ version / tools_required / source。

gates 键白名单与 core.prompt_gates._DEFAULT_GATE_RULES 键集同值复制
（skill_runtime 不得反向 import core，分层约束），漂移由
tests/unit/test_sidecar_schema_v2.py 的锁源断言钉死；规范阶段键
同 pipeline_orchestrator.CANONICAL_STAGES 复制口径。
"""
from typing import Any, Dict, List

# 与 pipeline_orchestrator.CANONICAL_STAGES 键序一致（漂移锁源见测试）
CANONICAL_STAGE_KEYS = (
    "analysis", "spec", "structure", "ke_media",
    "shot_media", "audio_assets", "assembly",
)

# gates 键白名单（与 prompt_gates._DEFAULT_GATE_RULES 键集同源复制；
# 未知 gate 名 fail-hard 拒注册——声明了平台不消费的闸键 = 配置漂移）
GATE_KEYS = (
    "shot_min_chars", "element_min_chars", "cjk_min_ratio",
    "require_duration", "require_subtitle", "require_camera_language",
    "require_audio_layer", "require_at_ref",
    "subtitle_synonyms", "camera_markers", "audio_markers",
)

# 已废除的流程抄本通道（声明即 fail-hard：正文 planner 是唯一流程源）
DEPRECATED_FLOW_KEYS = ("steps", "step_stages", "dependencies")

_FLOW_BOOL_KEYS = ("spec_wizard", "spec_gate", "script_required")
_STAGE_OVERRIDE_KEYS = ("done", "skip", "executors")
_DONE_PREFIX = "document:"
_PAUSE_KEYS = ("stage_pause",)

# custom_sections 声明的合法执行器白名单（P3-15 自定义章节通道）：
# 通道单一 = 通用章节执行器 skill_section_run（与 prompts/planner/
# executor_runtime.md「无专属执行器的章节用 skill_section_run」同源语义）；
# 未来若增专属通用执行器，先在此登记再允许声明（fail-closed）。
CUSTOM_SECTION_EXECUTORS = ("skill_section_run",)

# ---------- v3 键白名单（任务#34 B1 沿用） ----------
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


def _check_step_keyed(
    name: str, raw: Any, check_value, issues: List[str],
) -> None:
    """step 键控声明形状校验（步骤号→声明值）。

    steps 通道废除后不再对照 steps 检查步骤号引用，只校验值形状。
    """
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append(f"flow.{name} 必须是对象（步骤号→声明值）")
        return
    for k, v in raw.items():
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
        issues.append("custom_sections 必须是对象（章节标识→执行器名）")
        return
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            issues.append(f"custom_sections 章节标识 {k!r} 必须是非空字符串")
            continue
        if not isinstance(v, str) or v not in CUSTOM_SECTION_EXECUTORS:
            issues.append(
                f"custom_sections[{k}] 执行器必须是 "
                f"{'/'.join(CUSTOM_SECTION_EXECUTORS)} 之一（实际 {v!r}）")


def _check_gates(raw: Any, issues: List[str]) -> None:
    """gates：键白名单 fail-hard（任务#5）——未知 gate 名拒注册。

    白名单 = prompt_gates._DEFAULT_GATE_RULES 键集（平台消费的全部闸键）；
    值类型清洗归消费端 parse_gate_rules（与旧口径一致）。"""
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append("gates 必须是对象（闸键→声明值）")
        return
    for k in raw:
        if k not in GATE_KEYS:
            issues.append(
                f"gates.{k} 不是平台登记的闸键"
                f"（白名单：{'/'.join(GATE_KEYS)}）")


def _check_version(raw: Any, issues: List[str]) -> None:
    """version：Skill 声明版本（插件包约定；非空字符串，未声明合法）。"""
    if raw is None:
        return
    if not isinstance(raw, str) or not raw.strip():
        issues.append("version 必须是非空字符串（如 \"1.0\"）")


def _check_tools_required(raw: Any, issues: List[str]) -> None:
    """tools_required：平台工具依赖声明（非空字符串数组；未声明合法）。

    声明工具是否存在于平台工具注册表由 scripts/scan_skills.py --gate 核对，
    缺失输出 PENDING 报告（复用「待平台补齐」机制）；schema 只管形状。"""
    if raw is None:
        return
    if not isinstance(raw, list):
        issues.append("tools_required 必须是数组（平台工具名）")
        return
    for i, t in enumerate(raw):
        if not isinstance(t, str) or not t.strip():
            issues.append(f"tools_required[{i}] 必须是非空字符串（工具名）")


def _check_source(raw: Any, issues: List[str]) -> None:
    """source：外部导入来源标记（非空字符串，未声明合法）。"""
    if raw is None:
        return
    if not isinstance(raw, str) or not raw.strip():
        issues.append("source 必须是非空字符串（导入来源标记）")


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
    （插件包资源约定未落地脚本执行；空声明 = 未声明，零预设）。"""
    if raw is None:
        return
    if raw:  # 非空对象/数组/字符串等均视为「已声明」
        issues.append("scripts 暂不支持（当前版本不消费该键，声明已忽略）")


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


def validate_manifest_data(data: Any) -> List[str]:
    """frontmatter 声明全键 schema 校验；返回问题清单（空 = 合法）。

    None = 零声明合法。frontmatter YAML 解析失败时 load_manifest 返回
    带 _parse_error 键的哨兵对象，此处转为问题报出（注册期 fail-hard）。
    """
    issues: List[str] = []
    if data is None:
        return issues
    if not isinstance(data, dict):
        return ["frontmatter 根节点必须是 YAML 对象"]
    err = data.get("_parse_error")
    if err:
        return [str(err)]
    flow = data.get("flow")
    if flow is not None and not isinstance(flow, dict):
        issues.append("flow 必须是对象")
        flow = None
    flow = flow or {}
    # 流程步骤抄本通道废除（任务#5）：声明即 fail-hard
    for dk in DEPRECATED_FLOW_KEYS:
        if dk in flow:
            issues.append(
                f"flow.{dk} 已废除：Skill 正文 planner 是唯一流程源，"
                f"请从 frontmatter 移除该声明")
    _check_step_keyed(
        "stage_executors", flow.get("stage_executors"), _check_exec_list, issues)
    _check_step_keyed(
        "step_done_conditions", flow.get("step_done_conditions"),
        _check_stage_value, issues)
    _check_step_keyed(
        "step_short_titles", flow.get("step_short_titles"),
        _check_str_value, issues)
    _check_stage_overrides(flow.get("stages"), issues)
    for bk in _FLOW_BOOL_KEYS:
        v = flow.get(bk)
        if v is not None and not isinstance(v, bool):
            issues.append(f"flow.{bk} 必须是布尔值")
    _check_custom_sections(data.get("custom_sections"), issues)
    _check_gates(data.get("gates"), issues)
    _check_version(data.get("version"), issues)
    _check_tools_required(data.get("tools_required"), issues)
    _check_source(data.get("source"), issues)
    pause = data.get("pause")
    if pause is not None:
        if not isinstance(pause, dict):
            issues.append("pause 必须是对象")
        else:
            sp = pause.get("stage_pause")
            if sp is not None and not isinstance(sp, bool):
                issues.append("pause.stage_pause 必须是布尔值")
    # v3 键：全部可选，未声明=零预设，非法 fail-closed
    _check_schema_version(data, issues)
    _check_kind(data, issues)
    _check_requires_inputs(data.get("requires_inputs"), issues)
    _check_language(data.get("language"), issues)
    _check_pause_points(data.get("pause_points"), issues)
    _check_scripts(data.get("scripts"), issues)
    return issues
