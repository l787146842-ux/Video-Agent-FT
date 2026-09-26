# -*- coding: utf-8 -*-
"""2026-09-26 11111 项目四问取证批 — 回归钉（事故编号：11111）。

现场：`proj-1790409991-6152543d`（工作台名「11111」），Skill「AI-短剧一站式生成」。
取证报告：`reports/11111-四问取证-20260926/00-取证报告.md`。

本文件钉死四类根因的修复，防止回归：
  R1 音色描述唯一载体（四跑四态的字段漂移）
  R2 键序写闸**已删除**（用户裁决：只留徽标内容说明，不做机械校验）
  R3 阶段建卡限定对主代理可见（父级盲区 → ≥46% 时长白烧）
  R7 音频种类按宿主分组分档（并列枚举与闸机口径打架）
  R9 铁律不得承诺不存在的机器闸（空头承诺）
"""
import pytest
from pathlib import Path

from src.video_agent.core import subagent as subagent_mod
from src.video_agent.tools.document_tools import _stage_hint
from src.video_agent.tools.storyboard_tools import CreateGroupInput, _DRAFT_FIELDS_HINT


# ---------- R3：主代理必须看得见「阶段建卡限定」 ----------


def test_11111_stage_hint_declares_card_limits():
    """R3：`run_subagent.stage` 描述必须包含各阶段的建卡限定。

    11111 现场：父级按 SUBAGENT_POLICY「只补子代理读不到的东西」写下
    「补齐场景/道具 keyElement 草稿」，子代理照办、5 次 add_draft(image)
    全被阶段媒体闸拒收（单步 188.0s / 42,340 字推理）。根因 = 该限定只下发到
    子级 GateContext，父级 prompt 从无此表。本钉防止再度失明。
    """
    hint = _stage_hint()
    assert "新建草稿卡可用媒体类型" in hint
    assert "故事板设计" in hint
    # 必须点出 audio/video 允许集（image 不在内 = 父级不该安排建图卡）
    assert "audio/video" in hint
    assert "voice" in hint


def test_11111_stage_card_contract_single_source():
    """R3：渲染源必须与两张白名单表**同源**（P1 单一事实源，禁第二份名单）。"""
    for stage in ("storyboard_design",):
        contract = subagent_mod.stage_card_contract(stage)
        for media in subagent_mod.STAGE_CARD_MEDIA.get(stage, frozenset()):
            assert media in contract
        for kind in subagent_mod.STAGE_CARD_AUDIO_TYPES.get(stage, frozenset()):
            assert kind in contract


def test_11111_stage_card_contract_empty_for_unrestricted_stage():
    """未登记限定的阶段 → 空串（不产出空话，维持现状）。"""
    assert subagent_mod.stage_card_contract("script_analyze") == ""
    assert subagent_mod.stage_card_contract("") == ""
    assert subagent_mod.stage_card_contract("no_such_stage") == ""


def test_11111_stage_card_contract_never_leaks_image_for_storyboard():
    """R3 反例：故事板设计阶段绝不能在「允许集」里出现 image。

    这正是 11111 被拒的那张卡类型；若将来放宽该表，须同批改本钉并留痕。
    """
    assert "image" not in subagent_mod.stage_card_contract("storyboard_design")


# ---------- R2：键序闸已删除（用户裁决 2026-09-26）；徽标改说明"内容一致" ----------


def test_11111_key_order_gate_removed():
    """R2：键序写闸**已删除**（用户裁决 2026-09-26）。

    裁决原话：「模型只管打字顺序，不管内容关系……直接在徽标里面说明就行了……
    **无论如何都不能做机械校验**。」
    取证支持：闸机只读位置（`keys.index`），而它自述的意图是**内容**
    （「防徽标吹内切、desc 里没有」）；模型先在思考里起草全文、落库只是抄写，
    故位置对 ≠ 内容一致——11111 的 9 镜全部通过键序检查，而"徽标吹牛"从未被验证。
    本钉防止该闸复活。
    """
    src = Path("src/video_agent/tools/storyboard_tools.py").read_text(encoding="utf-8")
    assert "_desc_before_summary" not in src
    assert "model_validator" not in src  # 该模块已不再需要它
    assert "desc 必须先于 summary" not in src


