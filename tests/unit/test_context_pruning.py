"""上下文剪枝 + 降级事件化测试（计划书 P4）。

覆盖：
- prune_large_text 边界：未超阈/刚超阈/头尾配额覆盖全文/阈值 0 关闭
- emoji 安全：str 码点切片，禁止代理对劈半
- 白名单：只剪 read_*/生成类回喂副本，写类工具不剪
- format_tool_results 集成：长回喂显著降 token（estimate_messages_tokens 量化）
- 事件落账：prune/truncate/degrade/compact 四类事件随 trace 落盘
"""
import json
from dataclasses import replace

import pytest

from src.video_agent.core import context_prune
from src.video_agent.core import tracer as tr_mod
from src.video_agent.core.context_prune import prune_large_text, prune_tool_feedback
from src.video_agent.core.fc_feedback import FEEDBACK_MARKER, format_tool_results
from src.video_agent.core.token_budget import estimate_messages_tokens, truncate_messages
from src.video_agent.core.tracer import AgentTracer

MARKER_KEY = "⟦PRUNE:"


def _long_body(n: int = 12000) -> str:
    """构造接近真实的长样本（Skill 流程式 markdown，中英混排 + emoji）。"""
    block = (
        "## 第{i}步 分镜拆解 🎬\n"
        "- 镜头语言：远景交代环境，特写强调情绪；节奏先缓后急。\n"
        "- Shot {i}: A slow push-in on the protagonist, warm rim light.\n"
        "- 约束：不得改动规格文档声明的渠道与分辨率；提示词须携带风格锚点。\n"
    )
    body = "".join(block.replace("{i}", str(i)) for i in range(1, n // len(block) + 2))
    return body[:n]


# ---------- prune_large_text 纯函数边界 ----------

class TestPruneLargeText:
    def test_below_threshold_unchanged(self):
        text = "短文本" * 100  # 300 字
        assert prune_large_text(text, 6000, 3000, 2000) is text

    def test_just_over_threshold_pruned(self):
        text = "字" * 6001
        out = prune_large_text(text, 6000, 3000, 2000)
        assert MARKER_KEY in out
        assert "中段省略 1001 字" in out
        assert "start=3000" in out
        assert out.startswith("字" * 3000)
        assert out.endswith("字" * 2000)
        assert len(out) < len(text)

    def test_head_tail_cover_full_text_unchanged(self):
        text = "字" * 6500  # 超阈但 head+tail=5000… 6500>5000 会剪；这里构造覆盖场景
        assert prune_large_text(text, 6000, 4000, 3000) is text

    def test_threshold_zero_disabled(self):
        text = "字" * 99999
        assert prune_large_text(text, 0, 3000, 2000) is text

    def test_empty_text(self):
        assert prune_large_text("", 6000, 3000, 2000) == ""

    def test_net_shrink_guard_returns_unchanged(self):
        """净缩短守卫：头尾+标记行近似开销（≈60 字）不短于原文则原样返回，
        防自定义参数下剪后反而更长"""
        text = "字" * 5055  # head+tail=5000，+60 开销 >= 5055 → 不剪
        assert prune_large_text(text, 5000, 3000, 2000) is text
        # 边界相等同样不剪（守卫含等号）
        edge = "字" * 5060
        assert prune_large_text(edge, 5000, 3000, 2000) is edge

    def test_net_shrink_guard_boundary_prunes_when_truly_shorter(self):
        """刚越过守卫边界：剪且结果确比原文短"""
        text = "字" * 5061
        out = prune_large_text(text, 5000, 3000, 2000)
        assert MARKER_KEY in out
        assert len(out) < len(text)

    def test_emoji_codepoint_safety(self):
        """切片点压在 emoji 边界上也不得劈半（str 码点切片，禁 bytes）"""
        emojis = "🎬🌟✨🚀💡" * 2000  # 每个都是单码点
        text = "开头" * 500 + emojis + "结尾" * 500  # 1000 + 10000 + 1000
        head, tail = 1003, 507  # 故意让边界落在 emoji 区内的奇数码点位
        out = prune_large_text(text, 6000, head, tail)
        assert MARKER_KEY in out
        assert out[:head] == text[:head]
        assert out[len(out) - tail:] == text[len(text) - tail:]
        # 无孤立代理对：能无损往返 utf-8 即未劈半
        assert out.encode("utf-8").decode("utf-8") == out
        assert "\ud83c" not in out and "\udfff" not in out


# ---------- 白名单与配置开关 ----------

class TestPruneWhitelist:
    def test_read_tool_pruned(self):
        out = prune_tool_feedback("read_skill", "字" * 12000, 6000, 3000, 2000)
        assert MARKER_KEY in out

    def test_write_tool_not_pruned(self):
        """写类工具不在白名单：再长也不剪（归 digest 杠杆管）"""
        text = "字" * 12000
        assert prune_tool_feedback("storyboard_create_group", text, 6000, 3000, 2000) is text
        assert prune_tool_feedback("script_analyze", text, 6000, 3000, 2000) is text

    def test_settings_default_thresholds(self, monkeypatch):
        """缺省读 settings（6000/3000/2000）"""
        monkeypatch.setattr(context_prune, "settings",
                            replace(context_prune.settings))
        out = prune_tool_feedback("read_project_doc", "字" * 12000)
        assert MARKER_KEY in out

    def test_settings_zero_one_key_rollback(self, monkeypatch):
        """tool_result_prune_chars=0 一键关闭（回滚开关）"""
        monkeypatch.setattr(
            context_prune, "settings",
            replace(context_prune.settings,
                    tool_result_prune_chars=0,
                    tool_result_prune_head=3000, tool_result_prune_tail=2000))
        text = "字" * 12000
        assert prune_tool_feedback("read_skill", text) is text


# ---------- 剪枝标记按工具类分流 ----------

class TestPruneMarkerByToolKind:
    def test_read_tool_marker_keeps_resume_hint(self):
        """read_* 类保留 start= 续读提示（有真实续读路径）"""
        out = prune_tool_feedback("read_draft", "字" * 12000, 6000, 3000, 2000)
        assert "可用 read_* 工具 start=3000 续读" in out

    def test_generation_tool_marker_neutral_no_resume(self):
        """生成类无续读路径：中性告知模板，不再提示续读"""
        out = prune_tool_feedback("image_generate", "字" * 12000, 6000, 3000, 2000)
        assert "按已有头尾信息继续，勿重复生成" in out
        assert "续读" not in out and "start=" not in out

    def test_generation_video_alias_same_template(self):
        """generate_video 同走生成类模板"""
        for name in ("generate_video",):
            out = prune_tool_feedback(name, "字" * 12000, 6000, 3000, 2000)
            assert "勿重复生成" in out and "续读" not in out


# ---------- format_tool_results 集成与 token 收益量化 ----------

class TestFeedbackPruneIntegration:
    def _feedback_tokens(self, content: str) -> int:
        return estimate_messages_tokens([{"role": "user", "content": content}])

    def test_long_read_skill_pruned_in_feedback(self, monkeypatch):
        monkeypatch.setattr(context_prune, "settings", replace(context_prune.settings))
        body = _long_body(15000)
        msg = format_tool_results([
            # B1 后 read_skill 无 section 走指针，剪枝路径用 read_uploaded_doc 验证
            {"name": "read_uploaded_doc", "ok": True,
             "data": {"name": "测试文档", "content": body}},
        ])
        assert isinstance(msg, str) and MARKER_KEY in msg
        # 头尾原文保留（start= 续读兜底的信任基础）；渲染头带「【名称】」前缀，
        # 头部 3000 码点中正文约占 2990，断言取保守区间
        assert FEEDBACK_MARKER in msg
        assert body[:2900] in msg and body[-2000:] in msg

    def test_short_read_skill_untouched(self, monkeypatch):
        monkeypatch.setattr(context_prune, "settings", replace(context_prune.settings))
        body = _long_body(5000)  # 未超 6000 阈值
        msg = format_tool_results([
            # B1 后 read_skill 无 section 走指针，剪枝路径用 read_uploaded_doc 验证
            {"name": "read_uploaded_doc", "ok": True,
             "data": {"name": "测试文档", "content": body}},
        ])
        assert MARKER_KEY not in msg and body in msg

    def test_token_savings_significant(self, monkeypatch):
        """真实长样本：剪枝后进入 history 的 token 量显著下降"""
        body = _long_body(20000)
        tr = {"name": "read_uploaded_doc", "ok": True,
              "data": {"name": "测试文档", "content": body}}
        orig = context_prune.settings
        monkeypatch.setattr(
            context_prune, "settings",
            replace(orig, tool_result_prune_chars=0))
        full = format_tool_results([dict(tr)])
        monkeypatch.setattr(context_prune, "settings", replace(orig))
        pruned = format_tool_results([dict(tr)])
        before = self._feedback_tokens(str(full))
        after = self._feedback_tokens(str(pruned))
        assert after < before
        # 20000 字 → 头 3000 + 尾 2000 + 标记行：收益应 >50%
        assert after <= before * 0.5, f"收益不足: {before} -> {after}"

    def test_original_tool_result_untouched(self, monkeypatch):
        """只剪回喂副本：tool_results 原始 data 不被修改"""
        monkeypatch.setattr(context_prune, "settings", replace(context_prune.settings))
        body = _long_body(15000)
        tr = {"name": "read_uploaded_doc", "ok": True,
              "data": {"name": "测试文档", "content": body}}
        format_tool_results([tr])
        assert tr["data"]["content"] == body


# ---------- 降级事件化落账 ----------

@pytest.fixture
def tracer(tmp_path, monkeypatch):
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    AgentTracer.reset()
    t = AgentTracer.get_instance()
    yield t
    AgentTracer.reset()


def _kinds(rec: dict) -> list:
    return [e.get("kind") for s in rec.get("steps", [])
            for e in (s.get("context_events") or [])]


class TestContextEvents:
    def test_prune_event_lands_in_trace(self, tracer):
        tracer.start_trace("剪枝事件")
        tracer.start_step()
        prune_tool_feedback("read_skill", "字" * 12000, 6000, 3000, 2000)
        tracer.end_step(1, finish_reason="tool_calls")
        rec = tracer.finish_trace()
        assert "prune" in _kinds(rec)

    def test_truncate_and_degrade_events(self, tracer):
        tracer.start_trace("截断事件")
        tracer.start_step()
        big_system = "状" * 8000
        msgs = [{"role": "system", "content": big_system}] + [
            {"role": "user", "content": f"真实消息{i}"} if i % 2 == 0
            else {"role": "assistant", "content": "（系统）回喂" + "x" * 800}
            for i in range(8)
        ]
        out = truncate_messages(
            msgs, max_tokens=200, keep_recent=1,
            system_degrader=lambda c: "降级后的短 system")
        tracer.end_step(1)
        rec = tracer.finish_trace()
        kinds = _kinds(rec)
        assert "truncate" in kinds
        assert "degrade" in kinds  # 删无可删后 system 保险丝触发
        assert len(out) < len(msgs)

    def test_compact_event_pre_trace_adopted(self, tracer):
        """轮前事件（compaction 先于 start_trace）随 start_trace 收养落账"""
        tracer.record_context_event("compact", "会话 compaction：12 条 -> 摘要+4 条")
        tracer.start_trace("收养测试")
        tracer.start_step()
        tracer.end_step(1)
        rec = tracer.finish_trace()
        assert "compact" in _kinds(rec)

    def test_invalid_kind_ignored(self, tracer):
        tracer.start_trace("非法 kind")
        tracer.start_step()
        tracer.record_context_event("explode", "不应落账")
        tracer.end_step(1)
        rec = tracer.finish_trace()
        assert _kinds(rec) == []

    def test_event_persisted_to_jsonl(self, tracer, tmp_path):
        tracer.start_trace("落盘测试")
        tracer.start_step()
        tracer.record_context_event("prune", "read_skill: 12000->5064 字")
        tracer.end_step(1)
        tracer.finish_trace()
        lines = (tmp_path / "agent_traces.jsonl").read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[-1])
        assert "prune" in _kinds(rec)

    def test_no_event_no_key_keeps_record_compact(self, tracer):
        """无事件时 step 不写 context_events 键（历史格式/体积不变）"""
        tracer.start_trace("空事件")
        tracer.start_step()
        tracer.end_step(1)
        rec = tracer.finish_trace()
        assert "context_events" not in rec["steps"][0]
