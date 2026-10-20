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
    """音色描述唯一载体 = 卡 prompt（提示词框），必须写在模型可见的字段契约里；
    timbre 归前端预设下拉（模型留空）；声音特征不进组 desc（消双份事实源）。

    11111 现场：同一份「音色描述」有 4 个候选字段，全库四项目四跑四态
    （6666→timbre+desc / 9999→desc / 8888→prompt / 11111→三者都落）。
    2026-09-27 用户裁决：音色卡整张卡的内容即这段音色描述，落在提示词框（prompt）；
    是否附台词样本顺其自然、平台不加否定约束；此前 A+C 的「写 desc」定法作废。
    """
    assert "音色卡的音色描述写 prompt" in _DRAFT_FIELDS_HINT
    assert "timbre" in _DRAFT_FIELDS_HINT  # 仍写明模型留空
    assert "声音特征只落音色卡" in _DRAFT_FIELDS_HINT


def test_11111_audio_kinds_tiered_by_host_group():
    """R7：音频种类按**宿主分组**分档，消除「先并列后限定」的自相矛盾。

    11111 读到的契约把 bgm/narration 与 voice 并列，而闸机只放行 voice
    （`STAGE_CARD_AUDIO_TYPES`）⇒ 模型照契约执行却被拒。本句把分档写明。

    ⚠ 2026-09-30：原断言手抄字面量 `"音色卡（voice）挂角色组"`，2026-09-27 去重批
    改写措辞（只留长版后半句、丢掉「音色卡（voice）」主语）后即失配——**契约真被
    改坏了，测试反而是对的**。现按语义断言：主语标签 + 宿主分组 + 音频组三者齐备。
    """
    # 主语标签必须还在：读不出「这句在说哪种卡」等于契约失效
    assert "音色卡（voice）" in _DRAFT_FIELDS_HINT, "归位契约丢了主语标签（2026-09-27 回归）"
    # 分档两侧必须都在：voice→角色组、其余→音频组
    assert "角色自己的 keyElement 组内" in _DRAFT_FIELDS_HINT
    assert "挂音频组" in _DRAFT_FIELDS_HINT


def test_11111_audio_kinds_contract_matches_gate():
    """R7 同源：契约里点名「挂角色组」的种类，必须正是闸机放行的种类。"""
    allowed = subagent_mod.STAGE_CARD_AUDIO_TYPES["storyboard_design"]
    assert allowed == frozenset({"voice"})


def test_1019_voice_reference_written_inline_beside_dialogue():
    """2026-10-19 音色就地下（用户裁决「音色写在台词旁边，不要汇总成一行」）。

    病灶（9999 实测 7/11 张视频卡）：模型把音色写成卡尾一句汇总——
    「【音色】对白分别采用 @音色·AA、@音色·程心、@音色·曹彬 的音色参考。」
    汇总句建立不了「哪句台词用哪个音色」的对应关系，用户原话「发给视频模型
    也不知道是哪个音色」。Flova 实产是就地写（台词旁紧跟音色记号）。

    本钉锁死模型可见契约里必须**同时**有：
    ① 正面形态：音色紧跟在那句台词旁边；
    ② 禁止形态：不得写成卡尾「对白分别采用…」汇总句。
    只断言语义片段（不抄整句），措辞微调不误伤，但契约真被删掉就必红。
    """
    assert "音色就地写在那句台词旁边" in _DRAFT_FIELDS_HINT, "就地音色契约丢了"
    assert "@音色·该角色名" in _DRAFT_FIELDS_HINT, "就地写法必须给出具体记号形态"
    assert "对白分别采用" in _DRAFT_FIELDS_HINT, "必须点名被禁止的汇总句式"
    # 既有「拆开写」契约不得被本批改坏（角色图 vs 音色两轴仍分离）
    assert "角色图写 @角色名" in _DRAFT_FIELDS_HINT
    assert "音色卡（voice）" in _DRAFT_FIELDS_HINT


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


