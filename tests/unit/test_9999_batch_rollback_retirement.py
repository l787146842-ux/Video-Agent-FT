# -*- coding: utf-8 -*-
"""事故 9999（2026-09-27）· 批级整态回滚退役 + 平台改写可见性的回归钉。

## 事故现场

`proj-1790513490-8468602e`（项目名 9999），2026-09-27 21:04。子代理在**一个响应**
里发了 6 个调用（1 个 `todo_write` + 5 个 `storyboard_add_draft`）。前 4 张卡
**成功落盘**（日志账本 79/80/81/82），第 5 个因 `group_id` 抄错失败 ⇒
`batch_checkpoint.maybe_rollback_on_failure` 命中保守条件 ⇒ **整份 state 恢复到批首**
⇒ 4 张已成功落盘的卡**全部蒸发**，且只留一条 loguru WARNING，模型/用户皆不可见。

**链条**：假回执 → 假信念 → 假完工。
子代理手里仍攥着 4 条「执行成功」回执（`tool_results` 未被清理），据其推断
「第 2 步实际已完成 4/5」，最终如实汇报「已写入 14 张……**未完成事项：无**」——
它没撒谎，是被平台的静默回滚骗了。用户随后报告「领航员、观测员、研究员、
研究员甲没有提示词」。

**物理证据**：现存草稿 id 按时间戳排序，`1790514241`（21:04:01）后直接跳到
`1790514257`（21:04:17）——21:04:07 那一秒的 4 次写入在库里一个字节都不剩。

## 退役依据（用户 2026-09-27 裁决①A「一个失败不连坐」）

| # | 依据 |
|---|---|
| ① | 该机制自设的前置条件（批内无 high 风险工具 / 无生成族成败 / 无文档写入）已把所有**外部副作用**排除干净，剩下的全是**纯内部状态写入** |
| ② | 单个写类工具的写入本就**原子**——全部 9 个 `async with svc.lock:` 块内 **await 计数为 0**，取消（只能在 await 点插入）打不断任何单个工具的写入 ⇒「半截态」在单工具粒度上不成立 |
| ③ | 它诞生的 2026-08 是**串行时代**（并行池是后置的批 7，且以本机制为前置依赖）；「一串顺序动作没跑完就当没发生」的语义被原样套用到「N 个独立写入」上，爆炸半径随并行池放大而判定条件一字未改 |

现语义对齐 dsh `dsh-tools`：「普通工具失败返回最终结果而**不中止当前轮次**」。

## 本文件钉什么

| # | 钉子 | 防的回潮 |
|---|---|---|
| 1 | 批内单个调用失败**不连坐**：其余调用照常执行并保留写入 | 回滚机制复活 / `break` 中止本批 |
| 2 | 失败**不影响**同批已成功成员的状态 | 「回滚抹掉先前成功写入」复现 |
| 3 | 批级回滚模块**已真删**（不留兼容空壳） | 留 `try: import` 兼容桩变相复活 |
| 4 | `StateManager.snapshot_state/restore_snapshot` **仍存活**（E1 快照 / fork / web restore 三条独立消费链） | 误把这两个方法当回滚专属一并删除 |
| 5 | 旧回滚模块的 `_BatchState` 专属字段已清除 | 字段残留 + 悬空引用 |
| 6 | 取消**不再**恢复整态：已完成成员写入保留 | 取消路径重新接回回滚 |
| 7 | 动作二②：版本闸放弃写入时写类工具**不再回假成功** | 12 处 `svc.save()` 不判返回值回潮 |
"""
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_feedback import compose_failure_feedback
from src.video_agent.core.fc_tool_runner import FCToolRunner, _BatchState
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult, save_or_conflict


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class _FakeTool:
    def __init__(self, name, risk="medium"):
        self.name = name
        self.risk = risk


class _ScriptedToolManager:
    """脚本化工具管理器：与 ToolManager 同形（get_tool/get_tool_risk/invoke_tool）。
    风险分级语义对齐 §2.7：未知归 high。"""

    def __init__(self):
        self._tools = {}
        self._behaviors = {}

    def add(self, tool, behavior):
        self._tools[tool.name] = tool
        self._behaviors[tool.name] = behavior

    def get_tool(self, name):
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found.")
        return self._tools[name]

    def get_tool_risk(self, name):
        tool = self._tools.get(name)
        risk = str(getattr(tool, "risk", "") or "").strip().lower() if tool else ""
        return risk if risk in ("low", "medium", "high") else "high"

    async def invoke_tool(self, name, args):
        return await self._behaviors[name](args)


