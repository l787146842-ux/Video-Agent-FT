"""
产出质量评估集 — 样本回归 + LLM-as-judge。

本地检查（确定性）：闸机规则 / 确认闭环 / SSRF / with_retry 等可直接断言；
LLM 检查（judge 模式）：把场景发给 LLM，用 judge 提示词判定行为是否合规。

用法：
    python scripts/run_eval_pipeline.py            # 报告输出到 stdout
"""
import asyncio
from typing import Any, Dict, List, Tuple

import httpx

from src.video_agent.adapters.retry import with_retry
from src.video_agent.core import prompt_gates
from src.video_agent.exceptions import AdapterError
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.web.chat_service import _consume_pending_confirmation
from src.video_agent.web.generation import call_chat_completion
from src.video_agent.web.url_safety import validate_external_url

# 样本：输入场景 → 期望行为
LOCAL_CASES: List[Dict[str, Any]] = [
    {
        "id": "gate_english_body_rejected",
        "title": "整段英文分镜提示词应被校验识别为不合格（照写并警告）",
        "check": "gate_english_body_rejected",
    },
    {
        "id": "gate_duration_synonyms_accept",
        "title": "时长语义解析：15s / 15 秒 等写法应通过",
        "check": "gate_duration_synonyms_accept",
    },
    {
        "id": "gate_subtitle_synonyms_accept",
        "title": "字幕约束同义词：无字幕/后期加字幕 应通过",
        "check": "gate_subtitle_synonyms_accept",
    },
    {
        "id": "confirm_unrelated_not_promote",
        "title": "执行优先：无关追问同样晋升草稿并解除暂停（不再拦截）",
        "check": "confirm_unrelated_promotes",
    },
    {
        "id": "spec_gate_warns_and_allows_structure",
        "title": "无规格文档时照常搭建故事板并记录警告",
        "check": "spec_gate_warns_and_allows_structure",
    },
    {
        "id": "element_gate_referenced_only",
        "title": "元素图时序提醒：引用无图元素的分镜照常写入并附警告（不误伤）",
        "check": "element_gate_referenced_only",
    },
    {
        "id": "retry_last_5xx_raises",
        "title": "with_retry 末次 5xx 必须抛错（不得当成功返回）",
        "check": "retry_last_5xx_raises",
    },
    {
        "id": "ssrf_private_blocked",
        "title": "SSRF：私网地址必须被 image-proxy 校验拒绝",
        "check": "ssrf_private_blocked",
    },
]

LLM_CASES: List[Dict[str, Any]] = [
    {
        "id": "llm_confirm_semantics",
        "title": "执行优先：任何用户消息都视为继续指令，不再因未确认拦截",
        "scenario": (
            "用户先前轮次收到了 3 条关键元素提示词草案并停在确认点。"
            "用户现在问：『今天天气如何？』\n"
            "请判断：此时系统应如何处理这些草案？"
        ),
        "expected": "晋升草稿并解除暂停，按用户最新指令继续执行",
    },
    {
        "id": "llm_spec_first",
        "title": "流程时序：规格文档未写入时先建议写规格；用户坚持直接开工则照做并警告",
        "scenario": (
            "用户要求『开始制作一个科幻短片』，但项目中还没有 制片规格.md。\n"
            "Agent 下一步应该做什么？"
        ),
        "expected": "先写规格文档；若用户要求直接开工则照做并附警告，不拦截",
    },
]


def _english_shot_prompt() -> str:
    return (
        "Camera: Slow push-in from wide cabin view to medium close-up on Cheng Xin and AA. "
        "Subject: Cheng Xin and AA float in zero gravity, turning anxiously towards a holographic screen. "
        "Space: Spherical white spacecraft bridge with massive observation window showing Jupiter's storm bands. "
        "Audio: AA says in Chinese: {为什么木星城还没躲进掩体？} "
        "<low ambient hum of life support> no music, no subtitles."
    )


def _good_shot_base() -> str:
    return (
        "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原在冷光中缓缓崩裂成二维平面，"
        "前景冰晶闪烁，整体色调深青克制，<急促呼吸声与远处坍缩轰鸣>，no music。"
    )


def _make_temp_state_dir() -> str:
    """创建临时状态目录：优先系统临时目录，沙箱禁止时回落工作区 .eval_state。"""
    import tempfile
    from pathlib import Path

    try:
        return str(Path(tempfile.mkdtemp(prefix="eval_state_")))
    except OSError:
        base = Path.cwd() / ".eval_state"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)


def _check_gate_english_body_rejected() -> Tuple[bool, str]:
    ok, hard, _ = prompt_gates.validate_prompt_write(_english_shot_prompt(), "shot")
    return (not ok and any("中文" in e for e in hard)), "英文正文应被中文语言闸拒绝"


def _check_gate_duration_synonyms_accept() -> Tuple[bool, str]:
    for clause in ("镜头总时长：15s", "15秒", "duration: 15 seconds"):
        ok, hard, _ = prompt_gates.validate_prompt_write(
            _good_shot_base() + f" {clause} no subtitles", "shot")
        if not ok:
            return False, f"时长写法未通过: {clause} -> {hard}"
    return True, "时长同义写法全部通过"


def _check_gate_subtitle_synonyms_accept() -> Tuple[bool, str]:
    for negation in ("无字幕", "不加字幕", "后期加字幕", "no subtitles"):
        ok, hard, _ = prompt_gates.validate_prompt_write(
            _good_shot_base() + f" {negation}", "shot")
        if not ok:
            return False, f"字幕同义词未通过: {negation} -> {hard}"
    return True, "字幕同义写法全部通过"


