"""
Mock LLM 回复生成器 — 仅在用户显式选择 mock 供应商时使用。

从 routes/agent.py 抽离，保持路由层精简。
分支顺序：修改/优化 先于 拆解，避免「修改分镜」被误路由到拆解分支。
"""


def mock_llm_reply(user_text: str, context: str) -> str:
    """
    根据用户消息关键词生成模拟回复 + studio-actions 块。

    Args:
        user_text: 用户消息文本
        context: 当前工作台状态 JSON（用于统计信息）

    Returns:
        模拟的 LLM 回复（含 studio-actions 块）
    """
    if any(kw in user_text for kw in ["确认", "通过", "定稿", "锁定", "采用"]):
        reply = "好的，已将当前草稿标记为「已确认」。后续生成任务将优先使用已确认的版本。"
        actions_block = '```studio-actions\n[{"action":"confirm_draft","draft_type":"current","draft_id":"current"}]\n```'
    elif any(kw in user_text for kw in ["修改", "调整", "优化", "改写", "提示词"]):
        reply = (
            "已根据你的意见优化了提示词，增强了画面细节和电影感。"
            "新版本强调了光影层次、材质纹理和镜头语言。"
        )
        actions_block = '```studio-actions\n[{"action":"update_draft","draft_type":"current","draft_id":"current","patch":{"tag":"已优化","prompt":"电影级光影，超高细节，8K 分辨率，赛博朋克现实主义，体积光，景深虚化"}}]\n```'
    elif any(kw in user_text for kw in ["拆解", "解析", "拆分", "分镜", "上传", "文档", "已上传并绑定素材"]):
        reply = (
            "已根据你提供的素材拆解出关键元素和分镜，请查看左侧故事板。"
            "每个分组都带有可执行的生成提示词，你可以点击生成图片。"
        )
        actions_block = '```studio-actions\n[{"action":"add_group","group_type":"keyElement","title":"关键元素：核心视觉设定","desc":"从素材中提取的核心视觉元素","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"电影级概念图，超高细节，8K 分辨率，体积光，景深虚化"}},{"action":"add_group","group_type":"shot","title":"分镜1：全景—建立镜头","desc":"开场全景建立镜头","draft":{"label":"全景镜头","tag":"Agent","mediaType":"image","prompt":"电影级全景建立镜头，宽银幕构图，自然光，8K"}}]\n```'
    elif any(kw in user_text for kw in ["新增", "添加", "加一个", "再来"]):
        reply = "已为当前分组新增了一个草稿卡片，你可以点击左侧查看。"
        actions_block = '```studio-actions\n[{"action":"add_draft","group_type":"keyElement","group_id":"current","draft":{"label":"Agent 新草稿","tag":"Agent","mediaType":"image","prompt":"新增概念图，电影级采光"}}]\n```'
    elif any(kw in user_text for kw in ["绑定", "素材", "参考图"]):
        reply = "已将素材绑定到当前草稿的参考输入。"
        actions_block = '```studio-actions\n[{"action":"bind_asset","name":"Agent 绑定素材","type":"image","url":"https://picsum.photos/id/1069/400/300"}]\n```'
    else:
        ke_count = context.count('"id": "ke-')
        shot_count = context.count('"id": "shot-')
        reply = (
            f"收到！我来分析一下你的需求：「{user_text}」\n\n"
            f"当前项目状态：{ke_count} 个关键元素、{shot_count} 个分镜。"
            f"你可以告诉我需要调整哪个部分，比如：\n"
            f"- 修改某个草稿的提示词\n"
            f"- 确认/通过某个草稿\n"
            f"- 新增一个分镜或关键元素\n"
            f"- 绑定参考素材"
        )
        actions_block = ""

    return f"{reply}\n\n{actions_block}".strip() if actions_block else reply