# ---------- Q2：降级占位不得是可模仿的第一人称完整句 ----------
#
# 2026-10-08 批（事故 9999 根因修复，用户裁决「按 dsh 方案做」）更新：
# 原 `_downgrade_tool_role_messages`（粘性历史改写）已整体退役——它是
# 9999「工具调用凭空蒸发」的放大器。现由两个替代物承重：
#   · `normalize_tool_pairing`（发出前配对归一，任何请求都走，不改历史）
#   · `_demote_tool_role_for_request`（真·不支持 role 时**逐次**降级，不记忆）
# 本组钉子改钉这两个替代物，原「机械标记式、不可模仿」的约束原样保留。


def _normalize(messages):
    from src.video_agent.adapters.openai_compat import normalize_tool_pairing
    return normalize_tool_pairing(messages)


def _demote(messages):
    from src.video_agent.adapters.openai_compat import _demote_tool_role_for_request
    return _demote_tool_role_for_request(messages)


def _asst_with_calls(*names):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": "{}"}}
        for i, n in enumerate(names)]}


def test_11111_demote_placeholder_is_not_imitable_sentence():
    """Q2（harness 修复）：降级占位必须是**机械标记**，不是可模仿的完整句。

    11111 取证：原占位「（本轮为工具调用轮：{names}，结果见紧随其后的系统消息）」
    是一句第一人称式完整陈述；而旧降级**粘性**（后续请求一律沿用旧通道）⇒ 模型
    每轮看到的自己的历史全是这句，开始照抄——5 处纯文本轮逐字复现，其中 seq=57
    那轮**实际带了 5 个工具调用**、正文仍是样板话（已成说话习惯），模型推理
    两次自认 `I again failed to emit tool calls.`，子代理#2 八步里丢 3 步。
    本钉防止该可模仿文案复活（现由 `_demote_tool_role_for_request` 承接）。
    """
    out = _demote([_asst_with_calls("storyboard_create_group", "todo_write")])
    content = out[0]["content"]
    # 旧文案不得回潮
    assert "本轮为工具调用轮" not in content
    assert "见紧随其后的系统消息" not in content
    # 是机械标记式（对齐 ⟦PRUNE: …⟧ 口径），非完整句
    assert content.startswith("\u27e6") and content.endswith("\u27e7")
    assert "。" not in content
    # 工具名保留（排障与追溯）
    assert "storyboard_create_group" in content


def test_11111_demote_keeps_real_content_and_preserves_history():
    """Q2 不变量：只换**占位**文案，不吞真实正文、不改调用方历史本体。"""
    # ① assistant 已有真实正文 → 原样保留，不被占位覆盖
    real = {"role": "assistant", "content": "我已建完 4 组",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "x", "arguments": "{}"}}]}
    out = _demote([real])
    assert out[0]["content"] == "我已建完 4 组"

    # ② tool 结果内容保留（转 user 伪装）
    out2 = _demote([{"role": "tool", "tool_call_id": "c1", "content": "正文内容"}])
    assert out2[0]["role"] == "user"
    assert "正文内容" in out2[0]["content"]

    # ③ 浅拷贝：不改调用方历史本体
    hist = [_asst_with_calls("x")]
    _demote(hist)
    assert "tool_calls" in hist[0]


# ---------- 2026-10-08 批：配对归一（9999 根因） ----------


