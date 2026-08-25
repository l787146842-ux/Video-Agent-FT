"""SSE 契约对拍（任务 #3 E-1；任务 #4 契约生成化）：后端 sse_events.py ↔ 前端契约面。

防漂移方案选型（任务 #4 后）：帧接口与字段已随 sidecar 生成到
api.generated.ts（字段锚点改解析生成物，漂移由 gen --check 同闸兼管）；
index.ts 仅保留 SseEvent 联合与视图态收窄（成员锚点仍解析 index.ts）。
仅对"关键字段"维护对照表（_KEY_FIELDS 钉事件顶层字段；
_SUBMODEL_KEY_FIELDS 钉 done/replay 载荷子模型子项字段，任务 #12），
字段增删只需改一处。

同步规则（改动契约时的必做动作）：
1. 后端 sse_events.py 增/删事件常量 → TS_EVENT_FRAMES 登记后重跑生成器，
   前端联合经 index.ts 收窄层同步，本测试事件名对拍失败即提醒；
2. 事件的关键载荷字段变化 → 更新本文件 _KEY_FIELDS 对照表；
3. 豁免清单须有明确理由（见 _BACKEND_ONLY / _FRONTEND_ONLY 注释），
   新增豁免必须在此登记，禁止默默绕过。
"""
import re
from pathlib import Path

import pytest

from src.video_agent.core import sse_events

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TYPES_TS = _REPO_ROOT / "src" / "web" / "types" / "index.ts"
_GEN_TS = _REPO_ROOT / "src" / "web" / "types" / "api.generated.ts"

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

# 关键子项字段对照表（任务 #12）：载荷子模型名 → 生成物接口必须声明的字段。
# 钉 _KEY_FIELDS 够不到的嵌套载荷面（done.payload 全家桶 / replay 首帧）；
# 后端子模型字段变更未重跑生成器时，与后端 model_fields 全等对拍即红。
_SUBMODEL_KEY_FIELDS = {
    "SseDonePayload": {"chat_inserts", "confirmation_options", "suggested_actions"},
    "SseDoneChatInsert": {"kind", "url", "name", "thumb"},
    "SseDoneConfirmationOption": {"label", "description", "group", "value"},
    "SseDoneSuggestedAction": {"kind", "label", "value"},
    "SseStoppedInflightItem": {"task_id", "media_type", "model", "draft_id", "summary"},
    "AgentTaskReplayPayload": {"status", "tools", "snapshot", "done_payload", "stopped_payload"},
}


def _backend_event_names() -> set[str]:
    """后端权威事件名集合（常量值即契约，不解析字符串避免两处维护）。"""
    return {
        getattr(sse_events, name)
        for name in sse_events.__all__
        if name.startswith("SSE_")
    }


def _parse_frontend_types() -> tuple[set[str], set[str], dict[str, set[str]]]:
    """解析前端契约面：返回 (联合成员接口名, 事件字面量集合, 接口字段表)。

    任务 #4 后双锚点：联合成员解析 index.ts（收窄层）；帧接口/type 字面量/
    字段解析生成物 api.generated.ts（只扫 Sse 前缀接口，避免误吞业务接口；
    接口体取到独占一行的闭括号，兼容嵌套内联对象）。
    """
    union_src = _TYPES_TS.read_text(encoding="utf-8")
    union_m = re.search(r"export type SseEvent\s*=\s*(.*?);", union_src, re.S)
    assert union_m, "types/index.ts 缺少 SseEvent 联合类型定义"
    members = set(re.findall(r"\|\s*(\w+)", union_m.group(1)))
    assert members, "SseEvent 联合类型成员为空"

    src = _GEN_TS.read_text(encoding="utf-8")
    # 联合成员必须全部有生成帧支撑（防联合引用孤儿接口）
    orphan = {m for m in members if f"export interface {m}" not in src}
    assert not orphan, f"联合成员无生成帧：{sorted(orphan)}"

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


def _parse_generated_interface_fields() -> dict[str, set[str]]:
    """解析生成物全部 Sse*/AgentTask* 接口字段表（含无 type 判别的载荷子模型）。

    与 _parse_frontend_types 同双通道提取（单行/多行），但不要求 type 字面量，
    故 SseDonePayload/AgentTaskReplayPayload 等子模型也纳入对拍。
    """
    src = _GEN_TS.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for m in re.finditer(
            r"export interface ((?:Sse|AgentTask)\w+)\s*\{([^{}]*?)\}", src):
        bodies[m.group(1)] = m.group(2)
    for m in re.finditer(
            r"export interface ((?:Sse|AgentTask)\w+)\s*\{(.*?)^\}",
            src, re.S | re.M):
        bodies.setdefault(m.group(1), m.group(2))
    fields: dict[str, set[str]] = {}
    for name, body in bodies.items():
        clean = re.sub(r"/\*\*.*?\*/|/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
        fields[name] = {
            m.group(1)
            for m in re.finditer(r"^\s*(\w+)\??\s*:", clean, flags=re.M)
        }
    return fields


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


def test_submodel_key_fields_parity():
    """关键子项字段对拍（任务 #12）：对照表 ↔ 生成物子模型 ↔ 后端 Pydantic 模型。

    双保险：对照表字段必须出现在生成物接口；且生成物字段集与后端模型
    model_fields 全等（事实源 sse_events.py）——后端子项字段变更后要么
    重跑 gen_api_types.py，要么本对拍红。
    """
    fields = _parse_generated_interface_fields()
    unknown = sorted(set(_SUBMODEL_KEY_FIELDS) - set(fields))
    assert not unknown, f"生成物缺对照表登记的子模型：{unknown}"
    drift = {
        name: sorted(required - fields[name])
        for name, required in _SUBMODEL_KEY_FIELDS.items()
        if required - fields[name]
    }
    assert not drift, f"生成物子模型缺关键子项字段：{drift}"
    for name in _SUBMODEL_KEY_FIELDS:
        backend = set(getattr(sse_events, name).model_fields)
        assert fields[name] == backend, (
            f"{name} 生成物字段集与后端模型不一致："
            f"多出={sorted(fields[name] - backend)} "
            f"缺失={sorted(backend - fields[name])}"
        )


@pytest.mark.parametrize("event_name", sorted(_KEY_FIELDS))
def test_backend_only_events_not_in_key_fields(event_name):
    """对照表自洽：豁免事件不得出现在字段对照表（豁免即不消费其载荷）。"""
    assert event_name not in _BACKEND_ONLY
