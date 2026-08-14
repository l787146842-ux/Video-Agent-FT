"""Skill <planner> 依赖图解析与调度（814E2）。

Skill 的 <planner> 章节常带「依赖关系：3→1,2；4→3」式声明。本模块把它
解析成 DAG，按拓扑层给出可并行批次；并结合工作台状态客观判定步骤完成度，
输出「下一步可执行批次」——调度由代码计算（P2 约束下沉），主模型只执行。
"""
import re
from typing import Any, Dict, List

# 步骤行：1. / 1、 / 1) 开头的编号行
_STEP_RE = re.compile(r"(?m)^\s*(\d+)\s*[\.、)]\s*(.+)$")
# 依赖行：3→1,2；4→3（允许中文分号分隔多对）
_DEP_RE = re.compile(r"(\d+)\s*→\s*([0-9,\s]+?)(?=[；;]|$)")


def parse_steps(planner_text: str) -> Dict[int, str]:
    """解析编号步骤：{步骤号: 步骤文本}（去掉行尾 **tool** 标记保留语义文本）。"""
    steps: Dict[int, str] = {}
    for m in _STEP_RE.finditer(planner_text or ""):
        no = int(m.group(1))
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(2)).strip()
        if text and no not in steps:
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


def step_done(no: int, text: str, state: Dict[str, Any]) -> bool:
    """步骤完成度客观判定（只认状态事实，认不出的视为未完成）。"""
    t = (text or "").lower()
    ke = state.get("keyElements") or []
    shots = state.get("shots") or []
    audio = state.get("audioItems") or []

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


def pipeline_status(planner_text: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """全步骤状态 + 下一可执行批次（依赖满足且未完成）。"""
    steps = parse_steps(planner_text)
    deps = parse_dependencies(planner_text)
    status = []
    done_nos = set()
    for no in sorted(steps):
        d = step_done(no, steps[no], state)
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
