"""compaction 采样过滤系统回喂型消息语义钉死（任务 #10 采样过滤）。

钉死：
1. 「（系统）」前缀的系统回喂条目（工具回喂/FEEDBACK_COMPRESSED 占位/
   步间回喂/暂停回应提示）不进采样；
2. 步间注入的用户引导消息解包还原用户原文后保留（真实意图不丢）；
3. 真实用户/助手对话照常采样；采样预算口径不变；
4. 过滤只作用于采样视角：指纹仍对全量计算（失效语义不变）。
"""
from src.video_agent.web import history_compact as cc


def test_system_refeed_messages_filtered():
    older = [
        {"role": "user", "content": "我要做一个古风甜宠短剧"},
        {"role": "assistant", "content": "好的，先拆解故事板"},
        {"role": "user", "content": "（系统）第 1 轮的 3 个 Tool 已执行完毕，工作台状态已刷新（见对话末尾最新的工作台状态 JSON）。请继续完成任务；全部完成后直接回复文本即可。"},
        {"role": "user", "content": "（系统）此前轮次工具读回的文档全文已从上下文移除以节约空间；其中的流程与约束仍须遵守，如确需复核原文请重新调用对应 read_* 工具。"},
        {"role": "user", "content": "（系统）本轮调用的工具已执行完毕，结果如下："},
        {"role": "user", "content": "（系统提示：上一轮已通过 workflow_pause 暂停等待确认，暂停内容：请审阅规格文档。）"},
        {"role": "user", "content": "（系统：已按你的选择拼装并写入 Final_Video_Spec.md 规格文档，不必再手写规格。）"},
        {"role": "assistant", "content": "故事板已拆好，请审阅"},
    ]
    out = cc._sample_older_dialog(older)
    assert "古风甜宠短剧" in out
    assert "故事板已拆好" in out
    assert "Tool 已执行完毕" not in out
    assert "从上下文移除" not in out
    assert "结果如下" not in out
    assert "暂停等待确认" not in out
    assert "不必再手写规格" not in out


def test_guidance_injection_unwrapped_to_user_text():
    """步间注入的用户引导：外层系统包装剥掉，内层用户原文保留"""
    wrapped = ("（任务执行期间收到您的指令：把主角名字改成林晚）"
               "请优先处理；若为提问先回答，处理完继续原任务。")
    out = cc._sample_older_dialog([{"role": "user", "content": wrapped}])
    assert "把主角名字改成林晚" in out
    assert "任务执行期间收到您的指令" not in out


def test_dialog_sample_text_classify():
    assert cc._dialog_sample_text(
        {"role": "user", "content": "（系统）xxx"}) == ""
    assert cc._dialog_sample_text(
        {"role": "user", "content": "   "}) == ""
    assert cc._dialog_sample_text(
        {"role": "user", "content": "真实对话"}) == "真实对话"
    # 多模态 content 保持 repr 采样口径（不抛、非空）
    assert cc._dialog_sample_text(
        {"role": "user", "content": [{"type": "text", "text": "hi"}]})


def test_all_refeed_returns_empty_sample():
    older = [{"role": "user", "content": "（系统）噪声"}] * 5
    assert cc._sample_older_dialog(older) == ""


def test_sample_cap_applies_after_filter():
    """过滤后采样预算口径不变：上限仍为 _HISTORY_SAMPLE_CAP 行"""
    older = (
        [{"role": "user", "content": f"真实消息{i}"} for i in range(30)]
        + [{"role": "user", "content": "（系统）噪声"}] * 20
    )
    out = cc._sample_older_dialog(older)
    lines = out.splitlines()
    assert len(lines) <= cc._HISTORY_SAMPLE_CAP
    assert not any("（系统）" in ln for ln in lines)


def test_fingerprint_still_covers_full_history():
    """过滤只作用于采样视角：指纹对全量计算，回喂条目增删仍触发失效"""
    older_a = [{"role": "user", "content": "（系统）回喂甲"}]
    older_b = [{"role": "user", "content": "（系统）回喂乙"}]
    assert cc._history_fingerprint(older_a) != cc._history_fingerprint(older_b)
