"""重试续跑现场组装测试（任务#6：出错重试改为带上下文续跑）。

钉死：
- 失败现场收集：优先 trace 账本（进度清单/中断点/失败原因），
  内部过程条目过滤、清单封顶、详情截断；
  trace 无失败摘要时回落聊天历史 ⚠️ 错误气泡（chat_errors 统一出口）；
- 前置块组装：固定话术外置模板（prompts/shared/retry_resume.md）渲染
  现场进 {{scene}} 占位；无现场/模板缺失/任何异常一律静默返回空串；
- chat_opening 接线：resume_failed 标记时前置块注入用户原消息之前
  （原消息原样保留），无标记/空现场不注入；
- 失败轮 trace 归档格式：record_error 后 to_dict 落 error 键，
  成功轮不写键（历史格式/体积不变）。
"""
from types import SimpleNamespace

import pytest

import src.video_agent.core.tracer as tr_mod
from src.video_agent.core.tracer import AgentTracer, TraceRecord
import src.video_agent.web.chat_opening as co
import src.video_agent.web.chat_retry_context as crc


class FakeSvc:
    """最小会话桩：只提供失败现场回落路径用到的消息账本"""

    def __init__(self, messages=None):
        self._messages = messages or []

    def get_chat_messages(self):
        return self._messages


def _action(name, ok=True, detail=""):
    return {"name": name, "summary": name, "ok": ok, "result_summary": detail}


def _trace(steps=None, error=""):
    return {
        "trace_id": "t-" + str(len(steps or [])),
        "timestamp": 1.0,
        "steps": steps or [],
        "error": error,
    }


@pytest.fixture
def patch_traces(monkeypatch):
    """把 get_recent_traces 换成内存夹具（不碰真实 agent_traces.jsonl）"""
    holder = {"traces": []}
    tracer = AgentTracer.get_instance()
    monkeypatch.setattr(
        tracer, "get_recent_traces", lambda limit=50: list(holder["traces"]))
    return holder


# ---------- collect_failure_scene：现场收集 ----------

def test_collect_scene_from_failed_trace(patch_traces):
    """失败轮 trace：进度清单按序、内部条目过滤、中断点定位首个失败工具"""
    patch_traces["traces"] = [_trace(steps=[{
        "finish_reason": "error",
        "actions": [
            _action("gen_script", True, "脚本已落盘"),
            _action("model_reasoning", True, "内部推理不该进现场"),
            _action("bad_output_retry", True, "内部重试不该进现场"),
            _action("gen_image", False, "上游供应商 503"),
        ],
    }], error="上游供应商 503")]
    scene = crc.collect_failure_scene(FakeSvc())
    assert scene is not None
    assert [p["name"] for p in scene["progress"]] == ["gen_script", "gen_image"]
    assert scene["progress"][1]["ok"] is False
    assert "gen_image" in scene["failed_at"]
    assert scene["error"] == "上游供应商 503"


def test_collect_scene_progress_cap_and_truncate(patch_traces):
    """现场规模封顶 12 条、详情截断（预算友好）"""
    acts = [_action(f"tool_{i}", True, "长" * 500) for i in range(20)]
    patch_traces["traces"] = [_trace(
        steps=[{"finish_reason": "error", "actions": acts}], error="x")]
    scene = crc.collect_failure_scene(FakeSvc())
    assert len(scene["progress"]) == 12
    # 封顶保留最近 12 条（旧条目先丢）
    assert scene["progress"][0]["name"] == "tool_8"
    assert len(scene["progress"][0]["detail"]) <= 120


def test_collect_scene_fallback_chat_error_bubble(patch_traces):
    """trace 无失败摘要：回落聊天历史最近 ⚠️ 错误气泡（只认最后一条
    user 消息之后的 agent 消息）"""
    patch_traces["traces"] = []
    svc = FakeSvc(messages=[
        {"sender": "user", "text": "⚠️ 这是用户消息不认"},
        {"sender": "agent", "text": "正常回复"},
        {"sender": "agent", "text": "⚠️ 生成服务中断，请稍后重试"},
    ])
    scene = crc.collect_failure_scene(svc)
    assert scene is not None
    assert scene["error"] == "生成服务中断，请稍后重试"
    assert scene["failed_at"]  # 无工具失败记录也有中断点兜底文案


def test_collect_scene_none_when_nothing(patch_traces):
    """无 trace 且无错误气泡：无现场可还原返回 None"""
    patch_traces["traces"] = []
    assert crc.collect_failure_scene(FakeSvc()) is None


def test_collect_scene_prefers_failed_over_success_turn(patch_traces):
    """多轮在场：优先失败轮（新→旧扫描），成功轮进度不冒名顶替"""
    failed = _trace(steps=[{
        "finish_reason": "error",
        "actions": [_action("gen_video", False, "渲染失败")],
    }], error="渲染失败")
    success = _trace(steps=[{
        "finish_reason": "stop", "actions": [_action("gen_script", True)],
    }])
    patch_traces["traces"] = [success, failed]  # 失败轮不在最新位也要被挑出
    scene = crc.collect_failure_scene(FakeSvc())
    assert [p["name"] for p in scene["progress"]] == ["gen_video"]