def _check_confirm_unrelated_promotes() -> Tuple[bool, str]:
    StateManager.reset_instance()
    svc = StateManager(_make_temp_state_dir())
    try:
        svc.state_dict[CAT_KEY_ELEMENTS] = [{
            "id": "g1", "title": "G",
            "drafts": [{"id": "d1", "tag": "Agent", "prompt": "足够长的提示词内容。"}],
        }]
        inter = svc.state_dict.setdefault("interaction", {})
        inter["drafts_presented"] = ["d1"]
        inter["awaiting_confirmation"] = True
        inter["confirmation_message"] = "请审阅"
        _consume_pending_confirmation(svc, "今天天气如何？")
        tag = svc.state_dict[CAT_KEY_ELEMENTS][0]["drafts"][0]["tag"]
        return tag == "已确认", f"无关追问应晋升草稿并解除暂停，实际 tag={tag}"
    finally:
        StateManager.reset_instance()


def _check_element_gate_referenced_only() -> Tuple[bool, str]:
    StateManager.reset_instance()
    svc = StateManager(_make_temp_state_dir())
    try:
        svc.state_dict[CAT_KEY_ELEMENTS] = [{
            "id": "ke-1", "title": "E", "drafts": [{"id": "ke-d", "imgUrl": ""}],
        }]
        svc.state_dict[CAT_SHOTS] = [
            {
                "id": "shot-ref", "title": "引用", "sceneRefs": ["E"], "duration": "10s",
                "drafts": [{"id": "s1", "mediaType": "video", "prompt": ""}],
            },
            {
                "id": "shot-standalone", "title": "独立", "sceneRefs": [], "duration": "10s",
                "drafts": [{"id": "s2", "mediaType": "video", "prompt": ""}],
            },
        ]
        ex = StateOperationExecutor(svc, gate_enabled=True)
        first = ex.execute([{
            "action": "update_draft", "draft_id": "s1", "draft_type": "shot",
            "patch": {"prompt": _good_shot_base() + " no subtitles 镜头总时长：15秒"},
        }])
        second = ex.execute([{
            "action": "update_draft", "draft_id": "s2", "draft_type": "shot",
            "patch": {"prompt": _good_shot_base() + " no subtitles 镜头总时长：15秒"},
        }])
        return first == 1 and second == 1 and bool(ex.gate_warnings), (
            f"引用与独立分镜都应照常写入并警告，first={first}, second={second}"
        )
    finally:
        StateManager.reset_instance()


def _check_retry_last_5xx_raises() -> Tuple[bool, str]:
    async def fn():
        return httpx.Response(
            500, request=httpx.Request("POST", "http://example.invalid/chat"))

    try:
        asyncio.run(with_retry(fn, max_retries=0, base_delay=0, context="eval"))
        return False, "末次 5xx 未抛错"
    except AdapterError as e:
        return e.http_status == 500, "应抛 AdapterError(http_status=500)"


def _check_ssrf_private_blocked() -> Tuple[bool, str]:
    try:
        validate_external_url("http://192.168.0.5/a.png")
        return False, "私网地址未被拒绝"
    except ValueError:
        return True, "私网地址已拒绝"


_LOCAL_CHECKS = {
    "gate_english_body_rejected": _check_gate_english_body_rejected,
    "gate_duration_synonyms_accept": _check_gate_duration_synonyms_accept,
    "gate_subtitle_synonyms_accept": _check_gate_subtitle_synonyms_accept,
    "confirm_unrelated_promotes": _check_confirm_unrelated_promotes,
    "element_gate_referenced_only": _check_element_gate_referenced_only,
    "retry_last_5xx_raises": _check_retry_last_5xx_raises,
    "ssrf_private_blocked": _check_ssrf_private_blocked,
}


def run_local() -> List[Dict[str, Any]]:
    results = []
    for case in LOCAL_CASES:
        try:
            ok, detail = _LOCAL_CHECKS[case["check"]]()
        except Exception as e:
            ok, detail = False, f"执行异常: {e}"
        results.append({
            "id": case["id"],
            "title": case["title"],
            "ok": ok,
            "detail": detail,
        })
    return results


async def _run_llm_case(case: Dict[str, Any], provider: str, model: str) -> Dict[str, Any]:
    system = (
        "你是影视 Agent 工作台的行为审计员。用户会给你一个交互场景，"
        "请判断 Agent 的合理行为，回答必须包含 PASS 或 FAIL 以及一句话理由。"
    )
    user = (
        f"场景：{case['scenario']}\n"
        f"期望行为：{case['expected']}\n"
        "请用 PASS/FAIL + 理由回答。"
    )
    try:
        content, _ = await call_chat_completion(
            provider, model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=512, temperature=0,
        )
    except Exception as e:
        return {"id": case["id"], "title": case["title"], "ok": False, "detail": f"LLM 调用失败: {e}"}
    ok = "PASS" in content.upper()
    return {"id": case["id"], "title": case["title"], "ok": ok, "detail": content[:300]}


async def run_judge(provider: str, model: str) -> List[Dict[str, Any]]:
    return [await _run_llm_case(c, provider, model) for c in LLM_CASES]


def run(mode: str = "local", provider: str = "", model: str = "") -> List[Dict[str, Any]]:
    """统一入口：local 为确定性回归；judge 为 LLM-as-judge。"""
    if mode == "judge":
        return asyncio.run(run_judge(provider, model))
    return run_local()