def test_11111_any_group_key_order_accepted():
    """R2：任何字段顺序都必须能建组（闸已删，不再因位置拒收）。"""
    bad_order = CreateGroupInput.model_validate({
        "group_type": "shot", "title": "镜头A",
        "summary": "含3个内切镜头（约18s）", "desc": "完整镜头设计……",
    })
    assert bad_order.desc and bad_order.summary
    good_order = CreateGroupInput.model_validate({
        "group_type": "shot", "title": "镜头A",
        "desc": "完整镜头设计……", "summary": "含3个内切镜头（约18s）",
    })
    assert good_order.desc and good_order.summary


def test_11111_summary_describes_content_relation_not_position():
    """R2：徽标字段描述必须说明**内容关系**（须与 desc 一致），不再谈字段位置。

    这是裁决要求的落点：「直接在徽标里面说明就行了」。
    """
    desc = CreateGroupInput.model_json_schema()["properties"]["summary"]["description"]
    assert "desc" in desc
    assert "一致" in desc
    # 不再谈位置
    assert "键序" not in desc
    assert "之前" not in desc


# ---------- R1 / R7：草稿字段契约 ----------


def test_11111_voice_card_has_single_carrier_field():
    """R1（2026-09-27 4444 裁决 A+C 改判）：音色描述唯一载体 = 卡 desc，必须写在
    模型可见的字段契约里；timbre 回归前端预设选择器专属（模型留空）。

    11111 现场：同一份「音色描述」有 4 个候选字段，全库四项目四跑四态
    （6666→timbre+desc / 9999→desc / 8888→prompt / 11111→三者都落）。
    原 R1 定 timbre，4444 实证自由文本落 timbre 无消费者且打坏预设下拉，
    且契约「含声音特征进组 desc」造成双份事实源 → 改判卡 desc 单载体。
    """
    assert "音色卡的音色描述写 desc" in _DRAFT_FIELDS_HINT
    assert "timbre" in _DRAFT_FIELDS_HINT  # 仍写明模型留空
    assert "声音特征只落音色卡" in _DRAFT_FIELDS_HINT
    assert "含声音特征作为设定的一部分" not in _DRAFT_FIELDS_HINT  # 旧双份口径防回潮


def test_11111_audio_kinds_tiered_by_host_group():
    """R7：音频种类按**宿主分组**分档，消除「先并列后限定」的自相矛盾。

    11111 读到的契约把 bgm/narration 与 voice 并列，而闸机只放行 voice
    （`STAGE_CARD_AUDIO_TYPES`）⇒ 模型照契约执行却被拒。本句把分档写明。
    """
    assert "音色卡（voice）挂角色组" in _DRAFT_FIELDS_HINT
    assert "挂音频组" in _DRAFT_FIELDS_HINT


def test_11111_audio_kinds_contract_matches_gate():
    """R7 同源：契约里点名「挂角色组」的种类，必须正是闸机放行的种类。"""
    allowed = subagent_mod.STAGE_CARD_AUDIO_TYPES["storyboard_design"]
    assert allowed == frozenset({"voice"})
    assert "音色卡（voice）挂角色组" in _DRAFT_FIELDS_HINT


# ---------- R9：文档不得承诺不存在的机器闸 ----------


def test_11111_iron_rules_no_empty_machine_check_promise():
    """R9：铁律第 1 条不得再声称「系统机器验收」。

    11111 现场：覆盖/时长/镜数**没有任何**机械闸（对应探针已随任务#36 B5
    整体退役），落盘 9/17 镜、106s vs 目标 180s、场三整场 0 覆盖，全程零告警；
    而文档承诺「系统机器验收」⇒ 空头承诺。
    """
    from src.video_agent.core import spec_rules

    body = spec_rules._IRON_RULES_DOC_BODY
    assert "系统机器验收" not in body
    assert spec_rules._CLAUSE_1_CHECK in body
    assert "平台无对应机械闸" in spec_rules._CLAUSE_1_CHECK


