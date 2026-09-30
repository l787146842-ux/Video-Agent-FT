# -*- coding: utf-8 -*-
"""任务进度清单（2026-09-23 批8；**批13 收窄 + 补齐漏抄项**）。

## 事故根因（本工具要治什么）

2222/3333 实跑取证：子代理**首个规划响应推理 12867 字（占全会话 48.2%）**，
之后 seq=75~129 推理≈0 字纯批量执行 —— 典型的「一次性想完全部再动手」。
平台对「分批」只有**散文劝告**（`prompts/planner/subagent.md` 的
DELEGATION_CONTEXT），实跑只被吸收一半：模型照做了「每批 3-5 个工具调用」，
而当时同在劝告里的「思考也随想随写」半句**零命中**。

> 2026-09-27 用户裁决（7777 取证）：那半句「思考同样分批」及「后果说明」
> 已从 DELEGATION_CONTEXT 与 `skill_runtime.md` 第 6 条**删除**——模型拿到的
> 是有明确结果导向的任务，草稿在思考里一次打完再落盘是正常形态，平台只约束
> **写入分批**。上文 2222/3333 的「零命中」是当时的事实留痕，非现行契约。

dsh 的对照做法（`packages/todo/tool-todo/src/index.ts:45-78`）：**不靠劝，
给模型一个工具把进度状态外在化** —— 模型必须先列步骤、干活时改状态、
做完立刻标完成，推理天然被切成「一步一更新」。

## 2026-09-23 批13（用户裁决）：**仅子代理持有** + 补齐 dsh 漏抄项

批8 原口径是「完全照抄 dsh」，但实跑盘点后收窄了适用范围——
因为**两平台的前提不同**（依据全部来 dsh 原版源码/README，不是推断）：

| 事实 | dsh 原版 | 本平台（批13 前） |
|---|---|---|
| Skill 有无步骤流 | **无**（`dsh-skill` 只给 `<skill_content>` 方法参考） | **16/16 个 Skill 都有 `<planner>` 段**（步骤 + 依赖关系，全文注入） |
| 清单是否回注模型 | **否**：投影 README「模型体验：无」；原版注释「the complete `todo/write` session event is UI and replay state, **not a second model message**」 | **是**（尾部每轮注入，批8 自加） |

⇒ dsh 的 todo 是**流程的唯一来源**（填空缺）；本平台主代理的 todo 是把
同一份步骤**誊第二遍**，与 `<planner>` 构成同一事实源两份（P1 违规）。
故主代理摘除（并入 `CHILD_ONLY_TOOLS`），**子代理保留**——它拿到的是
**单个阶段章节**而非全流程，todo 在那边仍是填空缺（4444 实证：子代理条目
含项目实例信息，如「批次1：程心/AA/曹彬/白Ice/瓦西里A」，不是章节誊本）。
尾部注入随之整段删除（回到 dsh 原版口径）。

**同批补齐 dsh 漏抄项**：原版 `toTodoList` 对空/重复 content 一律 `throw`，
注释原文「the logged snapshot must equal what the model believes it wrote...
**fails loud at the schema boundary instead of silently flattening**」。
批8 只抄了 schema 层形状，漏了这条——空 content 静默 `continue`、重复项照收、
超限/超长静默截断，均为原版点名禁止的 silently flattening。

## 本实现与 dsh 的逐项对照

| 维度 | dsh `todo_write` | 本实现 |
|---|---|---|
| 工具名 | `todo_write` | `todo_write`（照抄） |
| 入参名 | `todos` | `todos`（照抄） |
| 条目结构 | `{content, status}`，`additionalProperties: false` | 同（照抄；多余键拒收） |
| 状态枚举 | 仅 `pending`/`in_progress`/`completed`，非法即拒收 | 同（照抄） |
| 覆盖语义 | 整表覆盖（`no per-item edits`） | 同（照抄） |
| 空/重复 content | **throw**（fail-loud） | **同**（批13 补齐；原先静默吞） |
| 条数/单条长度上限 | 无 | 本平台注入预算保护，**超限拒收**（不静默截断） |
| 并行策略 | `allowParallelInProgress` 部署开关，**同时改文案与校验** | 取 **true**：文案允许并行，校验不触发（用户裁决「能并行就并行，不能并行就排队」） |
| 作用域 | 每会话一份 | **每会话一份**（见下「作用域」） |
| 同状态上限 | `allowParallel=false` 时强制「至多一个 in_progress」 | 取 true ⇒ 不强制（与 dsh true 档一致） |
| **可见面** | 模型侧常驻（dsh 无主/子之分） | **仅子代理**（主代理并入 CHILD_ONLY_TOOLS，批13） |
| **回注模型** | **不回注** | **不回注**（批13 删尾部注入，回到原版） |
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
（批13 新加的拒收只作用于**本次提交自身的形状**，不涉及其它工具/产物/阶段。）
"""
from typing import Any, Dict, List, Literal, Optional, Type

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.video_agent.tools.base import BaseTool, ToolResult, save_or_conflict
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

        # 状态枚举由 schema 的 Literal 拒收（等价 dsh 注册表枚举校验）。
        #
        # 2026-09-23 批13（对照 dsh 原版补齐漏抄项 + 停掉静默吞）：
        # dsh `toTodoList`（lib/index.js:45-62）对空/重复 content **一律 throw**，
        # 原版注释写明理由：「the logged snapshot must equal what the model
        # believes it wrote... fails loud at the schema boundary instead of
        # silently flattening」。旧实现空 content 是 `continue` 静默跳过、
        # 重复项照收——恰好犯了原版点名禁止的 silently flattening：
        # 本清单的用途就是「模型以此核对进度」，账本被静默改写后模型会
        # 按**自己以为的**清单继续，与落盘事实分叉（P3 状态即数据：账本
        # 必须等于模型所写）。故改为逐项 fail-loud，与 dsh 同语义。
        raw_items: List[Dict[str, Any]] = []
        in_progress: List[str] = []
        _seen: set = set()
        # 条数上限仍属本平台注入预算保护（dsh 无此上限），**超限拒收**而非
        # 静默截断——同「不留静默 flatten」口径（截断会让模型以为写进去了）。
        if len(params.todos or []) > ITEM_MAX_COUNT:
            return ToolResult(
                success=False,
                error=(f"invalid todos: at most {ITEM_MAX_COUNT} items "
                       f"(got {len(params.todos or [])})"),
                error_code="validation", retryable=False,
            )
        for it in (params.todos or []):
            content = str(getattr(it, "content", "") or "").strip()
            status = str(getattr(it, "status", "") or "").strip().lower()
            if not content:
                return ToolResult(
                    success=False,
                    error="invalid todo: `content` must be a non-empty string",
                    error_code="validation", retryable=False,
                )
            if content in _seen:
                return ToolResult(
                    success=False,
                    error=f"invalid todos: duplicate content {content!r}",
                    error_code="validation", retryable=False,
                )
            _seen.add(content)
            # 单条长度上限同属本平台注入预算保护，**超限拒收**而非静默截断
            # （截断后落盘内容 ≠ 模型所写，同「不许 silently flatten」口径）。
            if len(content) > ITEM_MAX_CHARS:
                return ToolResult(
                    success=False,
                    error=(f"invalid todo: `content` exceeds {ITEM_MAX_CHARS} "
                           f"chars (got {len(content)})"),
                    error_code="validation", retryable=False,
                )
            if status == "in_progress":
                in_progress.append(content)
            raw_items.append({
                "content": content,
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

        _conflict = _write_session_todos(svc, raw_items)
        if _conflict is not None:
            return _conflict

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


def _write_session_todos(svc: Any, items: List[Dict[str, Any]]) -> Optional[ToolResult]:
    """整表覆盖写入当前会话的清单（每会话一份，见模块 docstring）。

    返回 None = 落盘成功；返回 ToolResult = 落盘被版本闸放弃（事故
    9999/2026-09-27 动作二②：不得静默回「执行成功」，调用方须原样上抛）。
    """
    cid = resolve_session_id(svc)
    conv = _conversation(svc, cid)
    conv[_TODOS_KEY] = items
    return save_or_conflict(svc)


def read_session_todos(svc: Any, conversation_id: str = "") -> List[Dict[str, Any]]:
    """读当前（或指定）会话的清单；无则空列表。

    **消费方现状（批13 如实登记，不留隐瞒）**：批8 的唯一生产消费方是
    `prompt_builder.build_todo_note` 的尾部注入，该注入已随批13 删除；
    故本函数当前**仅由测试消费**（整表覆盖/会话隔离语义的断言入口）。
    保留理由：它是本模块账本读取的**单一入口**——测试与将来可能的 UI 消费
    都走这里，而不是各自去扫 `_raw_state["conversations"][n]["todos"]`
    （那会让内部结构成为多份事实源，P1）。dsh 侧对应消费方是 `todos`
    会话投影 + `TodoPanel`（本平台暂无该 UI，属「照抄未抄全」的已知缺口）。
    """
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
    """注册进度清单工具。

    批13 起本工具**仅子代理可见**（并入 `subagent.CHILD_ONLY_TOOLS`）：
    主代理的流程事实源是 Skill `<planner>` 段，todo 在那里只是誊第二遍；
    子代理拿到的是单个阶段章节，todo 仍是填空缺。注册本身不分主/子
    （可见性由 `planner._compute_excluded_tools` 按 depth 裁剪）。
    """
    ToolManager.register(TodoWriteTool())