def _batch(*specs):
    return ChatResponse(content="", tool_calls=[
        {"id": f"c{i}", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}
        for i, (name, args) in enumerate(specs)
    ])


def _add_ke(svc, gid):
    svc.update("keyElements", svc.state_dict.get("keyElements", []) + [
        {"id": gid, "title": f"组-{gid}", "drafts": []}])


# =====================================================================
# ① 不连坐：批内一个失败，其余调用照常执行并保留写入（事故 9999 主钉）
# =====================================================================


class TestNoCascadeOnBatchFailure:
    """9999 实证：6 调用批内前 4 个成功、第 5 个失败 ⇒ 旧机制把 4 个一起抹了。
    本组钉死新语义：失败的归失败，成功的**保留**，本批其余调用**继续执行**。"""

    async def test_failure_does_not_wipe_earlier_successes(self, svc):
        """核心钉子：先成功的写入不得因后续失败而消失（旧：整批回滚全抹）。"""

        async def write_ok(args):
            _add_ke(svc, args["gid"])
            return ToolResult(success=True, data={})

        async def write_fail(args):
            return ToolResult(success=False, error="Group 'ke-xxx' not found")

        tm = _ScriptedToolManager()
        tm.add(_FakeTool("storyboard_add_draft", "medium"), write_ok)
        tm.add(_FakeTool("write_fail_med", "medium"), write_fail)
        runner = FCToolRunner(tool_manager=tm)

        # 复刻 9999 形态：4 个成功 + 1 个失败
        result = await runner.execute(_batch(
            ("storyboard_add_draft", {"gid": "ke-1"}),
            ("storyboard_add_draft", {"gid": "ke-2"}),
            ("storyboard_add_draft", {"gid": "ke-3"}),
            ("storyboard_add_draft", {"gid": "ke-4"}),
            ("write_fail_med", {"gid": "ke-bad"}),
        ))

        ids = [g.get("id") for g in svc.state_dict.get("keyElements", [])]
        for want in ("ke-1", "ke-2", "ke-3", "ke-4"):
            assert want in ids, (
                f"同批先前成功写入 {want} 被抹——批级回滚复活（事故 9999 复发）")
        assert result.applied == 4
        assert result.tool_results[-1]["ok"] is False

    async def test_failure_does_not_abort_rest_of_batch(self, svc):
        """失败**不中止**本批其余调用（旧行为：回滚后 return "break" 跳过剩余）。"""
        invoked = []

        async def write_fail(args):
            invoked.append("failer")
            return ToolResult(success=False, error="执行失败")

        async def write_after(args):
            invoked.append("after")
            _add_ke(svc, "ke-after")
            return ToolResult(success=True, data={})

        tm = _ScriptedToolManager()
        tm.add(_FakeTool("write_fail_med", "medium"), write_fail)
        tm.add(_FakeTool("write_after_med", "medium"), write_after)
        runner = FCToolRunner(tool_manager=tm)

        result = await runner.execute(_batch(
            ("write_fail_med", {}), ("write_after_med", {})))

        assert "after" in invoked, (
            "失败后的同批调用被跳过——回滚-中止纪律复活（应对齐 dsh 不中止轮次）")
        assert any(g.get("id") == "ke-after"
                   for g in svc.state_dict.get("keyElements", [])), (
            "失败后的同批调用虽执行但写入未保留")
        # 两个调用都有回喂条目（失败者 + 成功者）
        assert len(result.tool_results) == 2
        assert result.applied == 1

    async def test_cancel_keeps_already_completed_writes(self, svc):
        """取消不再恢复整态：已完成成员的写入**保留**（旧：取消也回滚）。"""
        from src.video_agent.utils.cancel_token import GenerationCancelled

        async def write_ok(args):
            _add_ke(svc, "ke-done")
            return ToolResult(success=True, data={})

        async def cancel_now(args):
            raise GenerationCancelled("用户停止")

        tm = _ScriptedToolManager()
        tm.add(_FakeTool("state_write_med", "medium"), write_ok)
        tm.add(_FakeTool("long_task", "low"), cancel_now)
        runner = FCToolRunner(tool_manager=tm)

        with pytest.raises(GenerationCancelled):
            await runner.execute(_batch(
                ("state_write_med", {}), ("long_task", {})))

        assert any(g.get("id") == "ke-done"
                   for g in svc.state_dict.get("keyElements", [])), (
            "取消把同批已完成的写入抹掉了——取消路径回滚复活")

    async def test_unexecuted_rejection_does_not_abort_batch(self, svc):
        """未执行型拒收（入参校验拒收）继续不中止、不连坐（既有语义保持）。"""

        async def validation_reject(args):
            return ToolResult(
                success=False, error="Validation Error: 未知字段",
                error_code="validation", retryable=False)

        async def write_ok(args):
            _add_ke(svc, "ke-keep")
            return ToolResult(success=True, data={})

        tm = _ScriptedToolManager()
        tm.add(_FakeTool("patch_stub", "medium"), validation_reject)
        tm.add(_FakeTool("state_write_med", "medium"), write_ok)
        runner = FCToolRunner(tool_manager=tm)

        await runner.execute(_batch(
            ("patch_stub", {}), ("state_write_med", {})))

        assert any(g.get("id") == "ke-keep"
                   for g in svc.state_dict.get("keyElements", []))


