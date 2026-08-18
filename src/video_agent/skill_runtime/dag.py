"""Skill <planner> 依赖图解析与调度（814E2）。

Skill 的 <planner> 章节常带「依赖关系：3→1,2；4→3」式声明。本模块把它
解析成 DAG，按拓扑层给出可并行批次；并结合工作台状态客观判定步骤完成度，
输出「下一步可执行批次」——调度由代码计算（P2 约束下沉），主模型只执行。

步骤/依赖双通道：manifest flow.steps/dependencies 声明优先（确定性），
未声明回落正文解析（存量兼容）；resolve_steps_and_deps 是唯一入口。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS

# 步骤行：1. / 1、 / 1) 开头的编号行
_STEP_RE = re.compile(r"(?m)^\s*(\d+)\s*[\.、)]\s*(.+)$")
# 依赖行：3→1,2；4→3（允许中文分号分隔多对；末对后跟换行/句号也闭合）
_DEP_RE = re.compile(r"(\d+)\s*→\s*([0-9,\s]+?)(?=[；;。．.\n]|$)")


def parse_steps(planner_text: str) -> Dict[int, str]:
    """解析编号步骤：{步骤号: 步骤文本}（去掉行尾 **tool** 标记保留语义文本）。

    同号冲突后来居上：生产流程列表通常排在启动协议/检查清单之后，
    后者才是依赖声明指向的真实步骤。
    """
    steps: Dict[int, str] = {}
    for m in _STEP_RE.finditer(planner_text or ""):
        no = int(m.group(1))
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(2)).strip()
        if text:
            steps[no] = text
    return steps


def parse_dependencies(planner_text: str) -> Dict[int, List[int]]:
    """解析依赖行：{步骤号: [前置步骤号]}；未出现在依赖行的步骤前置为空。"""
    deps: Dict[int, List[int]] = {}
    for m in _DEP_RE.finditer(planner_text or ""):
        target = int(m.group(1))
        prereq = [int(x) for x in re.findall(r"\d+", m.group(2))]
        deps.setdefault(target, []).extend(prereq)
    return deps


def topo_batches(steps: Dict[int, str], deps: Dict[int, List[int]]) -> List[List[int]]:
    """按拓扑层分批：同层步骤互不依赖，可并行执行。

    环/未知前置防御：未知前置忽略；剩余成环步骤追加到末层（不丢步骤）。
    """
    done: set = set()
    remaining = set(steps.keys())
    batches: List[List[int]] = []
    while remaining:
        layer = sorted(
            n for n in remaining
            if all(d not in remaining or d in done for d in deps.get(n, []))
        )
        if not layer:
            # 成环兜底：整层强排，避免死循环
            layer = sorted(remaining)
        batches.append(layer)
        done.update(layer)
        remaining -= set(layer)
    return batches


def step_done(no: int, text: str, state: Dict[str, Any], conditions: Optional[Dict[str, str]] = None) -> bool:
    """步骤完成度客观判定（只认状态事实，认不出的视为未完成）。

    B4b/F32：manifest 声明 step_done_conditions（步骤号→状态键）时按声明评估
    （确定性题归系统）；未声明回落关键字猜测（兼容存量 Skill）。"""
    if conditions and str(no) in conditions:
        key = conditions[str(no)]
        ke = state.get(CAT_KEY_ELEMENTS) or []
        shots = state.get(CAT_SHOTS) or []
        audio = state.get(CAT_AUDIO_ITEMS) or []
        if key == "spec":
            from src.video_agent.core.prompt_gates import has_spec_document
            return has_spec_document(state)
        if key == "analysis":
            return bool((state.get("analysis") or {}).get("summary"))
        if key == CAT_KEY_ELEMENTS:
            return bool(ke)
        if key == "ke_media":
            return bool(ke) and any(
                (d.get("imgUrl") or "").strip()
                for g in ke for d in (g.get("drafts") or []) if isinstance(d, dict)
            )
        if key == CAT_SHOTS:
            return bool(shots)
        if key == "audio":
            return bool(audio)
        if key in ("shot_video", "assembly", "video"):
            return bool(shots) and any(
                (d.get("videoUrl") or "").strip()
                for g in shots for d in (g.get("drafts") or []) if isinstance(d, dict)
            )
        return False
    t = (text or "").lower()
    ke = state.get(CAT_KEY_ELEMENTS) or []
    shots = state.get(CAT_SHOTS) or []
    audio = state.get(CAT_AUDIO_ITEMS) or []

    def _has_media(groups: List[Dict[str, Any]], field: str) -> bool:
        return any(
            (d.get(field) or "").strip()
            for g in groups for d in (g.get("drafts") or []) if isinstance(d, dict)
        )

    if "规格" in t or "spec" in t:
        from src.video_agent.core.prompt_gates import has_spec_document

        return has_spec_document(state)
    if "设定图" in t or "概念图" in t or ("生成" in t and "关键元素" in t):
        return bool(ke) and _has_media(ke, "imgUrl")
    if "分镜" in t or "shot" in t:
        return bool(shots)
    if "关键元素" in t or "key_element" in t or "keyelement" in t:
        return bool(ke)
    if "音频" in t or "audio" in t:
        return bool(audio)
    if "视频" in t or "video" in t:
        return bool(shots) and _has_media(shots, "videoUrl")
    if "组装" in t or "时间线" in t or "剪辑" in t:
        return bool(shots) and _has_media(shots, "videoUrl")
    if "分析" in t or "读取" in t or "剧本" in t:
        return bool((state.get("analysis") or {}).get("summary"))
    return False


def resolve_steps_and_deps(
    manifest: Optional[Dict[str, Any]], planner_text: str,
) -> Tuple[Dict[int, str], Dict[int, List[int]]]:
    """步骤/依赖统一入口：manifest flow.steps/dependencies 声明优先
    （Skill 单一事实源，确定性调度）；未声明回落正文解析（存量兼容）。"""
    flow = ((manifest or {}).get("flow") or {})
    raw_steps = flow.get("steps")
    if isinstance(raw_steps, dict) and raw_steps:
        steps: Dict[int, str] = {}
        for k, v in raw_steps.items():
            try:
                no = int(str(k).strip())
            except (TypeError, ValueError):
                continue
            text = str(v or "").strip()
            if text:
                steps[no] = text
        deps: Dict[int, List[int]] = {}
        raw_deps = flow.get("dependencies") or {}
        if isinstance(raw_deps, dict):
            for k, v in raw_deps.items():
                try:
                    no = int(str(k).strip())
                except (TypeError, ValueError):
                    continue
                if not isinstance(v, (list, tuple)):
                    continue
                prereq: List[int] = []
                for x in v:
                    try:
                        prereq.append(int(x))
                    except (TypeError, ValueError):
                        continue
                deps[no] = prereq
        return steps, deps
    return parse_steps(planner_text), parse_dependencies(planner_text)


def lint_planner_dag(planner_text: str, manifest: Optional[Dict[str, Any]]) -> List[str]:
    """<planner> 结构体检（注册期门禁用）：依赖引用必须命中步骤；
    未声明 steps 时同号编号冲突也报出。返回问题描述列表（空 = 健康）。"""
    issues: List[str] = []
    flow = ((manifest or {}).get("flow") or {})
    declared = isinstance(flow.get("steps"), dict) and bool(flow.get("steps"))
    steps, deps = resolve_steps_and_deps(manifest, planner_text)
    if not declared:
        counts: Dict[int, int] = {}
        for m in _STEP_RE.finditer(planner_text or ""):
            counts[int(m.group(1))] = counts.get(int(m.group(1)), 0) + 1
        dup = sorted(no for no, c in counts.items() if c > 1)
        if dup:
            issues.append(
                f"正文编号列表同号冲突（后来居上）：步骤号 {dup}；"
                "建议 manifest flow.steps 显式声明流程步骤"
            )
    for target in sorted(deps):
        if target not in steps:
            issues.append(f"依赖声明 {target}→… 的步骤 {target} 不在步骤列表中")
        for pre in deps[target]:
            if pre not in steps:
                issues.append(f"依赖声明 {target}→{pre} 的前置步骤 {pre} 不在步骤列表中")
    return issues


def pipeline_status_from(
    steps: Dict[int, str], deps: Dict[int, List[int]],
    state: Dict[str, Any], conditions: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """全步骤状态 + 下一可执行批次（依赖满足且未完成）。"""
    status = []
    done_nos = set()
    for no in sorted(steps):
        d = step_done(no, steps[no], state, conditions)
        if d:
            done_nos.add(no)
        status.append({"step": no, "title": steps[no][:60], "done": d, "ready": False})
    by_no = {s["step"]: s for s in status}
    ready = [
        no for no in sorted(steps)
        if no not in done_nos and all(d in done_nos for d in deps.get(no, []))
    ]
    for no in ready:
        by_no[no]["ready"] = True
    return status


def pipeline_status(planner_text: str, state: Dict[str, Any], conditions: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """正文解析兼容入口（声明通道走 resolve_steps_and_deps + pipeline_status_from）。"""
    return pipeline_status_from(
        parse_steps(planner_text), parse_dependencies(planner_text), state, conditions)
