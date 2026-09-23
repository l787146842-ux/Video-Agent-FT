# -*- coding: utf-8 -*-
"""批11（2026-09-23，事故 4444/P1-5）：草稿 mediaType 的唯一推导入口。

## 事故原形（4444 实跑取证，conv-1790159633-e7d76b40）

子代理在故事板设计阶段建音频卡时，**只填了 `audioType`**（`bgm`/`voice`）——
它以为声明了「这是音频卡」就够了。但 `mediaType` 是**另一个维度**，其默认值是
`image`，于是：

```
seq108  5 次 storyboard_create_group 全部被拒：
        被拒收：本阶段（故事板设计）新建草稿卡只允许 mediaType=audio/video，
        收到 'image'
seq118  同一批补上 mediaType='audio' 后 → 全部通过
```

**关键**：模型从未发过 `'image'` 这个词——那是**平台自己的默认值**
（`DRAFT_DEFAULT_FIELDS["mediaType"] = "image"`），闸机按同一口径取值后
**拿平台默认值当模型意图回喂**。一次纯浪费的往返（5 个调用全废）。

## 根因与修法

根因 = **`mediaType` 的缺省取值在多处各写一遍 `or "image"`**
（构建工厂 / 闸机 / prompt_refs 三处），而平台**本就持有**「填了 audioType
就是音频卡」这个事实（`AUDIO_TYPES` 词表 + `key_element_audio` 契约）。

修法 = 抽 `models.infer_media_type` 作**唯一推导入口**（显式优先 → audioType
推导 → 回落 image），三处同引一实现。

## 本文件钉什么

1. 推导规则本身（显式优先、audioType 推导、零变化回落）；
2. **三个消费面同口径**（构建工厂 / 闸机 / prompt_refs）——防再次各写一遍；
3. 事故场景端到端复现：只填 audioType 的音频卡必须放行；
4. 显式 image 不被静默改写（本层不越权改写入参）。
"""
import pytest

from src.video_agent.core.prompt_refs import media_of_draft
from src.video_agent.state.models import (
    AUDIO_TYPE_TO_MEDIA,
    MEDIA_TYPES,
    build_draft_dict,
    infer_media_type,
)


class TestInferMediaType:
    """唯一推导入口的规则（写口与读口共用同一实现）。"""

    def test_explicit_value_wins(self):
        """显式声明优先，不被 audioType 覆盖（本层不越权改写入参）。"""
        assert infer_media_type({"mediaType": "image"}) == "image"
        assert infer_media_type({"mediaType": "video"}) == "video"
        assert infer_media_type({"mediaType": "audio"}) == "audio"
        # 显式 image + audioType 并存 → 尊重显式（是否合法交闸机判）
        assert infer_media_type(
            {"mediaType": "image", "audioType": "voice"}) == "image"

    def test_explicit_value_normalized(self):
        """显式值大小写/空白归一（落库统一 canonical 小写）。"""
        assert infer_media_type({"mediaType": "  AUDIO  "}) == "audio"

    @pytest.mark.parametrize("at", sorted(AUDIO_TYPE_TO_MEDIA))
    def test_audio_type_infers_audio(self, at):
        """**事故核心**：只填 audioType ⇒ 推导为 audio（不再回落 image）。"""
        assert infer_media_type({"audioType": at}) == "audio"

    def test_audio_type_normalized(self):
        assert infer_media_type({"audioType": " VOICE "}) == "audio"

    def test_unknown_audio_type_still_audio(self):
        """未登记在词表内的 audioType 仍推为 audio（保守：有 audioType 即音频卡）。"""
        assert infer_media_type({"audioType": "某个未来种类"}) == "audio"

    def test_no_hint_falls_back_to_image(self):
        """都没有 ⇒ image（历史默认，零行为变化）。"""
        assert infer_media_type({}) == "image"
        assert infer_media_type({"label": "x"}) == "image"
        assert infer_media_type({"audioType": ""}) == "image"

    def test_media_types_is_the_closed_set(self):
        """推导结果必须落在合法闭集内。"""
        for probe in ({}, {"audioType": "voice"}, {"mediaType": "video"},
                      {"mediaType": "image"}):
            assert infer_media_type(probe) in MEDIA_TYPES


