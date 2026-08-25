# -*- coding: utf-8 -*-
"""Skill 声明 schema 校验器（手写结构校验，零新依赖，禁 jsonschema）。

声明唯一源 = Skill 文档头部 YAML frontmatter。

语义口径：
- fail-closed：已声明键形状非法 → 报出（注册期门禁告警、workflow 编译门禁拒入）；
- 未声明键合法：引擎零预设，回落旧行为（「零声明 = 最小闸」同构）。

问题分级：issues 条目以 WARN_PREFIX 开头 = 告警级
（不拒注册，注册期输出告警/遥测）；其余 = 错误级（fail-hard）。消费端
经 split_issue_warnings 拆分（registry 注册门禁、workflow 编译门禁只按
错误级拒入）。

流程步骤抄本废除：flow.steps / flow.step_stages /
flow.dependencies 通道废止——Skill 正文 planner 是唯一流程源，
frontmatter 声明这三键 = fail-hard 报出（注册期拒注册）。

僵尸键废除迁移：step 键控声明 stage_executors /
step_done_conditions / step_short_titles 的步骤号全部抄自已废除的
flow.steps 通道，生产链路无实际消费者（现存读取点均被 steps/
dependencies 空声明闸住 = 死路径）——声明即输出 WARN 级过渡告警
（不拒注册）。时序：本版本 = WARN 过渡告警 + 存量迁移脚本清键
（scripts/archive/migrate_zombie_step_keys.py）；下一版本清验存量归零后
升级为 fail-hard（同 DEPRECATED_FLOW_KEYS 语义）。

校验键清单（flow 下）：僵尸键过渡告警（stage_executors /
step_done_conditions / step_short_titles，声明即 WARN） /
stages 双形态——对象 = stages.<规范键>.{done,skip,executors} 覆盖声明；
数组 = workflow 结构声明（每项 {key,title,probe|review,
executor?,deterministic?}，compile_definition 据此派生节点拓扑；
未声明回落 default_v2_workflow，零回归） /
布尔开关（spec_wizard/spec_gate/script_required）；顶层 pause.stage_pause；
顶层 custom_sections（自定义章节→通用执行器通道）；
顶层 gates（键白名单 fail-hard）/ version / tools_required / source。

gates 键白名单与 core.prompt_gates._DEFAULT_GATE_RULES 键集同值复制
（skill_runtime 不得反向 import core，分层约束），漂移由
tests/unit/test_sidecar_schema_v2.py 的锁源断言钉死；规范阶段键
同 stage_probes.CANONICAL_STAGES 复制口径。

扩展逃生舱约定（对齐 Agent Skills 开放标准）：
frontmatter 顶层 `metadata` 自由 map（string→string，开放标准
官方逃生舱语义，如 metadata.version / metadata.author）与 `x-` 前缀键
（如 x-acme-review）一律校验器忽略——不 WARN、不拒注册、不校验形状，
frontmatter 任意键原样透传，便于将来与 Agent Skills 开放标准互转
（逃生舱键双向搬运不产生校验噪音）。防冲突约定：metadata 命名空间内
键名与 x- 后缀建议带厂商/团队前缀（如 metadata."acme.market_id"），
避免与平台未来登记键或其他导入源撞键。判定归一入口 is_extension_key；
本清单校验只按登记表消费键，扩展键不进任何 _check_* 路径。
"""
from typing import Any, Dict, List, Tuple

# 告警级问题前缀：validate 返回清单中以此开头的条目为
# WARN（开放注册降级/废除键过渡告警），不触发 fail-hard 拒注册；
# 其余条目为错误级。消费端用 split_issue_warnings 拆分。
WARN_PREFIX = "[WARN] "


# ---------- 扩展逃生舱（对齐 Agent Skills 开放标准） ----------
# 顶层 metadata 自由 map 与 x- 前缀键：校验器一律忽略（不 WARN、不拒
# 注册、不校验形状），frontmatter 原样透传，便于将来与开放标准互转。
# 防冲突约定：命名空间内键名建议带厂商/团队前缀（详见模块 docstring）。
EXTENSION_KEY_PREFIX = "x-"
METADATA_KEY = "metadata"


def is_extension_key(key: Any) -> bool:
    """扩展逃生舱键判定：顶层 metadata 自由 map 与 x- 前缀键
    （对齐 Agent Skills 开放标准逃生舱语义）。

    命中键由 validate_manifest_data 一律忽略（不 WARN、不拒注册），
    frontmatter 读写原样透传；与开放标准互转意图见模块 docstring。
    """
    return key == METADATA_KEY or (
        isinstance(key, str) and key.startswith(EXTENSION_KEY_PREFIX))


def split_issue_warnings(issues: List[str]) -> Tuple[List[str], List[str]]:
    """校验问题清单 → (错误级, 告警级)；告警级剥掉 WARN_PREFIX 前缀。"""
    errors: List[str] = []
    warnings: List[str] = []
    for i in issues or []:
        if str(i).startswith(WARN_PREFIX):
            warnings.append(str(i)[len(WARN_PREFIX):])
        else:
            errors.append(str(i))
    return errors, warnings


