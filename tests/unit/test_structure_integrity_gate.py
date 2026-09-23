# -*- coding: utf-8 -*-
"""任务#36 护栏移植：建组结构完整性闸（structure_integrity_gate）。

原 exec_common._apply_actions 机械校验随执行器退役为通用工具级校验，
本文件逐条钉死同语义：
① 无标题 add_group 拒收；
② 分镜引用完整度（非空且覆盖标题提及的关键元素，否则拒收）。
（③ 分组类型边界已随 2026-09-10 阶段规则去代码化批退役：阶段类别边界闸
删除后按 group_type 声明推导，不再按「当前阶段」推导——对应用例同批删除。）

## 2026-09-23 批12（事故 4444/B-1 + B-2 + B-3）：本文件原先把两个真缺陷藏住了

**B-3（本文件自身的缺陷）**：原桩数据的 KE 标题是 `程心`（**不带前缀**），
而生产落库是 `Element_程心`（`normalize_group_title` 幂等补前缀）。
**桩与生产形态不一致**，于是下方 B-2 从未在本文件暴露。

**B-2**：闸机判定式 `t in title` 拿带前缀的标题去比不带前缀的镜头标题
⇒ `missing` **恒为空**。4444 实证：全部镜头标题命中数 = **0**。
本批桩已改为**生产形态**（`Element_程心`），并新增「带前缀标题必须被认出」
的反向钉——用旧实现跑它必红（突变验证见批12 CHANGELOG）。

**B-1**：闸机原**只看显式 `shot_refs`**，不看 `desc`。而工具对模型的文档承诺是
「留空时系统自动从描述里的 [元素名] 令牌与裸名提及解析合并」（写口确实这么做）
⇒ **模型按文档留空 = 被误杀**。4444 实证：前 5 次留空全被拒，此后 22 次被逼
显式重抄——**平台亲手教模型放弃正确行为**。
本批闸机改走写口同一实现 `ops.merge_shot_refs`（单一事实源）。

⚠️ **本文件的桩必须与生产落库形态一致**（B-3 的教训）：
`keyElements[].title` 一律带 `Element_` 前缀。
"""
import pytest

from src.video_agent.core import fc_gates, prompt_gates

# ⚠️ 桩 = 生产落库形态：KE 标题带容器前缀（normalize_group_title 的真实产物）
STATE = {
    "keyElements": [
        {"id": "ke-1", "title": "Element_程心", "drafts": []},
        {"id": "ke-2", "title": "Element_走廊", "drafts": []},
    ],
    "shots": [],
    "audioItems": [],
}


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "strict")


@pytest.fixture
def runner(monkeypatch):
    """闸机上下文工厂：runner(injected_skill) → fc_gates.GateContext。
    （阶段类别边界闸退役后本闸不再读当前阶段，故无需 stage 桩。）"""

    def _ctx(injected_skill="任意"):
        return fc_gates.GateContext(state=lambda: STATE,
                                    injected_skill=injected_skill)

    return _ctx


def _args(group_type="shot", title="程心走过走廊", shot_refs=None, desc=""):
    return {"group_type": group_type, "title": title, "desc": desc,
            "shot_refs": shot_refs or []}


# ---------- ① 无标题 add_group 拒收 ----------


def test_untitled_group_rejected(strict, runner):
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(title="  "))
    assert err is not None and "title" in err


def test_untitled_passes_when_gate_off(monkeypatch, runner):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(title="")) is None


def test_untitled_passes_without_skill(strict, runner):
    assert fc_gates.structure_integrity_gate(
        runner(""), "storyboard_create_group", _args(title="")) is None


# ---------- ② 分镜引用完整度 ----------


def test_shot_empty_refs_rejected(strict, runner):
    """真·漏引用（desc 里也没有任何元素线索）→ 拒收。"""
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="空镜远景", desc="纯风景无人物", shot_refs=[]))
    assert err is not None and "引用" in err


def test_bare_name_in_desc_passes_without_explicit_refs(strict, runner):
    """**B-1 回归钉**（事故原形）：按文档留空 `shot_refs`、元素写进 desc
    的 `[令牌]` ⇒ **必须放行**（写口会合并出来，闸机须同口径）。

    4444 实证：旧实现在此处拒收，模型被逼此后 22 次显式重抄。
    """
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="「星环」号球形舱内程心与走廊",
              desc="【空间锚点】[程心] 与 [走廊] 悬停舱内",
              shot_refs=[]))
    assert err is None, f"B-1 回归：按文档留空被误拒 —— {err}"


def test_bare_name_mention_passes_without_tokens(strict, runner):
    """裸名提及（无 [令牌]）同样由写口自动挂上 ⇒ 闸机须放行。"""
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="程心走过走廊", desc="程心沿走廊前行，无令牌",
              shot_refs=[]))
    assert err is None, f"裸名提及被误拒 —— {err}"


def test_prefixed_ke_title_recognized(strict, runner):
    """**B-2 回归钉**：标题点名了元素、但引用里没有 ⇒ 必须拒收。

    旧实现拿 `Element_程心` 去比 `程心走过走廊` ⇒ 恒不命中 ⇒ 放行（漏判）。
    本钉用旧实现必红。
    """
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="程心走过走廊", desc="无元素线索", shot_refs=["走廊"]))
    assert err is not None, "B-2 回归：标题点名的元素漏引却放行了"
    # 回喂用裸名（内部容器前缀对模型无意义）
    assert "程心" in err
    assert "Element_程心" not in err, "回喂应剥容器前缀"


def test_refs_by_id_or_title_pass(strict, runner):
    """兼容关键元素 id 与标题（含带前缀）两种写法。"""
    for refs in (["ke-1", "Element_走廊"], ["程心", "走廊"],
                 ["Element_程心", "Element_走廊"]):
        assert fc_gates.structure_integrity_gate(
            runner(), "storyboard_create_group",
            _args(desc="[程心] 与 [走廊]", shot_refs=refs)) is None, refs


def test_not_mentioned_ke_not_required(strict, runner):
    """标题未点名的关键元素不强制引用（不误伤无关分镜）。"""
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="空镜远景", desc="[走廊]", shot_refs=["走廊"])) is None


# ---------- ③ 各类别建组一律放行（阶段类别边界闸已退役） ----------


def test_all_group_kinds_pass_without_stage_boundary(strict, runner):
    """阶段类别边界闸退役（2026-09-10 计划 B2）：建组只看标题与引用完整度，
    不再按「当前阶段」限制 group_type。"""
    for kind, title in (("keyElement", "程心"), ("audio", "旁白轨")):
        assert fc_gates.structure_integrity_gate(
            runner(), "storyboard_create_group",
            _args(group_type=kind, title=title)) is None


# ---------- ④ 单一事实源：闸机与写口同引合并实现 ----------


def test_gate_shares_merge_impl_with_write_path(strict, runner):
    """**同源钉**：闸机必须调用 `ops.merge_shot_refs`（写口同一实现）。

    两处各写一遍正是 4444/B-1 的成因；本钉防回潮成第二份实现。
    """
    import inspect

    src = inspect.getsource(fc_gates.structure_integrity_gate)
    assert "merge_shot_refs" in src, "闸机未走写口同一合并实现（B-1 回潮）"


# ---------- 边界：非建组工具不受本闸管辖 ----------


def test_non_create_group_tools_pass(strict, runner):
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_patch_draft", _args(title="")) is None