class TestFactoryUsesInference:
    """构建工厂（写口）走同一推导。"""

    def test_audio_card_without_media_type_lands_as_audio(self):
        """事故原形：只填 audioType 的卡，落库必须是 audio。"""
        d = build_draft_dict({"audioType": "voice", "label": "voice-程心"})
        assert d["mediaType"] == "audio"
        d2 = build_draft_dict({"audioType": "bgm"})
        assert d2["mediaType"] == "audio"

    def test_plain_card_unchanged(self):
        """无任何提示的卡维持 image（既有行为不翻）。"""
        assert build_draft_dict({"label": "x"})["mediaType"] == "image"

    def test_explicit_still_respected(self):
        assert build_draft_dict({"mediaType": "video"})["mediaType"] == "video"


class TestGateUsesSameInference:
    """闸机（读口）必须判「该卡真实会落库的那个类型」。"""

    @pytest.fixture
    def ctx(self):
        from src.video_agent.core.fc_gates import GateContext

        return GateContext(stage_card_media=frozenset({"audio", "video"}),
                           stage_label="故事板设计")

    def test_audio_card_without_media_type_passes(self, ctx):
        """**4444/P1-5 回归钉**：只填 audioType 的音频卡不得被拒。"""
        from src.video_agent.core.fc_gates import card_media_gate

        for at in ("voice", "bgm", "narration"):
            err = card_media_gate(ctx, "storyboard_add_draft",
                                  {"draft": {"audioType": at}})
            assert err is None, (
                f"只填 audioType={at} 的音频卡被拒收（4444/P1-5 回归）")

    def test_real_image_card_still_rejected(self, ctx):
        """真·图卡仍拒（本修复不放开跨阶段产物）。"""
        from src.video_agent.core.fc_gates import card_media_gate

        err = card_media_gate(ctx, "storyboard_add_draft",
                              {"draft": {"mediaType": "image"}})
        assert err is not None
        assert "只允许 mediaType=audio/video" in err

    def test_gate_and_factory_agree(self, ctx):
        """**同口径钉**：闸机放行 ⟺ 工厂落库的类型在允许集内。

        这正是本次事故的缺口——两处各写一遍 `or "image"` 才会漂移。
        """
        from src.video_agent.core.fc_gates import card_media_gate

        allowed = frozenset({"audio", "video"})
        for draft in ({"audioType": "voice"}, {"audioType": "bgm"},
                      {"mediaType": "image"}, {"mediaType": "video"},
                      {"label": "x"}, {}):
            landed = build_draft_dict(dict(draft))["mediaType"]
            gate_rejects = card_media_gate(
                ctx, "storyboard_add_draft", {"draft": dict(draft)}) is not None
            assert gate_rejects == (landed not in allowed), (
                f"闸机与工厂口径不一致：draft={draft} 落库={landed} "
                f"闸机拒={gate_rejects}")


class TestPromptRefsUsesSameInference:
    """`media_of_draft`（第三处）同口径——此前也是各写一遍。"""

    def test_audio_card_without_media_type_reads_as_audio(self):
        url, kind = media_of_draft(
            {"audioType": "voice", "audioUrl": "http://a.wav"})
        assert (url, kind) == ("http://a.wav", "audio")

    def test_image_card_unchanged(self):
        url, kind = media_of_draft(
            {"mediaType": "image", "imgUrl": "http://i.png"})
        assert (url, kind) == ("http://i.png", "image")


class TestSingleSourceOfTruth:
    """防回潮：三处不得再各写一遍 `or "image"`。"""

    def test_no_local_image_fallback_left(self):
        """源码级钉：三个消费面都必须引用推导入口，不得内联回落串。

        口径：只看**可执行代码**（剥离注释与 docstring 后再断言），
        否则事故说明里引用的旧写法 `or "image"`（作为反例出现在注释中）
        会被误判为回潮。
        """
        import ast
        import inspect

        from src.video_agent.core import fc_gates, prompt_refs
        from src.video_agent.state import models

        def code_only(fn) -> str:
            """剥离注释/docstring 后的源码（只留可执行部分）。"""
            src = inspect.getsource(fn)
            tree = ast.parse(
                __import__("textwrap").dedent(src))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef, ast.Module)):
                    body = getattr(node, "body", [])
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        body.pop(0)
            # 注释不进 AST，rebuild 后自然消失
            return ast.unparse(tree)

        assert "infer_media_type" in code_only(models.build_draft_dict)
        gate_code = code_only(fc_gates.card_media_gate)
        assert "infer_media_type" in gate_code, "闸机未引用唯一推导入口"
        assert 'or "image"' not in gate_code.replace("'", '"'), \
            "闸机可执行代码里仍有内联回落串（口径漂移回潮）"
        assert "infer_media_type" in code_only(prompt_refs.media_of_draft)
