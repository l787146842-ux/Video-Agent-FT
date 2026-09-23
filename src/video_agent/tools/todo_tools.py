# -*- coding: utf-8 -*-
"""任务进度清单（2026-09-23 批8，用户裁决：**完全照抄 dsh `todo_write`**）。

## 事故根因（本工具要治什么）

2222/3333 实跑取证：子代理**首个规划响应推理 12867 字（占全会话 48.2%）**，
之后 seq=75~129 推理≈0 字纯批量执行 —— 典型的「一次性想完全部再动手」。
平台对「分批」只有**散文劝告**（`prompts/planner/subagent.md:70`），
实跑只被吸收一半：模型照做了「每批 3-5 个工具调用」，
而 `随想随写`/`预先起草全部` 两个短语**零命中**。

dsh 的对照做法（`packages/todo/tool-todo/src/index.ts:45-78`）：**不靠劝，
给模型一个工具把进度状态外在化** —— 模型必须先列步骤、干活时改状态、
做完立刻标完成，推理天然被切成「一步一更新」。

## 本实现与 dsh 的逐项对照（用户要求完全照抄）

| 维度 | dsh `todo_write` | 本实现 |
|---|---|---|
| 工具名 | `todo_write` | `todo_write`（照抄） |
| 入参名 | `todos` | `todos`（照抄） |
| 条目结构 | `{content, status}`，`additionalProperties: false` | 同（照抄；多余键拒收） |
| 状态枚举 | 仅 `pending`/`in_progress`/`completed`，非法即拒收 | 同（照抄） |
| 覆盖语义 | 整表覆盖（`no per-item edits`） | 同（照抄） |
| 并行策略 | `allowParallelInProgress` 部署开关，**同时改文案与校验** | 取 **true**：文案允许并行，校验不触发（用户裁决「能并行就并行，不能并行就排队」） |
| 作用域 | 每会话一份 | **每会话一份**（见下「作用域」） |
| 同状态上限 | `allowParallel=false` 时强制「至多一个 in_progress」 | 取 true ⇒ 不强制（与 dsh true 档一致） |
| 描述文案 | dsh 原句 | **中文照翻**（用户选「乙」：照翻 + 给本工具在
  `check_tool_descriptions.py` 登记豁免，因 dsh 原句含 `do not batch completions`
  而本仓门禁拦中文否定词） |

## 作用域（修一处实现缺陷）

dsh 的清单是**每会话一份**。此前本平台实现把它存在项目级 `state_dict`，
而**主代理与子代理共享同一 StateManager** ⇒ 两边清单**互相覆盖**
（子代理一列清单就把主代理那份顶掉）。本实现改存**会话作用域**
（`svc.bound_conversation_id` → `activeConversationId` → `conv-main`，
与 `conversation_ops.target_chat_messages` / `session_log._resolve_cid` 同口径），
主代理与其子代理各自一份、互不干扰。

## 边界（不撞「不加机械闸」）

本工具只做**模型自用记账**：写自己的清单、读自己的清单。
它不拦任何其它工具的调用、不校验产物、不推进阶段——
`allowParallelInProgress=true` 档下连清单自身的状态都不强制。
"""
from typing import Any, Dict, List, Literal, Type

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.video_agent.tools.base import BaseTool, ToolResult
# 模块级导入（func_imports 闸：合法函数内 import 须登记豁免，本模块无此需要）
from src.video_agent.state import conversation_ops as conv_ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.prompts import load_prompt_section

# 合法状态闭集（与 dsh `STATUSES` 逐字同集）
STATUSES = ("pending", "in_progress", "completed")

# 并行策略档位（与 dsh `allowParallelInProgress` 同义）。
# 本平台取 True（用户裁决：「模型有这个可以自己编排啊，能并行就并行提高效率啊；
# 不能并行就排队做啊」）——文案允许同时多个 in_progress，且不做上限校验。
# 注：档位与文案必须成对（dsh 注释：本开关**唯一**改变的就是那条指令），
# 故改档位必须同步改 DESCRIPTION 尾部，二者不得各改一半。
ALLOW_PARALLEL_IN_PROGRESS = True

# 单条内容长度上限 / 条数上限（防清单本身膨胀成新的大对象）。
# dsh 侧无此上限（其 schema 只限形状）；本平台因清单会随状态注入回上下文，
# 加上限属本平台的注入预算保护，不改 dsh 的语义。
ITEM_MAX_CHARS = 120
ITEM_MAX_COUNT = 40

# 进度清单在会话对象里的存放键（每会话一份，见模块 docstring「作用域」）
_TODOS_KEY = "todos"


class TodoItem(BaseModel):
    """清单单项（对齐 dsh `TodoItem`：只允许 content/status 两个键）。

    dsh 侧等价约束 = schema 的 `additionalProperties: false` +
    注册表状态枚举校验（`:83-84` 注释逐字：「the shared event's semantics live
    here」）；本处用 pydantic `extra="forbid"` + Literal 表达，同为**拒收**语义。
    """
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        ..., description="这一步做什么（一句话；只放步骤索引，"
        "步骤内容本身以当前阶段 Skill 章节为准）")
    status: Literal["pending", "in_progress", "completed"] = Field(
        ..., description="pending (not started) | in_progress (now) | completed (done).")


