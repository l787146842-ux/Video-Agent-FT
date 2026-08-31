"""Skill 执行器校验/应用层（主模型产出，本层按 Skill 章节把关）。

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
        user_override=user_override,
        gate_enabled=True,
    )
    if verdict.ok:
        if verdict.message:
            return True, [], [verdict.message]
        return True, [], []
    hard = [verdict.message] if verdict.message else ["提示词结构校验未通过"]
    return False, hard, []


def skill_planner_flow(skill_name: str, limit: int = 6000) -> str:
    """当前 Skill 的 <planner> 流程章节（主模型流程基线）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return ""
    flow = entry.sections.get("planning") or ""
    if len(flow) > limit:
        flow = flow[:limit] + "\n……（流程章节超长已截断）"
    return flow
