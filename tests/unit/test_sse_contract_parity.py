"""SSE 契约对拍（任务 #3 E-1）：后端 sse_events.py ↔ 前端 SseEvent 联合类型。

防漂移方案选型：直接解析 src/web/types/index.ts 源码提取 SseEvent 联合成员与
各接口 `type: '<字面量>'`、字段名，与后端常量对拍——事件名集合零对照表维护；
仅对"关键字段"维护一份对照表（_KEY_FIELDS），字段增删只需改一处。

同步规则（改动契约时的必做动作）：
1. 后端 sse_events.py 增/删事件常量 → 前端 types/index.ts 的 SseEvent 联合与
   对应 Sse*Event 接口必须同步，本测试事件名对拍失败即提醒；
2. 事件的关键载荷字段变化 → 更新本文件 _KEY_FIELDS 对照表与前端接口；
3. 豁免清单须有明确理由（见 _BACKEND_ONLY / _FRONTEND_ONLY 注释），
   新增豁免必须在此登记，禁止默默绕过。
"""
import re
from pathlib import Path

import pytest

from src.video_agent.core import sse_events

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TYPES_TS = _REPO_ROOT / "src" / "web" / "types" / "index.ts"

# 后端有、前端联合类型刻意不接的事件（登记理由，防静默漂移）
_BACKEND_ONLY = {
    # 多步循环轮次开始：agent_loop 内部事件，前端目前忽略（sse_events.py 注释）
    "step_started",
}
# 前端有、不属于 sse_events.py 常量的事件（web 层发射，非 core 契约）
_FRONTEND_ONLY = {
    "replay",        # agent_task_manager 订阅首帧：累计状态回放
    "task_status",   # agent_task_manager 任务状态变更通知（如 cancelled）
}

# 关键字段对照表：事件名 → 前端接口必须声明的字段（防载荷字段漂移）
_KEY_FIELDS = {
    "status": {"key", "text", "params"},
    "delta": {"text"},
    "reasoning_delta": {"text"},
    # 任务 #2：args = 输入参数预览（core/tool_args_preview 裁剪脱敏），分级展开依赖
    "tool_started": {"id", "name", "summary", "args"},
    "tool_finished": {"id", "ok", "elapsed_ms", "result_summary"},
    "doc_written": {"name", "turn_id"},
    "model_fallback": {"provider", "model"},
    "done": {"payload"},
    "stopped": {"phase", "inflight"},
    "error": {"detail", "error_code", "raw", "code", "kind"},
    "actions_applied": {"payload"},
    "guidance_injected": {"id", "text"},
}


def _backend_event_names() -> set[str]:
    """后端权威事件名集合（常量值即契约，不解析字符串避免两处维护）。"""
    return {
        getattr(sse_events, name)
        for name in sse_events.__all__
        if name.startswith("SSE_")
    }


def _parse_frontend_types() -> tuple[set[str], set[str], dict[str, set[str]]]:
    """解析 types/index.ts：返回 (联合成员接口名, 事件字面量集合, 接口字段表)。

    只扫 Sse 前缀接口（SseEvent 契约族），避免误吞业务接口；
    接口体取到独占一行的闭括号（兼容嵌套内联对象）。
    """
    src = _TYPES_TS.read_text(encoding="utf-8")

    union_m = re.search(r"export type SseEvent\s*=\s*(.*?);", src, re.S)
    assert union_m, "types/index.ts 缺少 SseEvent 联合类型定义"
    members = set(re.findall(r"\|\s*(\w+)", union_m.group(1)))
    assert members, "SseEvent 联合类型成员为空"

    # 逐接口提取：type 字面量（必选锚定，非可选字段）+ 顶层字段名；
    # 单行/多行双通道（单行接口闭括号不独占一行），先剥离注释再全文提取
    bodies: dict[str, str] = {}
    for m in re.finditer(r"export interface (Sse\w+)\s*\{([^{}]*?)\}", src):
        bodies[m.group(1)] = m.group(2)
    for m in re.finditer(r"export interface (Sse\w+)\s*\{(.*?)^\}", src, re.S | re.M):
        bodies.setdefault(m.group(1), m.group(2))
    literals: set[str] = set()
    fields: dict[str, set[str]] = {}
    for name, body in bodies.items():
        type_m = re.search(r"\btype:\s*'(\w+)'", body)
        if not type_m:
            continue  # 非事件接口（如 SseDonePayload 负载定义）
        literals.add(type_m.group(1))
        clean = re.sub(r"/\*\*.*?\*/|/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
        keys = {
            m.group(1)
            for m in re.finditer(r"\b(\w+)\??\s*:", clean)
            if m.group(1) != "type"
        }
        fields[type_m.group(1)] = keys
    return members, literals, fields


def test_event_name_parity():
    """事件名集合对拍：后端常量 ↔ 前端联合类型字面量（豁免清单登记制）。"""
    members, literals, _ = _parse_frontend_types()
    backend = _backend_event_names()

    expected_frontend = (backend - _BACKEND_ONLY) | _FRONTEND_ONLY
    missing = expected_frontend - literals
    extra = literals - expected_frontend
    assert not missing, f"前端 SseEvent 缺事件（后端已定义）：{sorted(missing)}"
    assert not extra, f"前端 SseEvent 多出未登记事件：{sorted(extra)}"
    # 联合成员数与字面量数一致，防联合引用了无 type 字面量的接口
    assert len(members) == len(literals)


def test_key_fields_parity():
    """关键字段对拍：对照表每个字段必须出现在前端对应事件接口声明中。"""
    _, literals, fields = _parse_frontend_types()
    assert set(_KEY_FIELDS) <= literals, (
        f"对照表含前端未声明的事件：{sorted(set(_KEY_FIELDS) - literals)}"
    )
    drift = {
        ev: sorted(required - fields.get(ev, set()))
        for ev, required in _KEY_FIELDS.items()
        if required - fields.get(ev, set())
    }
    assert not drift, f"前端接口缺关键字段（对照表对拍失败）：{drift}"


@pytest.mark.parametrize("event_name", sorted(_KEY_FIELDS))
def test_backend_only_events_not_in_key_fields(event_name):
    """对照表自洽：豁免事件不得出现在字段对照表（豁免即不消费其载荷）。"""
    assert event_name not in _BACKEND_ONLY