class TodoWriteInput(BaseModel):
    """整表覆盖入参：提交的是**完整清单**，不是增量补丁。"""
    todos: List[TodoItem] = Field(
        default_factory=list,
        description="完整清单（整表覆盖，无逐条增删语义）：每步一条。"
        "传空数组 = 清空清单。")


# 工具描述外置（本平台 prompt_literals 闸：进模型上下文的 CJK prose 须外置，
# Rule 6）。文案唯一源 = prompts/shared/todo_write.md；两档文案成对，
# 档位翻转时须同批改该文件（dsh 注释：本开关唯一改变的就是这条指令）。
def _load_description() -> str:
    key = "DESCRIPTION_PARALLEL" if ALLOW_PARALLEL_IN_PROGRESS else "DESCRIPTION_SINGLE"
    text = load_prompt_section("shared/todo_write.md", key)
    if not text:
        logger.warning(
            f"[todo_write] prompts/shared/todo_write.md::{key} 分节缺失，"
            "工具描述为空——请检查外置文案文件")
    return text


_DESCRIPTION = _load_description()


class TodoWriteTool(BaseTool):
    name = "todo_write"
    risk = "low"  # 纯记账：只写模型自己的清单，不改工作台产物
    detail_tier = "output"  # 记账类：仅输出留痕，不展开输入
    description = _DESCRIPTION

    def get_input_schema(self) -> Type[BaseModel]:
        return TodoWriteInput

    async def aexecute(self, params: TodoWriteInput) -> ToolResult:
        svc = StateManager.get_instance()

        # 状态枚举由 schema 的 Literal 拒收（等价 dsh 注册表枚举校验）；
        # 此处只做条数与长度的注入预算保护（清单会随状态注入回上下文）。
        raw_items: List[Dict[str, Any]] = []
        in_progress: List[str] = []
        for it in (params.todos or [])[:ITEM_MAX_COUNT]:
            content = str(getattr(it, "content", "") or "").strip()
            status = str(getattr(it, "status", "") or "").strip().lower()
            if not content:
                continue
            if status == "in_progress":
                in_progress.append(content)
            raw_items.append({
                "content": content[:ITEM_MAX_CHARS],
                "status": status,
            })

        # 并行策略校验（dsh `:107-109` 同款；true 档不触发）
        if not ALLOW_PARALLEL_IN_PROGRESS and len(in_progress) > 1:
            return ToolResult(
                success=False,
                error=(f"invalid todos: at most one task may be in_progress "
                       f"(got {len(in_progress)})"),
                error_code="validation", retryable=False,
            )

        _write_session_todos(svc, raw_items)

        _done = sum(1 for i in raw_items if i["status"] == "completed")
        return ToolResult(success=True, data={
            "count": len(raw_items),
            "completed": _done,
            "in_progress": in_progress,
            "detail": (
                f"清单已更新：共 {len(raw_items)} 步，已完成 {_done} 步"
                + (f"，正在做：{'；'.join(in_progress[:3])}" if in_progress else "")
            ) if raw_items else "清单已清空",
        })


def resolve_session_id(svc: Any) -> str:
    """当前会话 ID（与 conversation_ops.target_chat_messages /
    session_log._resolve_cid 同口径：绑定会话 → 活跃会话 → conv-main）。"""
    cid = str(getattr(svc, "bound_conversation_id", "") or "")
    if cid:
        return cid
    raw = getattr(svc, "_raw_state", None)
    if isinstance(raw, dict):
        return str(raw.get("activeConversationId") or "conv-main")
    return "conv-main"


def _conversation(svc: Any, cid: str) -> Dict[str, Any]:
    """取（必要时建）会话对象。会话缺失时建占位，不阻断记账。"""
    convs = conv_ops.ensure_conversations(svc)
    target = next(
        (c for c in convs if isinstance(c, dict) and c.get("id") == cid), None)
    if target is not None:
        return target
    # 绑定的子会话线程可能尚未登记：建一个占位，保证记账可用
    stub = {"id": cid, "title": cid, "messages": [], "scope": {"kind": "todo-stub"}}
    convs.append(stub)
    logger.debug("[todo_write] 会话 {} 不存在，已建占位承载清单", cid)
    return stub


def _write_session_todos(svc: Any, items: List[Dict[str, Any]]) -> None:
    """整表覆盖写入当前会话的清单（每会话一份，见模块 docstring）。"""
    cid = resolve_session_id(svc)
    conv = _conversation(svc, cid)
    conv[_TODOS_KEY] = items
    svc.save()


def read_session_todos(svc: Any, conversation_id: str = "") -> List[Dict[str, Any]]:
    """读当前（或指定）会话的清单（供尾部注入消费）；无则空列表。"""
    cid = str(conversation_id or "") or resolve_session_id(svc)
    try:
        convs = conv_ops.ensure_conversations(svc)
    except Exception:
        return []
    for c in convs:
        if isinstance(c, dict) and c.get("id") == cid:
            items = c.get(_TODOS_KEY) or []
            return items if isinstance(items, list) else []
    return []


def register_todo_tools():
    """注册进度清单工具（主代理与子代理都持有：记账是两边的共同需求）。"""
    ToolManager.register(TodoWriteTool())