def test_collect_scene_trace_read_failure_silent(monkeypatch, patch_traces):
    """trace 读取异常静默回落聊天错误气泡（重试绝不因续跑组装报错）"""
    tracer = AgentTracer.get_instance()
    monkeypatch.setattr(
        tracer, "get_recent_traces", lambda limit=50: (_ for _ in ()).throw(RuntimeError("boom")))
    svc = FakeSvc(messages=[{"sender": "agent", "text": "⚠️ 上游故障"}])
    scene = crc.collect_failure_scene(svc)
    assert scene is not None and scene["error"] == "上游故障"


# ---------- build_retry_resume_note：前置块组装与静默回落 ----------

def test_build_note_renders_template_with_scene(patch_traces):
    """有现场：外置模板渲染现场（话术头 + 清单 + 中断点 + 失败原因）"""
    patch_traces["traces"] = [_trace(steps=[{
        "finish_reason": "error",
        "actions": [
            _action("gen_script", True, "脚本已落盘"),
            _action("gen_image", False, "供应商故障"),
        ],
    }], error="供应商故障")]
    note = crc.build_retry_resume_note(FakeSvc())
    assert note
    assert "续跑" in note                      # 外置模板话术头
    assert "{{scene}}" not in note             # 占位必须被替换
    assert "gen_script" in note and "gen_image" in note
    assert "中断点" in note and "供应商故障" in note


def test_build_note_empty_when_no_scene(patch_traces):
    """无现场：返回空串（调用方静默回落机械重发）"""
    patch_traces["traces"] = []
    assert crc.build_retry_resume_note(FakeSvc()) == ""


def test_build_note_empty_when_template_missing(patch_traces, monkeypatch):
    """模板缺失：返回空串不报错"""
    patch_traces["traces"] = [_trace(steps=[{
        "finish_reason": "error", "actions": [_action("x", False)],
    }], error="e")]
    monkeypatch.setattr(crc, "load_prompt_section", lambda p, s: "")
    assert crc.build_retry_resume_note(FakeSvc()) == ""


def test_build_note_empty_on_any_exception(monkeypatch):
    """任何异常：返回空串（用户无感知回落，重试本身不受影响）"""
    monkeypatch.setattr(
        crc, "collect_failure_scene", lambda svc: (_ for _ in ()).throw(RuntimeError("boom")))
    assert crc.build_retry_resume_note(FakeSvc()) == ""


# ---------- render_scene：现场渲染格式 ----------

def test_render_scene_marks():
    text = crc.render_scene({
        "progress": [
            {"name": "a", "ok": True, "detail": "done"},
            {"name": "b", "ok": False, "detail": ""},
        ],
        "failed_at": "执行到工具 b 时失败",
        "error": "boom",
    })
    assert "✔ a —— done" in text
    assert "✘ b" in text
    assert "中断点：执行到工具 b 时失败" in text
    assert "失败原因：boom" in text


# ---------- chat_opening 接线：续跑块单独返回 ----------

def _body(resume_failed=None):
    kwargs = {"pause_response": None, "attachments": []}
    if resume_failed is not None:
        kwargs["resume_failed"] = resume_failed
    return SimpleNamespace(**kwargs)


async def test_opening_returns_resume_note_separately(monkeypatch):
    """resume_failed 且有现场：续跑块随第四元单独返回，用户文本不被
    prepend（多模态构建层 content_parts 分支不用 text 参数，须走 leading_note）"""
    monkeypatch.setattr(co, "build_retry_resume_note", lambda svc: "【续跑前置块】")
    llm_text, signal, resume_note = await co._prepare_chat_opening(
        FakeSvc(), _body(resume_failed=True), "原指令", use_studio_context=False)
    assert llm_text == "原指令"          # 用户原消息不被篡改（持久化气泡同源）
    assert resume_note == "【续跑前置块】"
    assert signal == ""


async def test_opening_silent_fallback_when_note_empty(monkeypatch):
    """resume_failed 但无现场（空串）：续跑块为空，调用方回落机械重发"""
    monkeypatch.setattr(co, "build_retry_resume_note", lambda svc: "")
    llm_text, _, resume_note = await co._prepare_chat_opening(
        FakeSvc(), _body(resume_failed=True), "原指令", use_studio_context=False)
    assert llm_text == "原指令" and resume_note == ""


async def test_opening_no_injection_without_flag(monkeypatch):
    """无标记/标记为 False：绝不组装现场（普通消息零开销零影响）"""
    monkeypatch.setattr(
        co, "build_retry_resume_note",
        lambda svc: pytest.fail("无标记不应触发续跑组装"))
    for body in (_body(resume_failed=False), _body(resume_failed=None)):
        llm_text, _, resume_note = await co._prepare_chat_opening(
            FakeSvc(), body, "原指令", use_studio_context=False)
        assert llm_text == "原指令" and resume_note == ""