# =====================================================================
# ② 退役完整性：模块真删、字段已清、不留兼容空壳
# =====================================================================


class TestRetirementIsReal:
    """退役必须是真删（P1：无消费方即不得留孤立文案/空壳）。"""

    def test_batch_checkpoint_module_is_gone(self):
        """`core.batch_checkpoint` 不可导入——不留 `try/except ImportError` 兼容桩。"""
        import importlib
        with pytest.raises(ImportError):
            importlib.import_module("src.video_agent.core.batch_checkpoint")

    def test_batch_state_has_no_rollback_fields(self):
        """回滚专属字段（batch_cp / batch_tools / parallel_member）已清除。"""
        fields = set(_BatchState.__dataclass_fields__)
        for gone in ("batch_cp", "batch_tools", "parallel_member"):
            assert gone not in fields, (
                f"_BatchState.{gone} 仍在——回滚专属字段残留")

    def test_batch_state_keeps_stage_boundary_field(self):
        """`batch_tool_names`（同名陷阱：**不是**回滚那个函数）必须保留——
        它服务三通道阶段边界逻辑（5555/Q3 阶段标签），与回滚无关。"""
        assert "batch_tool_names" in _BatchState.__dataclass_fields__
        assert "last_stage_label" in _BatchState.__dataclass_fields__

    def test_runner_has_no_rollback_wiring(self):
        """runner 源码零回滚接线（防回滚以任何形式复活）。"""
        import inspect
        from src.video_agent.core import fc_tool_runner
        src = inspect.getsource(fc_tool_runner)
        for gone in ("batch_checkpoint", "maybe_rollback", "take_checkpoint",
                     "should_rollback", "restore_snapshot", "parallel_member"):
            assert gone not in src, (
                f"fc_tool_runner 仍引用 {gone}——退役未净")


# =====================================================================
# ③ 幸存能力：snapshot/restore 两条独立消费链不得被误删
# =====================================================================


class TestSnapshotApiSurvives:
    """`StateManager.snapshot_state/restore_snapshot` **不是**回滚专属：
    E1 消息级快照（`take_snapshot`）、项目分叉（`fork_from_snapshot`）、
    Web 回档（`POST /api/project/restore`）三条独立消费链在用。
    （本组两例原在 test_batch_checkpoint.py，属 StateManager 能力测试，
    随模块退役**迁移保留**、不随之删除。）"""

    def test_state_manager_snapshot_is_deep_copy(self, svc):
        snap = svc.snapshot_state()
        snap.setdefault("keyElements", []).append({"id": "ghost"})
        assert all(g.get("id") != "ghost"
                   for g in svc.state_dict.get("keyElements", []))

    def test_state_manager_restore_writes_back_with_undo_trail(self, svc):
        snap = svc.snapshot_state()
        svc.update("keyElements", [{"id": "g1", "title": "半截组", "drafts": []}])
        assert any(g.get("id") == "g1" for g in svc.state_dict["keyElements"])
        assert svc.restore_snapshot(snap) in (True, False)  # 落盘结果不抛
        assert all(g.get("id") != "g1"
                   for g in svc.state_dict.get("keyElements", []))
        # undo 留痕：恢复本身可被 undo 复核（回到半截态）
        assert svc.can_undo is True
        svc.undo()
        assert any(g.get("id") == "g1" for g in svc.state_dict["keyElements"])

    def test_e1_snapshot_chain_still_uses_snapshot_state(self, svc):
        """E1 消息级快照链（take_snapshot → snapshot_state）仍通。"""
        snap_id = svc.take_snapshot("事故 9999 退役批回归")
        assert snap_id, "take_snapshot 失效——E1 快照链被退役误伤"
        assert svc.get_snapshot(snap_id) is not None

    def test_fork_from_snapshot_still_works(self, svc):
        """项目分叉链（fork_from_snapshot → restore_snapshot）仍通。"""
        _add_ke(svc, "ke-fork-src")
        snap_id = svc.take_snapshot("fork 源")
        pid = svc.fork_from_snapshot(snap_id, "事故9999退役批-分叉")
        assert pid, "fork_from_snapshot 失效——被退役误伤"