def test_9999_pairing_classifier_never_confuses_pairing_with_capability():
    """事故 9999 根因钉：**配对错误**不得被判成「端点不支持 tool role」。

    病灶：旧判定 `"tool" in body` 子串匹配 —— 而供应商的配对错误文案
    「Messages with role 'tool' must be a response to a preceding message
    with 'tool_calls'」里同时含 `role 'tool'` 与 `'tool_calls'` ⇒ 恒为真 ⇒
    误判 ⇒ 触发粘性历史改写 ⇒ 模型照抄占位符 ⇒ 工具调用蒸发。
    """
    from src.video_agent.adapters.openai_compat import classify_tool_role_400

    pairing = ('{"code":"LITELLM_ERROR","message":"Messages with role \'tool\' '
               'must be a response to a preceding message with \'tool_calls\' '
               'Request id: 021791376618724160995723eabea0b8c1f9"}')
    assert classify_tool_role_400(pairing) == "pairing", \
        "配对错误必须判为 pairing（可自愈），不得判成能力缺失"

    # 真·能力缺失仍要认出（本次修复不误伤该保护）
    assert classify_tool_role_400(
        '{"error":{"message":"role tool is not supported"}}') == "unsupported"
    assert classify_tool_role_400(
        '{"error":{"message":"unknown role: tool"}}') == "unsupported"

    # 无关 400 不得被吞进任一分支
    assert classify_tool_role_400(
        '{"error":{"message":"invalid temperature"}}') == "other"


def test_9999_normalize_fixes_orphan_tool_result_without_losing_content():
    """配对归一：孤立 tool 结果 → 转 user，**内容一字不丢**。

    现场形态（存量导入轮 / 压缩后断链）：历史里出现没有前置
    assistant(tool_calls) 声明的 tool 消息 ⇒ 供应商整次请求 400。
    修法 = 在**发送副本**上合法化，不改写持久历史（dsh「请求投影」同款）。
    """
    orphan = [
        {"role": "user", "content": "问"},
        {"role": "tool", "tool_call_id": "", "content": "存量导入的结果正文"},
    ]
    out = _normalize(orphan)
    assert out[1]["role"] == "user", "孤立 tool 消息必须转 user"
    assert "存量导入的结果正文" in out[1]["content"], "内容不得丢失"
    assert "tool_call_id" not in out[1], "转 user 后不得残留 tool_call_id"


def test_9999_normalize_fills_unanswered_call_and_is_idempotent():
    """两个方向都要修；且对已合法的序列**零改动**（幂等）。"""
    missing_result = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "user", "content": "（用户打断）"},
    ]
    out = _normalize(missing_result)
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
               for m in out), "assistant 声明但无结果的调用必须补占位"

    legal = [
        {"role": "assistant", "content": "做完了", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "结果"},
    ]
    out2 = _normalize(legal)
    assert out2 == legal, "已合法的序列必须原样返回（幂等）"
    assert out2 is legal, "零改动时返回同一列表对象（零拷贝）"


def test_9999_prepare_endpoint_never_rewrites_history_sticky():
    """根因防线：请求侧准备**不含**粘性历史改写。

    旧 `_prepare_endpoint_messages` 会在 `MSG_TOOL_ROLE_KEY in unsupported`
    时把整段历史改写（assistant.tool_calls → 文本占位）。该路径必须消失：
    配对问题归 `normalize_tool_pairing`（每次请求都做，不改历史），
    真能力缺失归 400 分支的**逐次**降级（不写 `_unsupported_fields`）。
    """
    import inspect

    from src.video_agent.adapters import openai_compat as oc

    src = inspect.getsource(oc._prepare_endpoint_messages)
    assert "normalize_tool_pairing" in src, "发出前必须做配对归一"
    assert "MSG_TOOL_ROLE_KEY" not in src, \
        "粘性 tool role 降级必须从请求侧移除（9999 根因）"
    assert not hasattr(oc, "MSG_TOOL_ROLE_KEY"), \
        "粘性记忆键必须整体退役，不得留兼容空壳"
    assert not hasattr(oc, "_downgrade_tool_role_messages"), \
        "粘性历史改写函数必须整体退役，不得留兼容空壳"


