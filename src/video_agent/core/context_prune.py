"""上下文剪枝：白名单工具的大返回在回喂进 history 前保留头尾、
中段替换为标记行（模型可用 read_* 的 start= 续读兜底）。

职责边界：
- 只剪「回喂进 history 的副本」（fc_feedback.format_tool_results 调用本模块）；
  工具原始返回、state、workspace 产物文件一律不动，前端展示不受影响。
- 写类工具结果不剪——其回喂行由 fc_feedback.digest_projected_tool_results
  管理（结果已投影进状态 JSON），两者职责互补。
- 必须用 Python str 码点切片（len/slice 直接操作 str），禁止 encode 成
  bytes 再切，防 emoji/代理对被劈半产生乱码。
- 配置 tool_result_prune_chars=0 即一键整体关闭（回滚开关）。
"""
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.tracer import AgentTracer

# 剪枝标记行（按工具类分流）：N=省略字符数
# - read_* 类：start=续读起点（对齐 read_* 的 start 协议，有真实续读路径）
PRUNE_MARKER_TEMPLATE = "⟦PRUNE: 中段省略 {n} 字，可用 read_* 工具 start={start} 续读⟧"
# - 生成类（image_generate/generate_video）：结果无续读路径，
#   中性告知按头尾信息继续，防模型误以为可续读而重复生成
PRUNE_MARKER_TEMPLATE_GEN = "⟦PRUNE: 中段省略 {n} 字，按已有头尾信息继续，勿重复生成⟧"
# 标记行近似开销（字符）：净缩短守卫用，防自定义参数下剪后反而更长
PRUNE_MARKER_OVERHEAD = 60

# 最保守白名单（判断点不清晰时宁窄勿宽）：
# - read_* 全文回喂（渐进式披露的「借阅归还」，大返回主源，且有 start 续读兜底）
# - 生成类工具的大 detail 返回；写类工具一律不剪（归 digest 杠杆管）
PRUNE_READ_TOOLS = frozenset({
    "read_skill", "read_project_doc", "read_uploaded_doc", "read_draft", "read_state_group",
})
PRUNE_GENERATION_TOOLS = frozenset({
    "image_generate", "generate_video",
    # 遗留别名：老会话历史中的旧生图工具名，同走生成类剪枝标记（防落入 read_* 可续读误导分支）
    "generate_image",
})
PRUNE_FEEDBACK_TOOLS = PRUNE_READ_TOOLS | PRUNE_GENERATION_TOOLS


def prune_large_text(
    text: str, threshold_chars: int, head_chars: int, tail_chars: int,
    marker_template: str = PRUNE_MARKER_TEMPLATE,
) -> str:
    """超阈值的文本保留头部 head_chars + 尾部 tail_chars，中段替换为标记行。

    纯函数、无副作用：未超阈（或阈值<=0 整体关闭、头尾配额覆盖全文）
    一律原样返回。净缩短守卫：头尾 + 标记行近似开销（约 60 字）已不短于
    原文时同样原样返回，防自定义参数下剪后反而更长。切片直接操作
    Python str 码点，不经 bytes，emoji/代理对不会被劈半。
    """
    if not text or threshold_chars <= 0:
        return text
    head_chars = max(int(head_chars or 0), 0)
    tail_chars = max(int(tail_chars or 0), 0)
    n = len(text)  # str 码点长度（len 直接作用 str）
    if n <= threshold_chars or head_chars + tail_chars >= n:
        return text
    if head_chars + tail_chars + PRUNE_MARKER_OVERHEAD >= n:
        return text  # 净缩短守卫：剪后不短于原文则不剪
    omitted = n - head_chars - tail_chars
    marker = "\n" + marker_template.format(n=omitted, start=head_chars) + "\n"
    return text[:head_chars] + marker + text[n - tail_chars:]  # str 切片，禁 bytes


def _record_prune_event(name: str, before: int, after: int) -> None:
    """剪枝命中记入上下文事件流（降级事件化）；失败仅 log，绝不干扰主链。"""
    try:
        AgentTracer.get_instance().record_context_event(
            "prune", f"{name}: {before}->{after} 字")
    except Exception as e:
        logger.debug(f"[ContextPrune] 事件记录失败（忽略）: {e}")


def prune_tool_feedback(
    name: str, text: str,
    threshold_chars: int = 0, head_chars: int = 0, tail_chars: int = 0,
) -> str:
    """回喂副本剪枝入口：仅白名单工具生效，阈值缺省读 settings。

    标记模板按工具名分叉：read_* 类带 start= 续读提示；生成类无续读
    路径，用中性告知模板（勿重复生成）。三个参数显式传 >0 时覆盖
    settings（测试/特调用）；threshold=0 整体关闭。
    """
    if name not in PRUNE_FEEDBACK_TOOLS or not text:
        return text
    threshold = threshold_chars if threshold_chars > 0 else int(settings.tool_result_prune_chars)
    head = head_chars if threshold_chars > 0 else int(settings.tool_result_prune_head)
    tail = tail_chars if threshold_chars > 0 else int(settings.tool_result_prune_tail)
    template = (PRUNE_MARKER_TEMPLATE_GEN if name in PRUNE_GENERATION_TOOLS
                else PRUNE_MARKER_TEMPLATE)
    pruned = prune_large_text(text, threshold, head, tail, marker_template=template)
    if pruned is not text and len(pruned) < len(text):
        _record_prune_event(name, len(text), len(pruned))
    return pruned