# 与 stage_probes.CANONICAL_STAGES 键序一致（漂移锁源见测试）
CANONICAL_STAGE_KEYS = (
    "analysis", "spec", "structure", "ke_media",
    "shot_media", "audio_assets", "assembly",
)

# workflow 结构声明（flow.stages 数组形态）可用的客观探针键白名单：
# 规范阶段键 + 节点级结构探针键（key_elements/shots_groups/audio_groups，
# 与 workflow_runtime _NODE_STRUCTURE_KEYS 同集；此三键在覆盖声明 dict
# 形态里仍不可经 stages.<key>.done 覆盖，此处仅作探针挂接白名单）。
WORKFLOW_STAGE_PROBE_KEYS = CANONICAL_STAGE_KEYS + (
    "key_elements", "shots_groups", "audio_groups",
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

# 僵尸键：步骤号键控声明，步骤号来源 flow.steps 已废除，生产链路
# 无消费者（现存读取点均被 steps/dependencies 空声明闸住 = 死路径）。
# 本版本声明即 WARN 过渡告警（不拒注册）；下一版本存量清零后升 fail-hard。
ZOMBIE_STEP_KEYS = ("stage_executors", "step_done_conditions", "step_short_titles")

_FLOW_BOOL_KEYS = ("spec_wizard", "spec_gate", "script_required")
_STAGE_OVERRIDE_KEYS = ("done", "skip", "executors")
# workflow 结构声明每项的合法键（白名单外键 fail-closed 报出）
_WORKFLOW_STAGE_DECL_KEYS = ("key", "title", "probe", "review", "executor", "deterministic")
_DONE_PREFIX = "document:"
_PAUSE_KEYS = ("stage_pause",)

# custom_sections 声明的合法执行器白名单（自定义章节通道）：
# 通道单一 = 通用章节执行器 skill_section_run（与 prompts/planner/
# executor_runtime.md「无专属执行器的章节用 skill_section_run」同源语义）；
# 未来若增专属通用执行器，先在此登记再允许声明（fail-closed）。
CUSTOM_SECTION_EXECUTORS = ("skill_section_run",)

# ---------- v3 键白名单 ----------
SCHEMA_VERSION = 3
_KIND_VALUES = ("pipeline", "style", "reference")
_REQUIRES_INPUT_TYPES = ("script", "music", "video", "image", "doc")
_LANGUAGE_VALUES = ("zh", "en", "auto")
_PAUSE_TRIGGER_VALUES = (
    "spec_finalized", "storyboard_structure_ready",
    "first_generation_call", "batch_boundary", "free_text",
)

# 公开别名（消费端同源读取：registry 声明 API / guard 暂停点
# 清洗同读此白名单，消费侧不再各自硬编码；校验语义仍归本模块 _check_*）
KIND_VALUES = _KIND_VALUES
REQUIRES_INPUT_TYPES = _REQUIRES_INPUT_TYPES
LANGUAGE_VALUES = _LANGUAGE_VALUES
PAUSE_TRIGGER_VALUES = _PAUSE_TRIGGER_VALUES


def _check_exec_list(name: str, k: Any, v: Any, issues: List[str]) -> None:
    if not isinstance(v, list) or not all(
        isinstance(x, str) and x.strip() for x in v
    ):
        issues.append(f"flow.{name}[{k}] 必须是非空字符串数组（执行器名）")


def _check_zombie_step_keys(flow: Dict[str, Any], issues: List[str]) -> None:
    """僵尸键过渡告警：声明即 WARN，不拒注册、不再校验形状
    （键已无消费者，形状对错无意义）。时序：本版本 WARN + 存量迁移
    清键；下一版本升级为 fail-hard（同 DEPRECATED_FLOW_KEYS）。"""
    for zk in ZOMBIE_STEP_KEYS:
        if zk in flow:
            issues.append(
                WARN_PREFIX
                + f"flow.{zk} 是已废除 steps 通道的僵尸键（无消费者），"
                "请从 frontmatter 移除（scripts/archive/migrate_zombie_step_keys.py）；"
                "下一版本将升级为拒注册")


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
    """gates：键白名单 fail-hard——未知 gate 名拒注册。

    白名单 = prompt_gates._DEFAULT_GATE_RULES 键集（平台消费的全部闸键）；
    值类型清洗归消费端 parse_gate_rules。"""
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
    """kind：开放注册——已知 pipeline/style/reference 走各自
    注入策略；未知取值不拒注册，降级为默认（pipeline）注入策略并输出
    WARN（注册期告警/遥测），为 writing/office 等新场景预留扩展位。
    kind 只管注入策略这一个维度，闸机语义/UI 呈现不绑到 kind 上。"""
    v = data.get("kind")
    if v is None:
        return
    if v not in _KIND_VALUES:
        issues.append(
            WARN_PREFIX
            + f"kind {v!r} 不在平台 kind 登记表（{'/'.join(_KIND_VALUES)}）；"
            "按开放注册降级为默认（pipeline）注入策略")


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


def _check_workflow_stages(stages: Any, issues: List[str]) -> None:
    """flow.stages 数组形态 = workflow 结构声明。

    每项 {key, title} 必填 + probe/review 二选一挂客观探针或评审暂停；
    无法映射探针的自定义 stage 按 fail-closed 原则 **ERROR 级拒入**
    （与「已声明键形状非法 fail-hard」门禁口径一致：无探针节点永远
    无法客观完成，放行只会产出死 workflow，不如注册期就钉死）。
    前置依赖固定线性链（声明次序），不开放依赖图声明
    （flow.dependencies 通道已废除，口径不回潮）。
    """
    if not stages:
        issues.append("flow.stages 数组声明不能为空（未声明请整键移除）")
        return
    seen = set()
    for i, item in enumerate(stages):
        if not isinstance(item, dict):
            issues.append(f"flow.stages[{i}] 必须是对象 {{key, title, probe|review, ...}}")
            continue
        for uk in item:
            if uk not in _WORKFLOW_STAGE_DECL_KEYS:
                issues.append(
                    f"flow.stages[{i}].{uk} 不是合法声明键"
                    f"（白名单：{'/'.join(_WORKFLOW_STAGE_DECL_KEYS)}）")
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            issues.append(f"flow.stages[{i}].key 必须是非空字符串（节点标识）")
            continue
        if key.strip() in seen:
            issues.append(f"flow.stages[{i}].key {key!r} 重复（节点标识必须唯一）")
            continue
        seen.add(key.strip())
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            issues.append(f"flow.stages[{i}].title 必须是非空字符串（节点标题）")
        probe, review = item.get("probe"), item.get("review")
        if review is not None and not isinstance(review, bool):
            issues.append(f"flow.stages[{i}].review 必须是布尔值")
            continue
        if review:
            if probe is not None:
                issues.append(
                    f"flow.stages[{i}] probe 与 review 互斥（评审暂停节点"
                    "完成度 = 前置探针 + 账本决议事件，不另挂探针）")
            if i == 0:
                issues.append(
                    f"flow.stages[{i}] 评审暂停节点不能作为首节点"
                    "（评审完成度需前置探针作证据）")
            if item.get("executor") is not None:
                issues.append(
                    f"flow.stages[{i}] 评审暂停节点执行器固定 workflow_pause，"
                    "不得声明 executor")
            continue
        if probe is None:
            issues.append(
                f"flow.stages[{i}] 必须声明 probe（客观探针键）或 review: true"
                "（fail-closed：无探针节点永远无法客观完成）")
        elif not isinstance(probe, str) or probe not in WORKFLOW_STAGE_PROBE_KEYS:
            issues.append(
                f"flow.stages[{i}].probe 必须是登记探针键"
                f"（{'/'.join(WORKFLOW_STAGE_PROBE_KEYS)}，实际 {probe!r}）")
        execs = item.get("executor")
        if execs is not None and (not isinstance(execs, str) or not execs.strip()):
            issues.append(f"flow.stages[{i}].executor 必须是非空字符串（执行器名）")
        det = item.get("deterministic")
        if det is not None and not isinstance(det, bool):
            issues.append(f"flow.stages[{i}].deterministic 必须是布尔值")


def _check_stage_overrides(stages: Any, issues: List[str]) -> None:
    if stages is None:
        return
    if isinstance(stages, list):
        _check_workflow_stages(stages, issues)
        return
    if not isinstance(stages, dict):
        issues.append(
            "flow.stages 必须是对象（规范阶段键→覆盖声明）"
            "或数组（workflow 结构声明，每项 {key, title, probe|review, ...}）")
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
    扩展逃生舱（is_extension_key：顶层 metadata 自由 map 与 x- 前缀键）
    一律忽略——不 WARN、不拒注册，原样透传待开放标准互转消费。
    """
    issues: List[str] = []
    if data is None:
        return issues
    if not isinstance(data, dict):
        return ["frontmatter 根节点必须是 YAML 对象"]
    err = data.get("_parse_error")
    if err:
        return [str(err)]
    # 扩展逃生舱显式口径：metadata / x-* 顶层键不进任何 _check_* 校验
    # 路径（本函数只按登记表消费键），声明即透传，零 WARN 零拒注册。
    flow = data.get("flow")
    if flow is not None and not isinstance(flow, dict):
        issues.append("flow 必须是对象")
        flow = None
    flow = flow or {}
    # 流程步骤抄本通道废除：声明即 fail-hard
    for dk in DEPRECATED_FLOW_KEYS:
        if dk in flow:
            issues.append(
                f"flow.{dk} 已废除：Skill 正文 planner 是唯一流程源，"
                f"请从 frontmatter 移除该声明")
    _check_zombie_step_keys(flow, issues)
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