# ---------- 端到端：续跑块经 build_multimodal_content 不丢 ----------

def test_build_multimodal_keeps_resume_note_with_content_parts(patch_traces):
    """必修回归：resume_failed + 非空 content_parts（前端重发恒携，
    纯文本也有单个 text part）时，build_multimodal_content 返回值必含
    续跑块——修复前 content_parts 交错分支不用 text 参数，前置块被静默丢弃"""
    import asyncio

    from src.video_agent.web.multimodal_builder import build_multimodal_content

    patch_traces["traces"] = [_trace(steps=[{
        "finish_reason": "error",
        "actions": [
            _action("gen_script", True, "脚本已落盘"),
            _action("gen_image", False, "供应商故障"),
        ],
    }], error="供应商故障")]
    note = crc.build_retry_resume_note(FakeSvc())
    assert note  # 现场存在，前置块非空（外置模板渲染成功）
    out = asyncio.run(build_multimodal_content(
        "原指令", [], [],
        content_parts=[{"type": "text", "text": "原指令"}],
        leading_note=note,
    ))
    # 续跑块不丢且位于用户原文之前（降级纯文本路径同样生效）
    assert "续跑" in out and "gen_image" in out
    assert out.index("续跑") < out.index("原指令")
    assert "{{scene}}" not in out


async def test_build_multimodal_keeps_resume_note_interleaved_with_media(monkeypatch):
    """含内联媒体的交错路径：前置块进首个 text part，媒体 part 位置不变"""
    import src.video_agent.web.multimodal_builder as mm

    async def _fake_resolve(url):
        return url

    monkeypatch.setattr(mm, "resolve_injectable_url", _fake_resolve)
    out = await mm.build_multimodal_content(
        "原指令", [], [],
        content_parts=[
            {"type": "text", "text": "参考这张图"},
            {"type": "image", "url": "https://x/1.png", "name": "参考图"},
            {"type": "text", "text": "接着写"},
        ],
        leading_note="【续跑前置块】",
    )
    assert isinstance(out, list)
    assert out[0]["type"] == "text"
    assert out[0]["text"].startswith("【续跑前置块】")
    assert "参考这张图" in out[0]["text"]  # 相邻文本合并，排版顺序不变
    assert out[1]["type"] == "image_url"
    assert out[2]["type"] == "text" and "接着写" in out[2]["text"]


async def test_build_multimodal_plain_text_branch_prepends_note():
    """纯文本支路（无 content_parts 无媒体）：前置块前置，空串时行为不变"""
    from src.video_agent.web.multimodal_builder import build_multimodal_content

    out = await build_multimodal_content(
        "原指令", [], [], leading_note="【续跑前置块】")
    assert out == "【续跑前置块】\n\n原指令"
    # 空前置块：与旧版逐字节一致（回归护栏）
    assert await build_multimodal_content("原指令", [], []) == "原指令"
    assert await build_multimodal_content(
        "原指令", [], [], leading_note="") == "原指令"


# ---------- 错误气泡回溯范围（小修 1） ----------

def test_last_error_bubble_scoped_after_last_user_message():
    """只认最后一条 user 消息之后的 ⚠️ 气泡：防「进度是新轮、原因是旧错误」错位"""
    msgs = [
        {"sender": "user", "text": "旧指令"},
        {"sender": "agent", "text": "⚠️ 旧错误不该被取"},
        {"sender": "user", "text": "新指令"},
        {"sender": "agent", "text": "正常回复"},
    ]
    # 新轮无错误气泡：宁缺毋滥，回落无错误原因（而非误引旧错误）
    assert crc._last_error_chat_message(FakeSvc(messages=msgs)) == ""
    msgs.append({"sender": "agent", "text": "⚠️ 本轮真实错误"})
    assert crc._last_error_chat_message(FakeSvc(messages=msgs)) == "本轮真实错误"
    # 无 user 消息时同样可取（首轮流式失败等场景，无错位风险）
    assert crc._last_error_chat_message(FakeSvc(messages=[
        {"sender": "agent", "text": "⚠️ 首轮错误"}])) == "首轮错误"


# ---------- tracer：失败轮归档格式 ----------

def test_trace_record_error_lands_in_dict(tmp_path, monkeypatch):
    """record_error → end_step(error) → finish_trace：error 键落账"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    t = AgentTracer()
    t.start_trace("失败轮")
    t.start_step()
    t.record_action("gen_image", "生图", ok=False, result_summary="供应商故障")
    t.record_error("上游供应商 503")
    t.end_step(1, finish_reason="error")
    rec = t.finish_trace()
    assert rec["error"] == "上游供应商 503"
    assert rec["steps"][0]["finish_reason"] == "error"


def test_trace_success_round_no_error_key(tmp_path, monkeypatch):
    """成功轮不写 error 键（历史格式/体积不变）"""
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    rec = TraceRecord(trace_id="ok-round").to_dict()
    assert "error" not in rec