def test_11111_iron_rules_legacy_wording_migrates():
    """R9 存量迁移：两张旧口径都收敛到现行自查口径，用户其余编辑不动。"""
    from src.video_agent.core import spec_rules

    for legacy in ("（自检核对）", "（系统机器验收）"):
        old = f"# 执行铁律（系统约定）\n\n1. 拆解覆盖完整{legacy}。\n"
        raw = {"documents": [{
            "id": "d1", "name": spec_rules.IRON_RULES_DOC_NAME, "content": old}]}
        assert spec_rules.ensure_iron_rules_doc(raw) is True
        content = raw["documents"][0]["content"]
        assert spec_rules._CLAUSE_1_CHECK in content
        assert legacy not in content


# ---------- Q2：降级样板话不得是可模仿的第一人称完整句 ----------


def _downgrade(messages):
    from src.video_agent.adapters.openai_compat import _downgrade_tool_role_messages
    return _downgrade_tool_role_messages(messages)


def _asst_with_calls(*names):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": "{}"}}
        for i, n in enumerate(names)]}


def test_11111_downgrade_placeholder_is_not_imitable_sentence():
    """Q2（harness 修复）：assistant 侧降级占位必须是**机械标记**，不是完整句。

    11111 取证：原占位「（本轮为工具调用轮：{names}，结果见紧随其后的系统消息）」
    是一句第一人称式完整陈述；降级**粘性**（后续请求一律沿用旧通道）⇒ 模型每轮
    看到的自己的历史全是这句，开始照抄——5 处纯文本轮逐字复现，其中 seq=57
    那轮**实际带了 5 个工具调用**、正文仍是样板话（已成说话习惯），模型推理
    两次自认 `I again failed to emit tool calls.`，子代理#2 八步里丢 3 步。
    本钉防止该可模仿文案复活。
    """
    out = _downgrade([_asst_with_calls("storyboard_create_group", "todo_write")])
    content = out[0]["content"]
    # 旧文案不得回潮
    assert "本轮为工具调用轮" not in content
    assert "见紧随其后的系统消息" not in content
    # 是机械标记式（对齐 ⟦PRUNE: …⟧ 口径），非完整句
    assert content.startswith("\u27e6") and content.endswith("\u27e7")
    assert "。" not in content
    # 工具名保留（排障与追溯）
    assert "storyboard_create_group" in content


def test_11111_downgrade_keeps_real_content_and_preserves_history():
    """Q2 不变量：只换**占位**文案，不吞真实正文、不改调用方历史本体。"""
    # ① assistant 已有真实正文 → 原样保留，不被占位覆盖
    real = {"role": "assistant", "content": "我已建完 4 组",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "x", "arguments": "{}"}}]}
    out = _downgrade([real])
    assert out[0]["content"] == "我已建完 4 组"

    # ② tool 结果内容保留（转 user 伪装）
    out2 = _downgrade([{"role": "tool", "tool_call_id": "c1", "content": "正文内容"}])
    assert out2[0]["role"] == "user"
    assert "正文内容" in out2[0]["content"]

    # ③ 浅拷贝：不改调用方历史本体
    hist = [_asst_with_calls("x")]
    _downgrade(hist)
    assert "tool_calls" in hist[0]


def test_11111_downgrade_prefix_mismatches_feedback_marker():
    """Q2 附带发现（**已登记待裁决**）：降级前缀 ≠ `FEEDBACK_MARKER`。

    实测：适配器写「（系统）本轮工具执行结果：」，而
    `fc_feedback.FEEDBACK_MARKER` = 「（系统）本轮调用的工具已执行完毕，
    结果如下：」⇒ `_is_feedback_msg` 对降级后的消息返回 **False**。
    后果（降级粘性 ⇒ 全程生效）：`digest_projected_tool_lines`（工具行摘要
    压缩）与 `_skill_section_seen`（read_skill 去重）在降级通道下双双失效。
    本钉**锁定当前事实**，防「注释声称兼容、实际不兼容」的静默漂移；
    若将来接线（统一前缀），本钉须同批更新并留痕。
    """
    from src.video_agent.core.fc_feedback import (
        FEEDBACK_MARKER, _is_feedback_msg,
    )

    out = _downgrade([{"role": "tool", "tool_call_id": "c1", "content": "x"}])
    msg = out[0]
    assert not msg["content"].startswith(FEEDBACK_MARKER), \
        "若前缀已统一，请更新本钉并在 CHANGELOG 留痕"
    assert _is_feedback_msg(msg) is False, \
        "若 _is_feedback_msg 已能识别降级消息，请更新本钉并留痕"