def test_11111_demote_prefix_mismatches_feedback_marker():
    """Q2 附带发现：降级前缀 ≠ `FEEDBACK_MARKER`（**影响面已收窄**）。

    实测：适配器写「（系统）本轮工具执行结果：」，而
    `fc_feedback.FEEDBACK_MARKER` = 「（系统）本轮调用的工具已执行完毕，
    结果如下：」⇒ `_is_feedback_msg` 对降级后的消息返回 **False**，
    故 `digest_projected_tool_lines`（工具行摘要压缩）与 `_skill_section_seen`
    （read_skill 去重）在降级消息上不生效。

    2026-10-08 批口径变更：降级已从**粘性**改为**逐次**（不写
    `_unsupported_fields`）⇒ 该前缀不匹配只在**那一次重试请求**上存在，
    不再像旧版那样「一经启用、本实例全程生效」。本钉**锁定当前事实**，
    防「注释声称兼容、实际不兼容」的静默漂移；若将来统一前缀，须同批
    更新本钉并留痕。
    """
    from src.video_agent.core.fc_feedback import (
        FEEDBACK_MARKER, _is_feedback_msg,
    )

    out = _demote([{"role": "tool", "tool_call_id": "c1", "content": "x"}])
    msg = out[0]
    assert not msg["content"].startswith(FEEDBACK_MARKER), \
        "若前缀已统一，请更新本钉并在 CHANGELOG 留痕"
    assert _is_feedback_msg(msg) is False, \
        "若 _is_feedback_msg 已能识别降级消息，请更新本钉并留痕"


# ---------- 2026-10-06 时间段落批（事故编号：9999） ----------


def test_9999_time_range_contract_on_both_write_paths():
    """镜内分段的时间写法契约必须同时落在**两条写口**上（G4 同类路径全覆盖）。

    病灶（9999 现场）：Skill `:130` 只写裸词「时长标注」，**未定义形态** ⇒
    模型自由发挥成「约4s」单值近似；对照 Flova 实产写的是累计时间轴
    `0-6s / 6-14s / 14-22s`（首尾相接、覆盖整镜）。
    本契约只补**形态**（平台侧），不动 Skill。

    G4：`storyboard_create_group`（建组）与 `storyboard_patch_group`（改分组）
    是同一件事的两条写口，漏一处则该路径仍写「约4s」。
    """
    from src.video_agent.tools.storyboard_tools import (
        PatchGroupInput, _GROUP_FIELDS_HINT,
    )
    key = "若本镜标注时间"
    assert key in _GROUP_FIELDS_HINT, (
        "改分组写口缺时间范围契约——patch_group 路径仍会写「约4s」")
    assert key in str(CreateGroupInput.model_fields["desc"].description or ""), (
        "建组写口（CreateGroupInput.desc）缺时间范围契约")
    # patch 写口经 hint 拼装，须真能到达模型可见面
    assert key in str(PatchGroupInput.model_fields["patch"].description or ""), (
        "PatchGroupInput.patch 的描述未带上契约（hint 未接上）")


def test_9999_time_range_contract_is_conditional_not_mandatory():
    """契约是**条件式**（「若本镜标注时间」），表达"要标就按这个格式标"。

    用户裁决措辞原话：「若本镜标注时间，按「0-6s」这类时间范围写
    （各段首尾相接、合计等于 duration）」——不强制必须标时间，
    只约束**标注时的形态**。
    """
    from src.video_agent.tools.storyboard_tools import _GROUP_FIELDS_HINT
    assert "若本镜标注时间" in _GROUP_FIELDS_HINT
    assert "0-6s" in _GROUP_FIELDS_HINT, "缺格式示例"
    assert "首尾相接" in _GROUP_FIELDS_HINT, "缺连续性判据"
    assert "合计等于 duration" in _GROUP_FIELDS_HINT, "缺与 duration 的关系"


def test_9999_time_range_contract_not_restating_skill():
    """P1：本契约**不是复述 Skill**——Skill 全文无此形态表述。

    若将来 Skill 自行补上同款逐字模板，本句应改为指针或删除（届时更新本钉）。
    """
    from pathlib import Path as _P
    sk = _P("data/skills/AI-短剧一站式生成/SKILL.md").read_text(encoding="utf-8")
    for kw in ("0-6s", "首尾相接", "时间范围"):
        assert kw not in sk, (
            f"Skill 已含 {kw!r}——本平台句已成复述（P1 违规），"
            "应改为指针或删除并留痕")
