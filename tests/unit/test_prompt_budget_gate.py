"""B1 回归：提示词预算门禁 + 协议单轨瘦身 + 动作定义唯一源 + 矛盾统一 + F10-1 下沉。

对应审核报告 F5/F6/F7/F8/F9/F10；快照锁语义（Rule 6）。
"""
import asyncio
import json

from src.video_agent.utils.prompts import load_prompt
from src.video_agent.adapters.base_chat import ChatResponse


def test_b1_system_fc_under_budget_and_slimmed():
    """F5：system_fc.md ≤7KB 且不再内联动作清单（text_actions.md 为唯一动作定义源）。
    文本协议 system.md 已退役（P2e 单轨收敛），预算断言收敛到唯一协议。"""
    from pathlib import Path

    f = Path("prompts/planner/system_fc.md")
    text = f.read_text(encoding="utf-8")
    assert f.stat().st_size <= 7168
    for anchor in ("- add_group:", "- write_document:", "- generate_image:", "```studio-actions"):
        assert anchor not in text


def test_b1_prompt_budget_gate_passes():
    """13.6 预算 CI 门禁：模型可见「严禁/不得」≤8（当前应远低于预算）。"""
    import scripts.check_prompt_budget as gate

    assert gate.main() == 0


def test_c6_skill_ban_independent_ledger():
    """C6（任务#22）：data/skills/*.md 直注禁令独立账本，不并入 BUDGET=8；
    基线棘轮只降不升：当前计数不得超基线。"""
    import scripts.check_prompt_budget as gate

    viols = gate.collect_skill_ban_violations()
    assert len(viols) <= gate.SKILL_BAN_BASELINE, "Skill 直注禁令上涨，超出棘轮基线"
    # 与主账本分离：主账本扫描面不含 data/skills
    assert gate.SKILLS_MD_DIR == gate.ROOT / "data" / "skills"
    assert "data/skills" not in "|".join(gate.CODE_DIRS)


def test_c6_skill_ban_ratchet_blocks_increase(monkeypatch):
    """C6：超过基线即 FAIL（棘轮只降不升，观察项 ≠ 免死金牌）。"""
    import scripts.check_prompt_budget as gate

    monkeypatch.setattr(gate, "SKILL_BAN_BASELINE", len(gate.collect_skill_ban_violations()) - 1)
    assert gate.main() == 1


def test_model_visible_prompts_carry_no_internal_ticket_numbers():
    """整改批 2.2：模型可见提示词层（prompts/**/*.md）不含内部编号
    （任务#N / 批次N / ADR-NNNN / 宪法 RuleN / 层 N / Pn-N 等）——
    考古噪声对模型无意义且挤占预算，回潮即红。"""
    import re
    from pathlib import Path

    pattern = re.compile(
        r"任务#\d+|批次\d+|ADR-\d{4}|宪法\s*Rule\s*\d|(?<![A-Za-z])层\s?\d|"
        r"(?<![A-Za-z0-9])P\d+-\d+(?![0-9])")
    offenders = []
    for f in sorted(Path("prompts").rglob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            if m:
                offenders.append(f"{f.as_posix()}:{i}: {m.group(0)}")
    assert not offenders, "内部编号回潮: " + "; ".join(offenders)


def test_b1_system_fc_include_expansion():
    """F7：shared 段经 {{include}} 拼装（分身消除，单一事实源）。"""
    text = load_prompt("planner/system_fc.md")
    assert "渐进式披露" in text          # shared/important_rules.md
    assert "结构化短交代" in text                    # shared/output_discipline.md
    assert "看图再动笔" in text or "故事板媒体调用" in text  # shared/media_rules.md


def test_b1_text_actions_deleted_after_44():
    """4-4 双轨退役（ADR-0001）：text_actions.md 文件已删除，
    生成确认拦截语义唯一承载 = FC 工具层闸机（prompt_gates/gen gate）。"""
    from pathlib import Path

    assert not Path("prompts/planner/text_actions.md").exists()


def test_b1_no_text_action_protocol_injected_after_44():
    """4-4/P2e：协议单轨（system_fc.md）不注入文本动作定义。

    整改批 2.1 修订（裁决注记）：协议段新增「Skill 文档能力词对照」段，
    历史能力词（storyboard_key_elements 等）以「阶段标记 → 真实动作」的
    解释口径出现——这不是动作定义（模型可见的调用面仍唯一 = FC 工具 schema），
    而是把 Skill 章节标签显式降级为非工具名，与 ADR-0001 单轨意图一致。
    本测试改钉三件事：① 协议注入；② 对照段存在（能力词不得无解释裸奔）；
    ③ 4-4 时代的文本动作定义行（`- add_group:` 等）不复活。
    """
    from src.video_agent.core.planner import PlannerContext
    from src.video_agent.core.prompt_builder import PromptBuilder

    class _Docs:
        def list_skill_docs(self):
            return []

    builder = PromptBuilder(
        lambda: _Docs(),
        lambda: "proj-test",
        lambda: {},
    )
    ctx = PlannerContext(history=[], use_studio_context=True)
    text = builder.build_system_prompt(ctx)
    assert "Tool 优先协议" in text                      # system_fc.md 注入
    assert "Skill 文档能力词对照" in text               # 能力词必须带解释出现
    assert "阶段标记" in text
    for line in text.splitlines():
        # 能力词只允许出现在「标签 → 动作」解释行里，不允许成为动作定义行
        if "storyboard_key_elements" in line or "audio_generate" in line:
            assert "：" in line
    for legacy_action in ("- add_group:", "- update_draft:",
                          "- write_document:", "- generate_image:",
                          "- generate_video:"):
        assert legacy_action not in text                # 文本动作定义已删


def test_b1_generate_image_once_per_batch():
    """F10-1 下沉：对话内单图工具每批最多一次（prose 禁令 → 工具层计数器）。"""
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.tools.base import ToolResult

    class _Stub:
        async def invoke_tool(self, name, args):
            return ToolResult(success=True, data={"image_urls": ["http://x/1.png"]})

    runner = FCToolRunner(_Stub())
    calls = [
        {"id": "c1", "type": "function", "function": {
            "name": "generate_image",
            "arguments": json.dumps({"prompt": "一只猫", "adapter_provider": "mock"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "generate_image",
            "arguments": json.dumps({"prompt": "一只狗", "adapter_provider": "mock"})}},
    ]
    applied, confirmation, _u, _i, _l, _o, tool_results, _d, warnings, _overflow = asyncio.run(
        runner.execute(ChatResponse(content="", tool_calls=calls))
    )
    assert applied == 1  # 第二个被拦截
    assert any("每轮只调用一次" in str(t.get("error") or "") for t in tool_results)
