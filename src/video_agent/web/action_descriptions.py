"""Studio 操作的中文描述表（从 action_executor.py 拆出，批次5 文件瘦身）。

供前端「已执行操作」卡片展示具体做了什么。纯展示文案逻辑，无副作用。
"""
from typing import Any, Callable, Dict, Optional


def describe_action(
    action: Dict[str, Any],
    find_draft: Optional[Callable[[str, str], Any]] = None,
) -> str:
    """生成操作的中文简述（尽量解析出真实名称）。

    find_draft: 可选的草稿查找函数（draft_id, draft_type) -> (group, draft) | None，
    用于把 draft_id 解析为草稿真实 label；不传则退回显示 ID。
    """
    name = str(action.get("action") or action.get("type") or "").strip()
    title = str(action.get("title") or "").strip()
    label = str(action.get("label") or "").strip()
    doc = str(action.get("name") or action.get("doc_name") or action.get("key") or "").strip()
    patch = action.get("patch") if isinstance(action.get("patch"), dict) else {}
    # 更新类操作：优先从状态里解析出草稿真实 label
    draft_id = str(action.get("draft_id") or "")
    if draft_id and not label and find_draft is not None:
        found = find_draft(draft_id, str(action.get("draft_type") or ""))
        if found:
            label = str(found[1].get("label") or "")
    if name in ("add_group", "add_keyElement", "add_shot", "add_audio"):
        kind = {"keyElement": "关键元素", "shot": "分镜", "audio": "音频"}.get(
            str(action.get("group_type") or action.get("type_hint") or ""), "分组"
        )
        return f"新建{kind}分组「{title or '未命名'}」"
    if name in ("update_draft", "patch_draft", "update_current_draft", "set_prompt", "confirm_draft", "confirm_current_draft"):
        target = label or draft_id or "当前草稿"
        fields = list(patch.keys()) if patch else []
        if "prompt" in fields or name == "set_prompt":
            return f"更新草稿「{target}」的提示词"
        if fields:
            return f"更新草稿「{target}」（{'/'.join(fields[:3])}）"
        return f"确认草稿「{target}」"
    if name in ("update_group", "patch_group"):
        return f"更新分组「{title or action.get('group_id', '')}」"
    if name == "add_draft":
        return f"新增草稿「{label or '未命名'}」"
    if name in ("delete_draft", "remove_draft"):
        return f"删除草稿 {action.get('draft_id', '')}"
    if name in ("clear_media", "delete_media", "remove_media"):
        target = str(action.get("draft_id") or "").strip()
        found = find_draft(target, str(action.get("draft_type") or "")) if (target and find_draft) else None
        t_label = str(found[1].get("label") or "") if found else target
        return f"清空草稿「{t_label or '当前草稿'}」内的媒体"
    if name in ("delete_group", "remove_group"):
        return f"删除分组 {action.get('group_id', '')}"
    if name in ("write_document", "write_doc", "save_document"):
        return f"写入文档「{doc or '未命名'}」"
    if name == "bind_asset":
        return f"绑定素材「{str(action.get('name') or action.get('url', ''))[:24]}」"
    if name in ("insert_chat_media", "send_to_chat", "add_to_chat_input"):
        return "插入故事板媒体到对话输入框"
    if name in ("generate_image", "batch_generate_image", "gen_image"):
        return f"发起生图（{str(action.get('target', ''))}）"
    if name == "select_draft":
        return "选中草稿"
    return f"执行操作 {name}"
