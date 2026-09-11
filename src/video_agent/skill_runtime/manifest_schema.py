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
executor?,deterministic?}；**不再驱动节点拓扑**——2026-09-10 阶段规则
去代码化批删除 16 节点 DAG 契约后 `compile_definition` 恒 None，
该形态只做形状校验、不产生任何运行时效果） /
布尔开关（spec_wizard/spec_gate/script_required）；顶层 pause.stage_pause；
顶层 version / source /
scripts（键声明静态校验，绝不自动执行）/ resources（目录包资源清单 +
版本锁声明，批6：形状校验首版 WARN、下版升硬；记账面保留、执法退役，
见 registry.register_skill）。

（C1a 裁决 2026-08-31：顶层 gates 键全链路删除——技能级闸层退役，
结构校验收归平台固定地板，frontmatter 不再承载闸键声明。）

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
    "analysis", "structure", "ke_media",
    "shot_media", "audio_assets", "assembly",
)
# （C1b 裁决 2026-08-31：WORKFLOW_STAGE_PROBE_KEYS/_WORKFLOW_STAGE_DECL_KEYS/
# _STAGE_OVERRIDE_KEYS/_DONE_PREFIX 随 flow.stages 机械通道退役删除。）

# 已废除的流程抄本通道（声明即 fail-hard：正文 planner 是唯一流程源）
DEPRECATED_FLOW_KEYS = ("steps", "step_stages", "dependencies")

# 僵尸键：步骤号键控声明，步骤号来源 flow.steps 已废除，生产链路
# 无消费者（现存读取点均被 steps/dependencies 空声明闸住 = 死路径）。
# 本版本声明即 WARN 过渡告警（不拒注册）；下一版本存量清零后升 fail-hard。
ZOMBIE_STEP_KEYS = ("stage_executors", "step_done_conditions", "step_short_titles")

# ---------- v3 键白名单 ----------
SCHEMA_VERSION = 3


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


def _check_version(raw: Any, issues: List[str]) -> None:
    """version：Skill 声明版本（插件包约定；非空字符串，未声明合法）。"""
    if raw is None:
        return
    if not isinstance(raw, str) or not raw.strip():
        issues.append("version 必须是非空字符串（如 \"1.0\"）")


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


def _is_safe_relative_path(v: str) -> bool:
    """包内相对路径静态校验：拒绝绝对路径（/ 或盘符开头）、父目录穿越（.. 段）
    与反斜杠形态（统一 / 口径）。只校形状，不解文件系统。"""
    s = str(v or "").strip()
    if not s or s.startswith("/") or "\\" in s or ":" in s:
        return False
    return ".." not in [p for p in s.split("/") if p]


def _check_scripts(raw: Any, issues: List[str]) -> None:
    """scripts：脚本键声明（P2-4）——只做键声明的静态校验，平台**绝不自动执行**
    任何脚本（声明仅供资源清单探针/人工查阅，执行语义从未存在）。

    形状：对象 {脚本名: 包内相对路径}；空声明 = 未声明（零预设）。
    已声明形状非法按 fail-closed 报出（注册期拒注册）；声明路径在包内是否存在
    由 scripts/scan_skills.py 资源清单探针 WARN 核对（schema 只管形状）。"""
    if raw is None or raw == {} or raw == []:
        return
    if not isinstance(raw, dict):
        issues.append("scripts 必须是对象（脚本名→包内相对路径；平台只做静态校验绝不执行）")
        return
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            issues.append(f"scripts 脚本名 {k!r} 必须是非空字符串")
            continue
        if not isinstance(v, str) or not v.strip():
            issues.append(f"scripts[{k}] 必须是非空字符串（包内相对路径）")
            continue
        if not _is_safe_relative_path(v):
            issues.append(
                f"scripts[{k}] 路径 {v!r} 必须是包内相对路径"
                "（禁止绝对路径/盘符/.. 穿越）")


_RESOURCE_SHA256_HEX = frozenset("0123456789abcdefABCDEF")


def _check_resources(raw: Any, issues: List[str]) -> None:
    """resources：目录包资源清单（批6 素材+版本锁）{rel_path: {sha256, size, mime}}。

    未声明合法（零声明 = 最小闸，存量包不受影响）。形状校验沿用僵尸键演进时序：
    本版本一律 WARN 过渡告警（不拒注册）；下一版本升级为 fail-hard。
    分层口径勿混：形状宽松，但已声明的 sha256 与实际文件不符 = 版本锁破坏，
    由注册期硬拒（归 registry.register_skill，不在此处）。
    """
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append(
            WARN_PREFIX
            + "resources 必须是对象（包内相对路径→{sha256, size, mime}）；"
            "下一版本将升级为拒注册")
        return
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            issues.append(
                WARN_PREFIX + f"resources 清单键 {k!r} 必须是非空字符串（包内相对路径）")
            continue
        if not _is_safe_relative_path(k):
            issues.append(
                WARN_PREFIX + f"resources[{k}] 路径必须是包内相对路径"
                "（禁止绝对路径/盘符/.. 穿越）")
        if not isinstance(v, dict):
            issues.append(
                WARN_PREFIX + f"resources[{k}] 必须是对象 {{sha256, size, mime}}")
            continue
        sha = v.get("sha256")
        if sha is not None and (
            not isinstance(sha, str) or len(sha) != 64
            or any(c not in _RESOURCE_SHA256_HEX for c in sha)
        ):
            issues.append(
                WARN_PREFIX + f"resources[{k}].sha256 必须是 64 位十六进制字符串")
        size = v.get("size")
        if size is not None and (
            isinstance(size, bool) or not isinstance(size, int) or size < 0
        ):
            issues.append(WARN_PREFIX + f"resources[{k}].size 必须是非负整数")
        mime = v.get("mime")
        if mime is not None and (not isinstance(mime, str) or not mime.strip()):
            issues.append(WARN_PREFIX + f"resources[{k}].mime 必须是非空字符串")


def _check_stage_overrides(stages: Any, issues: List[str]) -> None:
    """flow.stages 声明（数组 workflow 结构 / dict 阶段覆盖）。

    （C1b 裁决 2026-08-31：机械工作流层整体退役——flow.stages 编译与
    阶段覆盖通道删除，声明忽略不校验（零警告），恒用平台默认定义。）"""
    return


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
    _check_version(data.get("version"), issues)
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
    _check_scripts(data.get("scripts"), issues)
    _check_resources(data.get("resources"), issues)
    return issues