# =====================================================================
# ④ 动作二②：版本闸静默丢弃 → 假回执（同一类病：平台改状态而模型不知情）
# =====================================================================


class TestVersionGateNoSilentSuccess:
    """9999 实跑日志中「放弃过期写入」出现 5 次，即至少 5 次「回执说成功、
    其实没落盘」。`StateManager.save()` 返回 bool（`save_ops.py:64-71`），而
    12 处写类工具的 `svc.save()` 都不读返回值 ⇒ 版本闸静默丢弃写入时模型
    仍收到「执行成功」。本组钉死：落盘失败必须回可行动的失败信封。"""

    def test_save_success_returns_none(self):
        class _Ok:
            def save(self):
                return True

        assert save_or_conflict(_Ok()) is None

    def test_save_refused_returns_conflict_envelope(self):
        class _Refused:
            def save(self):
                return False  # 版本闸放弃写入

        r = save_or_conflict(_Refused())
        assert r is not None, "落盘被放弃却回成功——假回执（事故 9999 同源病）"
        assert r.success is False
        assert r.error_code == "conflict"
        assert r.retryable is False
        assert "未落盘" in str(r.error)
        assert "read_state_group" in str(r.error), "须给出可行动路径"

    def test_conflict_hint_requires_reread_and_differs_from_generic(self):
        """conflict 专属指引必须与 generic 不同，且要求先读回最新状态
        （原参重试必被同一版本闸再拒，故不能照 generic 的「调整参数后重试」）。"""
        conflict = compose_failure_feedback("t", "落盘冲突", 1, error_code="conflict")
        generic = compose_failure_feedback("t", "落盘冲突", 1, error_code="other")
        assert conflict.startswith("[conflict]")
        assert "read_state_group" in conflict
        assert "不要用原参直接重试" in conflict
        assert conflict != generic

    async def test_real_write_tool_surfaces_conflict(self, svc):
        """端到端：真实写类工具在落盘被放弃时返回失败（不得回成功）。"""
        from src.video_agent.tools.storyboard_tools import (
            AddDraftInput, StoryboardAddDraftTool,
        )

        _add_ke(svc, "ke-1")
        orig = svc.save
        svc.save = lambda: False  # 强制版本闸放弃写入
        try:
            res = await StoryboardAddDraftTool().aexecute(AddDraftInput(
                group_id="ke-1", group_type="keyElement",
                draft={"label": "设定图·X", "mediaType": "image",
                       "prompt": "a prompt"}))
        finally:
            svc.save = orig
        assert res.success is False, (
            "版本闸放弃写入时 storyboard_add_draft 仍回成功——假回执复发")
        assert res.error_code == "conflict"

    def test_costly_submit_path_keeps_deliberate_exception(self):
        """**唯一例外**（宪法 §2.5 明载）：外部副作用已发生（生成任务已提交并
        计费）时的事后记账，刻意不返失败——返失败会诱发模型重提 ⇒ 重复扣费。
        本钉防后人「顺手统一」。"""
        import inspect
        from src.video_agent.tools import document_tools
        src = inspect.getsource(document_tools)
        assert "_submit_persisted" in src, "生成提交后记账的刻意例外被移除"
        assert "防重复扣费" in src, "例外理由留痕丢失（后人会当缺陷抹平）"
