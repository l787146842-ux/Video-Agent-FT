# -*- coding: utf-8 -*-
"""Versioned workflow declaration and immutable node contracts."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class WorkflowDefinitionError(ValueError):
    pass


_NODE_FIELDS = ("node_id", "executor", "deterministic", "prerequisites",
                "done_predicate", "artifact_schema", "decision_schema",
                "approval_policy", "retry_policy", "next_transition")


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    executor: str
    deterministic: bool
    prerequisites: Tuple[str, ...] = ()
    done_predicate: Any = None
    artifact_schema: Dict[str, Any] = field(default_factory=dict)
    decision_schema: Dict[str, Any] = field(default_factory=dict)
    approval_policy: Dict[str, Any] = field(default_factory=dict)
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    next_transition: Any = None

    @classmethod
    def from_value(cls, raw: Mapping[str, Any]) -> "WorkflowNode":
        if not isinstance(raw, Mapping):
            raise WorkflowDefinitionError("workflow node must be an object")
        missing = [k for k in _NODE_FIELDS if k not in raw]
        if missing:
            raise WorkflowDefinitionError("workflow node missing fields: " + ",".join(missing))
        node_id = str(raw.get("node_id") or "").strip()
        executor = str(raw.get("executor") or "").strip()
        if not node_id or not executor or not isinstance(raw.get("deterministic"), bool):
            raise WorkflowDefinitionError("node_id/executor/deterministic are invalid")
        prereq = raw.get("prerequisites")
        if not isinstance(prereq, (list, tuple)) or any(not str(x).strip() for x in prereq):
            raise WorkflowDefinitionError(f"{node_id}.prerequisites must be a list")
        vals = {}
        for key in ("artifact_schema", "decision_schema", "approval_policy", "retry_policy"):
            if not isinstance(raw.get(key), Mapping):
                raise WorkflowDefinitionError(f"{node_id}.{key} must be an object")
            vals[key] = copy.deepcopy(dict(raw[key]))
        return cls(node_id, executor, raw["deterministic"], tuple(str(x) for x in prereq),
                   copy.deepcopy(raw["done_predicate"]), vals["artifact_schema"],
                   vals["decision_schema"], vals["approval_policy"],
                   vals["retry_policy"], copy.deepcopy(raw["next_transition"]))

    def to_dict(self) -> Dict[str, Any]:
        return {"node_id": self.node_id, "executor": self.executor,
                "deterministic": self.deterministic, "prerequisites": list(self.prerequisites),
                "done_predicate": copy.deepcopy(self.done_predicate),
                "artifact_schema": copy.deepcopy(self.artifact_schema),
                "decision_schema": copy.deepcopy(self.decision_schema),
                "approval_policy": copy.deepcopy(self.approval_policy),
                "retry_policy": copy.deepcopy(self.retry_policy),
                "next_transition": copy.deepcopy(self.next_transition)}


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    revision: str
    nodes: Tuple[WorkflowNode, ...]
    content_hash: str
    skill_id: str = ""

    @classmethod
    def from_sidecar(
        cls,
        sidecar: Mapping[str, Any],
        *,
        workflow_id: str = "",
        skill_id: str = "",
    ) -> "WorkflowDefinition":
        workflow = sidecar.get("workflow") if isinstance(sidecar, Mapping) else None
        if not isinstance(workflow, Mapping):
            raise WorkflowDefinitionError("sidecar.workflow is required")
        raw_nodes = workflow.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise WorkflowDefinitionError("sidecar.workflow.nodes must be a non-empty list")
        nodes = tuple(WorkflowNode.from_value(x) for x in raw_nodes)
        ids = [n.node_id for n in nodes]
        if len(ids) != len(set(ids)):
            raise WorkflowDefinitionError("workflow node_id must be unique")
        known = set(ids)
        graph = {n.node_id: set(n.prerequisites) for n in nodes}
        if any(dep not in known for deps in graph.values() for dep in deps):
            raise WorkflowDefinitionError("workflow prerequisite is unknown")
        visiting, visited = set(), set()

        def visit(item: str) -> None:
            if item in visiting:
                raise WorkflowDefinitionError("workflow prerequisite cycle")
            if item in visited:
                return
            visiting.add(item)
            for dep in graph[item]:
                visit(dep)
            visiting.remove(item)
            visited.add(item)

        for item in ids:
            visit(item)
        payload = {"workflow_id": str(workflow_id or workflow.get("workflow_id") or skill_id),
                   "revision": str(workflow.get("revision") or "1"),
                   "nodes": [n.to_dict() for n in nodes]}
        return cls(payload["workflow_id"] or "workflow", payload["revision"],
                   nodes, _hash(payload), str(skill_id or ""))


# 默认 workflow 自带节点标题（硬编码标题表归注册数据；
# frontmatter flow.stages 声明式 workflow 的标题则随声明自带）。
DEFAULT_V2_NODE_TITLES: Dict[str, str] = {
    "analyze_script": "剧本分析", "collect_spec": "规格候选收集",
    "write_spec": "规格文档", "review_spec": "规格审核",
    "storyboard_key_elements": "关键元素拆解",
    "review_key_elements": "关键元素审核",
    "storyboard_shots": "分镜设计", "storyboard_audio": "音频层设计",
    "review_storyboard": "故事板审核",
    "ke_media": "关键元素设定图", "shot_media": "逐镜视频生成",
    "review_shot_media": "镜头视频审核", "audio_assets": "音频资产",
    "review_audio": "音频审核", "assembly": "剪辑组装",
    "review_assembly": "成片审核",
}

# 审批节点（2026-09-06 对齐批：机械闸里程碑，6 个）。
# 单一事实源——default_v2_workflow 的 approval_policy 声明与本表同源维护；
# 消费端 = workflow_runtime._REVIEW_NODE_PREREQ（完成判定）与
# planner 轮末阶段闸（key_steps_confirm 档拦停目标）。
DEFAULT_V2_REVIEW_NODES: Tuple[str, ...] = (
    "review_spec", "review_key_elements", "review_storyboard",
    "review_shot_media", "review_audio", "review_assembly",
)


def default_v2_workflow(skill_id: str = "") -> WorkflowDefinition:
    def node(
        node_id: str,
        executor: str,
        deterministic: bool,
        prerequisites: Sequence[str] = (),
        approval: bool = False,
    ) -> Dict[str, Any]:
        return {"node_id": node_id, "executor": executor, "deterministic": deterministic,
                "prerequisites": list(prerequisites), "done_predicate": {"type": "state", "node": node_id},
                "artifact_schema": {}, "decision_schema": {"type": "approval"} if approval else {},
                "approval_policy": {"required": approval} if approval else {},
                "retry_policy": {"max_attempts": 1},
                "next_transition": {}}

    # 全流程 16 节点（2026-09-06 对齐批）：设计三节点后补故事板审核，
    # 媒体四阶段（ke_media/shot_media/audio_assets/assembly）入默认定义，
    # 逐阶段后挂审批节点（规格/关键元素/故事板/镜头视频/音频/成片）。
    # 关键元素审核保持「生图前确认」位（3/4 合并口径：确认后再生图）。
    nodes = [node("analyze_script", "script_analyze", False),
             node("collect_spec", "collect_spec", True, ("analyze_script",)),
             node("write_spec", "document_write", True, ("collect_spec",)),
             node("review_spec", "workflow_pause", True, ("write_spec",), True),
             node("storyboard_key_elements", "storyboard_key_elements", False, ("review_spec",)),
             node("review_key_elements", "workflow_pause", True, ("storyboard_key_elements",), True),
             node("storyboard_shots", "storyboard_shots", False, ("review_key_elements",)),
             node("storyboard_audio", "storyboard_audio", False, ("storyboard_shots",)),
             node("review_storyboard", "workflow_pause", True, ("storyboard_audio",), True),
             node("ke_media", "image_generate", False, ("review_storyboard",)),
             node("shot_media", "generate_video", False, ("ke_media",)),
             node("review_shot_media", "workflow_pause", True, ("shot_media",), True),
             node("audio_assets", "audio_generate", False, ("review_shot_media",)),
             node("review_audio", "workflow_pause", True, ("audio_assets",), True),
             node("assembly", "video_assembler", False, ("review_audio",)),
             node("review_assembly", "workflow_pause", True, ("assembly",), True)]
    return WorkflowDefinition.from_sidecar(
        {"workflow": {"workflow_id": "video_storyboard_v2", "revision": "2", "nodes": nodes}},
        workflow_id="video_storyboard_v2", skill_id=skill_id)


__all__ = ["WorkflowDefinition", "WorkflowDefinitionError", "WorkflowNode",
           "default_v2_workflow", "DEFAULT_V2_NODE_TITLES"]
