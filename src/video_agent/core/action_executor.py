"""Studio 状态视图载体（Q2 裁决 2026-09-01 删干净后的存留形态）。

文本轨动作分派家族（execute/_apply 分派 + action_drafts/action_gen/
action_media 三域实现体 + flow_directive 一条龙）已整体退役删除：
动作通道唯一 = FC 工具，状态变更经 FC 工具直连 state/storyboard_ops
（宪法 Rule2/Rule3）。本类仅保留编排层消费的状态视图与动作描述：
- agent_loop / round_end_policies：state 视图、_describe_action。
（原 action_log/documents_written/chat_inserts/gate_rejections/skill_name
五个恒空字段已随 2026-09-03 兼容层根除批删除：生产路径零写入，
FC 轨各 collector 才是实际来源。）
退役符号防复活见 scripts/check_legacy_orchestration（FORBIDDEN_B2）。
"""
from typing import Any, Dict, Optional

from src.video_agent.core.action_descriptions import describe_action
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager


class StateOperationExecutor:
    """状态视图载体（无动作分派：动作通道唯一 = FC 工具）。"""

    def __init__(
        self,
        state_service: Optional[StateManager] = None,
        selected_draft_id: str = "",
        selected_type: str = "",
        gate_enabled: bool = False,
    ):
        self.svc = state_service or StateManager.get_instance()
        # 前端当前选中的草稿——"current" 的唯一正确解释
        self.selected_draft_id = selected_draft_id
        self.selected_type = selected_type
        # 提示词结构闸机开关（Skill 流程激活时由 Planner 打开，日常微调不拦截）
        self.gate_enabled = gate_enabled
        # 决策 D：用户坚持（user_override）时硬伤降为警告照常放行
        self.gate_override: bool = False

    @property
    def state(self) -> Dict[str, Any]:
        return self.svc.state_dict

    def _describe_action(self, action: Dict[str, Any]) -> str:
        """生成操作的中文简述（委托 core.action_descriptions）"""
        return describe_action(action, find_draft=self._find_draft)

    def _find_draft(self, draft_id: str, draft_type: str = ""):
        """在 state 中查找 draft（真实 ID / "current" / 卡片编号）；委托领域层唯一实现"""
        return ops.find_draft(
            self.state, draft_id, draft_type,
            selected_draft_id=self.selected_draft_id, selected_type=self.selected_type,
        )
