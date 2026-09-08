"""Studio 操作的中文描述表。

供前端「已执行操作」卡片展示具体做了什么。纯展示文案逻辑，无副作用。
"""
import re
from typing import Any, Callable, Dict, List, Optional

# 描述里的目标名称（「…」）与实体 ID（ke-/sh-/au-…）——聚合时剔除，只留动词+对象类别
_TITLE_RE = re.compile(r"「[^」]*」")
_ID_RE = re.compile(r"\b(?:ke|sh|au|grp|draft)-[A-Za-z0-9-]+")


def describe_action(
    action: Dict[str, Any],
    find_draft: Optional[Callable[[str, str], Any]] = None,
) -> str:
    """生成操作的中文简述（尽量解析出真实名称）。

    find_draft: 可选的草稿查找函数（draft_id, draft_type) -> (group, draft) | None，
    用于把 draft_id 解析为草稿真实 label；不传则退回显示 ID。
    """
    name = str(action.get("action") or action.get("type") or "").strip()
    if name in ("script_analyze",):
        return "解析上传素材并输出一句话总结与关键要点"
    if name in ("storyboard_key_elements",):
        return "拆解关键元素分组（只建结构）"
    if name in ("storyboard_shots",):
        return "拆解分镜分组（只建结构）"
    if name in ("storyboard_audio",):
        return "拆解音频层分组（只建结构）"
    if name in ("write_media_prompt",):
        return "按 Skill 提示词写法分批编写草稿提示词"
    if name in ("audio_generate",):
        return "生成音频规划或绑定用户已上传音频"
    if name in ("video_assembler",):
        return "输出最终成片组装方案（素材清单+时间轴）"
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
    if name in ("generate_video", "batch_generate_video", "gen_video"):
        return f"发起分镜视频生成（{str(action.get('target', ''))}）"
    if name == "select_draft":
        return "选中草稿"
    return f"执行操作 {name}"


def _action_group_key(desc: str) -> str:
    """聚合键：剔除描述里的具体名称/ID，只保留动词+对象类别（如「新建关键元素分组」）"""
    key = _TITLE_RE.sub("", desc)
    key = _ID_RE.sub("", key)
    key = re.sub(r"\s+", "", key)
    return key.strip("：: ") or desc.strip()


# 低信息动作抑制（2026-09-06 对齐批）：机械续读/目录类动作不进聊天
# 动作日志（trace 与审计账本照记，仅展示层折叠）——动作完成卡只讲成果，
# 对齐外部标杆「视频规格已完成」式呈现。键 = _action_group_key 剔名后的形态。
_LOW_INFO_KEYS = frozenset({
    "Skill流程已加载",        # read_skill
    "执行工具list_skills",    # list_skills
    "执行工具get_skill_asset",  # get_skill_asset
})


def aggregate_action_log(logs: List[str]) -> List[str]:
    """粗粒度聚合操作清单（「阶段完成」卡片展示用）。

    用户不需要逐条看到每张卡片：连续同类操作合并为一条，
    如 3 条「新建关键元素分组「X」」→「新建关键元素分组 ×3」。
    仅合并连续的同类项，保持时间顺序；不连续的同类操作分开展示。
    低信息动作（机械续读/目录类）整类折叠不展示。
    """
    texts: List[str] = []
    counts: List[int] = []
    keys: List[str] = []
    for desc in logs:
        d = str(desc or "").strip()
        if not d:
            continue
        key = _action_group_key(d)
        if key in _LOW_INFO_KEYS:
            continue
        if keys and keys[-1] == key:
            counts[-1] += 1
        else:
            keys.append(key)
            counts.append(1)
            texts.append(key)
    return [t if n == 1 else f"{t} ×{n}" for t, n in zip(texts, counts)]
