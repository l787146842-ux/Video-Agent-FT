"""
Token 预算管理 — 估算 token 并自动截断历史消息。

估算规则：
- 优先使用 tiktoken（可选依赖，OpenAI 系精确估算）
- 未安装时回退启发式：中文 ~1.5 字/token，英文 ~4 字符/token

在 Planner 构建 messages 时：若估算超限（模型上下文窗口 * token_budget_ratio），
自动截断历史消息（保留最近 N 条 + 首条 system）；首条 system 自身超预算时，
可通过 system_degrader 降级重建（第二道保险丝）。
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.ports import provider_config_port
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.utils.paths import DATA_DIR

# tiktoken 为可选依赖：装了走精确估算，没装回退启发式（功能不中断）
try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # ImportError 或离线环境下 encoding 数据不可用
    _ENC = None

# 模型上下文窗口表外置于 data/model_context_windows.json（子串 → 窗口大小）。
# 匹配语义：子串先到先得，键序即优先级（与原硬编码表一致）；
# 未命中回落全局 CONTEXT_WINDOW_SIZE 并打 warning（不再静默兜底）。
_CONTEXT_WINDOWS_FILE = DATA_DIR / "model_context_windows.json"
_MODEL_CONTEXT_WINDOWS: Optional[Dict[str, int]] = None
_WARNED_MODELS: Set[str] = set()


def _load_context_windows() -> Dict[str, int]:
    """懒加载并缓存窗口表；文件缺失/损坏时按空表降级。
    加载警告只在首次加载失败时打一次（结果已缓存，后续查表不再触发）；
    模型未收录的警告另在 context_window_for_model 按模型名去重。"""
    global _MODEL_CONTEXT_WINDOWS
    if _MODEL_CONTEXT_WINDOWS is None:
        try:
            data = json.loads(_CONTEXT_WINDOWS_FILE.read_text(encoding="utf-8"))
            _MODEL_CONTEXT_WINDOWS = {str(k): int(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"[TokenBudget] 模型上下文窗口表加载失败，按空表降级: {e}")
            _MODEL_CONTEXT_WINDOWS = {}
    return _MODEL_CONTEXT_WINDOWS


def context_window_for_model(model: str, provider_id: str = "") -> int:
    """按模型名查上下文窗口；未收录的模型回落 settings.context_window_size。

    ：供应商元数据（api_providers.json 的模型条目 context_window）优先，
    data/model_context_windows.json 子串表仅作兜底（同族不同型号窗口可表达，
    不因表过期而失真）。"""
    m = (model or "").lower()
    if provider_id:
        try:
            cfg = provider_config_port().get_provider_config(provider_id) or {}
            for entry in (cfg.get("chat_models_meta") or []):
                if isinstance(entry, dict) and str(entry.get("model") or "").lower() == m:
                    win = int(entry.get("context_window") or 0)
                    if win > 0:
                        return win
        except Exception:
            pass  # 元数据不可用：回落查表（已日志化的降级路径）
    for key, window in _load_context_windows().items():
        if key in m:
            return window
    if m and m not in _WARNED_MODELS:
        _WARNED_MODELS.add(m)
        logger.warning(
            f"[TokenBudget] 模型 {model!r} 未收录于 model_context_windows.json，"
            f"回落保守窗口 {settings.context_window_size}"
        )
    return settings.context_window_size


# 模型输出上限查表（子串 → 单次输出上限 max_tokens 封顶值）下沉
# utils/model_limits（跨切面原语：adapters 400 钳制分支同用，宪法 §六；
# adapters 禁依赖 core 具体实现）。此处 re-export 保持原导入路径稳定。
from src.video_agent.utils.model_limits import output_limit_for_model  # noqa: F401


def estimate_tokens(text: str) -> int:
    """
    估算 token 数量。
    tiktoken 可用时精确估算（cl100k_base，对中文同样有效）；
    否则启发式：中文字符按 1.5 字/token，其他按 4 字符/token。
    """
    if not text:
        return 0
    if _ENC is not None:
        return len(_ENC.encode(text)) + 1
    # 统计中文字符数
    cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
    other_count = len(text) - cjk_count
    # 中文 1.5 字/token，英文 4 字符/token
    return int(cjk_count / 1.5 + other_count / 4) + 1


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # 多模态 content parts
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    # vision token 计入预算；固定成本取 settings.image_token_estimate
                    total += settings.image_token_estimate
        # 每条消息的 role/metadata 开销约 4 token
        total += 4
    return total


def _record_context_event(kind: str, detail: str) -> None:
    """截断/降级命中记入 tracer 上下文事件流；
    失败仅 log，绝不干扰截断主链（截断本身是保底路径）。"""
    try:
        AgentTracer.get_instance().record_context_event(kind, detail)
    except Exception as e:
        logger.debug(f"[TokenBudget] context event 记录失败（忽略）: {e}")


def _is_real_user_msg(msg: Dict[str, Any]) -> bool:
    """判定 user 消息是否为用户真实输入（与系统合成的回喂/注入相对）。

 ：截断按「轮组」原子删除——轮组 = 真实用户消息 + 其后的
    assistant/（系统）回喂，延续到下一条真实用户消息为止。FC 轨
    assistant(tool_calls) 与随后的（系统）回喂是配对消息，拆半边会被供应商 400。
    """
    if msg.get("role") != "user":
        return False
    content = msg.get("content", "")
    if isinstance(content, list):
        return True  # 多模态 content parts = 真实用户消息
    text = str(content)
    if text.startswith("（系统") or text.startswith("（任务执行期间收到您的指令"):
        return False
    return True


def window_recent_turns(
    messages: List[Dict[str, Any]],
    max_user_turns: int = 10,
) -> List[Dict[str, Any]]:
    """聊天入口历史窗口（统一管线入口）。

    取最近 max_user_turns 个**真实用户轮**（含各自后续回喂），轮组原子
    不劈半——条数硬切会从 assistant/回喂半截开刀（供应商 400 风险），
    且把系统合成回喂也计入窗口稀释真实上下文。窗口语义单一事实源 =
    本函数（前端 CHAT_HISTORY_WINDOW 仅作 UI 提示对齐）。"""
    if max_user_turns <= 0 or not messages:
        return list(messages)
    turns = 0
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if _is_real_user_msg(messages[i]):
            turns += 1
            if turns >= max_user_turns:
                start = i
                break
    return messages[start:]


def truncate_messages(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    keep_recent: int = 4,
    system_degrader: Optional[Callable[[str], str]] = None,
) -> List[Dict[str, Any]]:
    """
    截断消息列表以适应 token 预算。

    策略：
    - 保留首条消息（通常是 system prompt）
    - 保留最近 keep_recent 条消息
    - 从中间按「轮组」整组删除最早的消息，直到估算 token 数 <= max_tokens；
      轮组 = 一条消息 + 紧随其后的合成回喂消息（FC 轨
      assistant(tool_calls) 与（系统）回喂配对完整，拆半边会被供应商 400）
    - 保险丝：删无可删仍超预算且首条为 system 时，调用 system_degrader
      降级重建 system 段（如状态 JSON 只留组标题/计数），避免超限请求发出

    返回截断后的消息列表（不修改原列表）。
    实现注：每条消息的 token 只估算一次，删除时用增量减法维护总量，
    避免旧版 while 循环里每删一条都全量重估的 O(n²) 开销。
    """
    if not messages:
        return messages

    per_msg_tokens = [estimate_messages_tokens([m]) for m in messages]
    current_tokens = sum(per_msg_tokens)
    if current_tokens <= max_tokens:
        return messages

    # 需要截断
    result = list(messages)
    token_list = list(per_msg_tokens)
    total = current_tokens
    # 保护边界：首条 + 最近 keep_recent 条
    min_keep = 1 + min(keep_recent, len(result) - 1)

    while total > max_tokens and len(result) > min_keep:
        # 保护起点：最近 keep_recent 条不得删除
        protect_start = len(result) - min(keep_recent, len(result) - 1)
        if protect_start <= 1:
            break
        # 轮组边界：从索引 1 起，到下一条真实用户消息（不含）或保护起点为止
        g_end = 2
        while g_end < protect_start and not _is_real_user_msg(result[g_end]):
            g_end += 1
        del_end = min(g_end, protect_start)
        if del_end <= 1:
            break
        for _ in range(del_end - 1):
            removed = result.pop(1)
            total -= token_list.pop(1)
            preview = str(removed.get("content", ""))[:40]
            logger.debug(f"[TokenBudget] 截断历史消息: {preview}...")

    if current_tokens > max_tokens:
        logger.info(
            f"[TokenBudget] 消息截断: {current_tokens} -> {total} tokens "
            f"({len(messages)} -> {len(result)} 条)"
        )
        if len(result) < len(messages):
            _record_context_event(
                "truncate",
                f"轮组截断 {current_tokens}->{total} tokens，"
                f"{len(messages)}->{len(result)} 条（保留首条+最近 {keep_recent} 条）",
            )

    # 第二道保险丝：历史已删到保护边界仍超预算 → 首条 system 自身过大
    # （状态 JSON 大 + Skill 全文注入的场景），用降级器重建 system 段
    if total > max_tokens and result and result[0].get("role") == "system" and system_degrader is not None:
        degraded = system_degrader(result[0].get("content") or "")
        if degraded and degraded != result[0].get("content"):
            result[0] = {**result[0], "content": degraded}
            new_total = estimate_messages_tokens(result)
            logger.warning(
                f"[TokenBudget] system 段超预算，已降级重建: {total} -> {new_total} tokens "
                f"(预算 {max_tokens})"
            )
            _record_context_event(
                "degrade",
                f"system 段降级重建 {total}->{new_total} tokens（预算 {max_tokens}）",
            )
            total = new_total
    if total > max_tokens:
        logger.warning(
            f"[TokenBudget] 截断后仍超预算: {total} > {max_tokens} tokens，"
            f"请求可能被供应商拒绝（请考虑缩短 Skill 全文或清理草稿）"
        )
    return result
