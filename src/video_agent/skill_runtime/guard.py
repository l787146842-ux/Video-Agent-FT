"""Skill 执行器校验/应用层（A1：主模型产出，本层按 Skill 章节把关）。

职责：
- 结构阶段剥离内联提示词（storyboard_key_elements / storyboard_shots / storyboard_audio 只建结构）
- 提示词硬性条款写入前拒绝（决策 D：质量优先；用户坚持时降为警告）
"""
from typing import Any, Dict, List, Optional, Tuple

from src.video_agent.core import prompt_gates
from src.video_agent.core.guard_pipeline import prompt_write_verdict
from src.video_agent.skill_runtime.registry import resolve_entry


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
    """按 Skill 声明判断是否要求阶段暂停。

    判定优先级：
    1. skill_manifest 的 pause.stage_pause（S1：manifest 是平台行为声明的唯一源）；
    2. 旧 pause_rules 显式声明（兼容存量，与 manifest 并存时以 manifest 为准）；
    3. 兜底：存在『何时暂停/强制暂停点』字样即视为要求（兼容存量文档）。
    """
    entry = resolve_entry(skill_name)
    if entry is None:
        return False
    manifest_pause = (entry.manifest or {}).get("pause") or {} if entry.manifest else {}
    if "stage_pause" in manifest_pause:
        return bool(manifest_pause["stage_pause"])
    content = entry.content or ""
    from src.video_agent.web.skill_docs import parse_pause_rules

    rules = parse_pause_rules(content)
    if rules is not None and "stage_pause" in rules:
        return bool(rules["stage_pause"])
    return "何时暂停" in content or "强制暂停点" in content


def skill_planner_flow(skill_name: str, limit: int = 6000) -> str:
    """当前 Skill 的 <planner> 流程章节（主模型流程基线）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return ""
    flow = entry.sections.get("planning") or ""
    if len(flow) > limit:
        flow = flow[:limit] + "\n……（流程章节超长已截断）"
    return flow
