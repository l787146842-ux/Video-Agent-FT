"""Skill 执行器校验/应用层（A1：主模型产出，本层按 Skill 章节把关）。

职责：
- 结构阶段剥离内联提示词（storyboard_key_elements / storyboard_shots / storyboard_audio 只建结构）
- 提示词硬性条款写入前拒绝（决策 D：质量优先；用户坚持时降为警告）
"""
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.core import prompt_gates
from src.video_agent.core.guard_pipeline import prompt_write_verdict
from src.video_agent.skill_runtime.registry import resolve_entry, parse_pause_rules
from src.video_agent.skill_runtime.sidecar_schema import PAUSE_TRIGGER_VALUES


def strip_draft_prompt(draft: Dict[str, Any]) -> bool:
    """从单个 draft 中移除生成提示词；返回是否发生剥离。"""
    if not isinstance(draft, dict):
        return False
    if str(draft.get("prompt") or "").strip():
        draft["prompt"] = ""
        return True
    return False


def strip_structure_actions(actions: List[Dict[str, Any]]) -> int:
    """把 add_group / add_draft 动作中携带的内联详细提示词剥离（结构阶段）。

    仅处理动作本身，不修改状态；返回剥离条数。
    """
    stripped = 0
    for a in actions or []:
        name = str(a.get("action") or a.get("type") or "").strip()
        if name in ("add_group", "add_keyElement", "add_shot", "add_audio"):
            for d in (a.get("drafts") or []):
                if strip_draft_prompt(d):
                    stripped += 1
            d0 = a.get("draft")
            if isinstance(d0, dict) and strip_draft_prompt(d0):
                stripped += 1
        elif name == "add_draft":
            d = a.get("draft")
            if isinstance(d, dict) and strip_draft_prompt(d):
                stripped += 1
    return stripped


def validate_prompt_hard(
    prompt: str,
    kind: str,
    state: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
    user_override: bool = False,
) -> Tuple[bool, List[str], List[str]]:
    """提示词硬性条款校验（决策 D：质量优先）。

    返回 (ok, hard_errors, soft_warnings)：
    - 无硬伤或用户坚持（user_override=True）→ ok=True（用户坚持时 hard 并入警告）
    - 有硬伤且未坚持 → ok=False，调用方应拒绝写入
    """
    """提示词硬性条款校验（决策 D：质量优先），委托统一闸机管线（宪法 §2.0）。"""
    verdict = prompt_write_verdict(
        prompt, kind, state,
        gate_rules=rules,
        user_override=user_override,
        gate_enabled=True,
    )
    if verdict.ok:
        if verdict.message:
            return True, [], [verdict.message]
        return True, [], []
    hard = [verdict.message] if verdict.message else ["提示词结构校验未通过"]
    return False, hard, []


def skill_requires_stage_pause(skill_name: str) -> bool:
    """按 Skill 声明判断是否要求阶段暂停（对外 bool 兼容语义，调用方不改行为）。

    判定 = skill_pause_points 非空；四级优先级见 skill_pause_points。
    v2 存量（无 pause_points 声明）行为与旧实现逐一等价：
    manifest pause.stage_pause > pause_rules 声明块 > 关键词兜底。"""
    return bool(skill_pause_points(skill_name))


# stage_pause（bool）机械转暂停点清单的两个锚点（与 scripts/migrate_manifests_v3.py
# V3_ANCHOR_PAUSE_POINTS 同口径：迁移完成后两侧语义自然合流，id 与 trigger 同名）
_STAGE_PAUSE_ANCHOR_POINTS: Tuple[Dict[str, Any], ...] = (
    {"id": "storyboard_structure_ready", "trigger": "storyboard_structure_ready"},
    {"id": "first_generation_call", "trigger": "first_generation_call"},
)


def _clean_pause_points(raw: List[Any]) -> List[Dict[str, Any]]:
    """manifest pause_points 声明清洗（fail-closed，与 schema 同口径）：
    trigger 白名单外/id 缺失/batch_boundary 缺 description/free_text 缺 prose 的项丢弃。"""
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        trigger = item.get("trigger")
        if not isinstance(pid, str) or not pid.strip():
            continue
        if trigger not in PAUSE_TRIGGER_VALUES:
            continue
        point: Dict[str, Any] = {"id": pid.strip(), "trigger": trigger}
        if trigger == "batch_boundary":
            desc = item.get("description")
            if not isinstance(desc, str) or not desc.strip():
                continue
            point["description"] = desc.strip()
        elif trigger == "free_text":
            prose = item.get("prose")
            if not isinstance(prose, str) or not prose.strip():
                continue
            point["prose"] = prose.strip()
        out.append(point)
    return out


def skill_pause_points(skill_name: str) -> List[Dict[str, Any]]:
    """通用暂停点清单（任务#35 B3），四级优先级：

    1. manifest pause_points 声明（v3，列表形态即接管；非法项 fail-closed 丢弃）；
    2. pause.stage_pause（bool 机械转两锚点：storyboard_structure_ready/
       first_generation_call；false = 显式关闭，返回空表）；
    3. 文档 pause_rules 声明块（兼容存量，同机械转口径）；
    4. 关键词兜底：存在『何时暂停/强制暂停点』字样即视为要求（同两锚点）。

    未命中任一级返回空表（不要求暂停）。每项含 id/trigger，
    batch_boundary 附 description、free_text 附 prose（trigger 白名单与
    sidecar_schema 同源）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return []
    manifest = entry.manifest or {}
    raw_pps = manifest.get("pause_points")
    if isinstance(raw_pps, list):
        return _clean_pause_points(raw_pps)
    manifest_pause = manifest.get("pause") or {}
    if isinstance(manifest_pause, dict) and "stage_pause" in manifest_pause:
        if bool(manifest_pause["stage_pause"]):
            return [dict(p) for p in _STAGE_PAUSE_ANCHOR_POINTS]
        return []
    content = entry.content or ""
    rules = parse_pause_rules(content)
    if rules is not None and "stage_pause" in rules:
        if bool(rules["stage_pause"]):
            return [dict(p) for p in _STAGE_PAUSE_ANCHOR_POINTS]
        return []
    if "何时暂停" in content or "强制暂停点" in content:
        return [dict(p) for p in _STAGE_PAUSE_ANCHOR_POINTS]
    return []


def skill_planner_flow(skill_name: str, limit: int = 6000) -> str:
    """当前 Skill 的 <planner> 流程章节（主模型流程基线）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return ""
    flow = entry.sections.get("planning") or ""
    if len(flow) > limit:
        flow = flow[:limit] + "\n……（流程章节超长已截断）"
    return flow
