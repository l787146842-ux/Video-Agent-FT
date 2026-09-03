"""回归测试 0818-3333：pipeline 调度回喂可见性 + 语言跟随契约。

事故：调度工具（已退役）返回值全是干货但回喂只给模型「执行成功」五字，
模型看不到批次信息连调 3 次空转（每轮白烧 8~20s 思考）；planner 模板缺
语言跟随契约（回复须跟随用户消息语言）。
"""
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# ---------- C1：pipeline 调度回喂可见性（0818 架构板正批：调度工具退役，
# 回喂 detail 契约保留为执行器通用契约） ----------


class TestPipelineDetailVisibility:
    def test_feedback_carries_pipeline_detail(self):
        """层 8 回喂必须把 pipeline detail 原样带给模型（端到端钉契约）。"""
        from src.video_agent.core.fc_feedback import format_tool_results

        text = format_tool_results([{
            "name": "script_analyze", "ok": True,
            "data": {"detail": "已完成：剧本分析; 未完成：关键元素; 下一可执行批次：关键元素"},
        }])
        assert "下一可执行批次：关键元素" in text


# ---------- C2：语言跟随契约（P3 单一事实源） ----------


class TestLanguageContract:
    def test_language_template_exists_with_rule(self):
        # 语言规则单家已随提示词重组内联进 protocol.md（shared/language.md 退役）
        lang = (ROOT / "prompts" / "planner" / "protocol.md").read_text(encoding="utf-8")
        assert "跟随用户" in lang or "用户最新一条消息的语言" in lang

    def test_planner_protocol_carries_language(self):
        # P2e 单轨收敛 + 提示词重组：协议唯一 = protocol.md；语言规则由
        # 原 shared/language.md 的 {{include}} 展开内联进 protocol.md（单一事实源）。
        text = (ROOT / "prompts" / "planner" / "protocol.md").read_text(encoding="utf-8")
        assert "== 语言规则 ==" in text, "protocol.md 未承载语言规则段（P3 单一事实源）"
        assert "跟随用户最新一条消息的语言" in text
