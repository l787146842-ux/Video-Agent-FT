# -*- coding: utf-8 -*-
"""具名事件卡映射表（Skill 流程跑通修复批 2/3 · 插播报；批 6 · A3 兑现）。

工具成功 → 用户可读里程碑卡名的唯一映射（触发时刻写死，逐卡唯一落点，
对照《Skill流程跑通修复计划书》§四 批 2 表）：

- 规格已完成：document_write 成功且文档名命中规格（建立或更新都发，V4-2）；
- 剧本分析已完成：script_analysis_report 落账（detail_md 携报告全文挂卡折叠，
  不进模型上下文防膨胀——对齐批 2026-09-08，成果正文归模型浓缩交代）；
- 故事板已更新：storyboard_create_group/add_draft/patch_draft 任一成功；
- 资产已注册（M8 预留位，批 6 兑现）：keyElement 组创建成功——
  一元素一组形态下即"元素资产进入注册表"；
- 素材已完成：image_generate 本批返回（批级，随调用次数逐批发）；
- 时间线已更新：generate_video 成功；
- 信息搜索完成：读类工具动作完成（只进时间线，不进模型上下文防逐轮膨胀）。

Skill 已加载卡沿用开场既有 emit 点（chat_opening notes）；素材变更已同步
卡在轮始播报（planner 消费 REST 落库时记的 media_synced 流事件）。

本表独立成模块的原因：fc_tool_runner 受 provider 注入字面量门禁约束
（调度器不得硬编码 provider 工具名，check_fc_tool_name_literals）；
本表是 UI 命名策略而非注入分派，合法持有工具名清单（同 describe_fc_tool）。
"""
from typing import Any, Dict, List, Tuple

from src.video_agent.core import prompt_gates

# 读类工具（「先查再说」动作）→ 信息搜索完成卡；
# 与 fc_tool_runner 的 ACTIONS_APPLIED 读类排除名单同源语义
READ_CARD_TOOLS = (
    "read_skill", "read_draft", "read_uploaded_doc", "read_project_doc",
    "read_state_group", "view_storyboard_media",
)


def product_event_card(
    name: str, args: Dict[str, Any], image_count: int,
) -> List[Tuple[str, str, bool, str]]:
    """工具成功 → [(卡名, 明细, 是否进模型上下文, 折叠全文md)]；无卡工具返回空表。

    批 6 起支持一动作多卡（如 keyElement 建组 = 资产已注册 + 故事板已更新）；
    第 4 位 detail_md = 事件卡折叠区全文（ 对齐批 2026-09-08：分析成果
    全文挂卡不进正文，to_ctx=False 防上下文膨胀）。"""
    if name == "script_analysis_report":
        doc_name = str(args.get("doc_name") or "").strip()
        summary = str(args.get("summary") or "").strip()
        report = str(args.get("report_markdown") or "").strip()
        lines = [
            f"## 剧本分析《{doc_name}》" if doc_name else "## 剧本分析",
            f"**一句话总结**：{summary}" if summary else "",
            report,
        ]
        detail_md = "\n".join(ln for ln in lines if ln)
        return [("剧本分析已完成", summary, False, detail_md)]
    if name in ("document_write", "write_document"):
        doc_name = str(args.get("name") or args.get("key") or "").strip()
        if doc_name and prompt_gates.is_spec_doc_name(doc_name):
            return [("规格已完成", doc_name, True, "")]
        return []
    if name == "storyboard_create_group":
        title = str(args.get("title") or "").strip()
        cards: List[Tuple[str, str, bool, str]] = []
        if str(args.get("group_type") or "").strip() == "keyElement" and title:
            cards.append(("资产已注册", title, True, ""))
        cards.append(("故事板已更新", title, True, ""))
        return cards
    if name == "storyboard_add_draft":
        draft = args.get("draft") if isinstance(args.get("draft"), dict) else {}
        return [("故事板已更新", str(draft.get("label") or "").strip(), True, "")]
    if name == "storyboard_patch_draft":
        return [("故事板已更新", str(args.get("draft_id") or "").strip(), True, "")]
    if name == "image_generate":
        return [("素材已完成", f"{image_count} 张图片" if image_count else "", True, "")]
    if name == "generate_video":
        return [("时间线已更新", "", True, "")]
    if name in READ_CARD_TOOLS:
        return [("信息搜索完成", "", False, "")]
    return []
