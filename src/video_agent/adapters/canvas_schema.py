"""画布节点类型与映射表（画布领域语义，实现无关）。

契约出处（L2 起本仓自持，画布源码已 vendored）：
- ops 应用语义：`vendors/infinite-canvas/web/src/lib/canvas/canvas-agent-ops.ts`
- 工具闭集与高层工具翻译：`src/video_agent/adapters/canvas_agent_session.py`

工具层节点类型 → infinite-canvas 节点类型的映射在此定义（映射表是唯一事实源）。
"""

# 工具层节点类型 → 画布领域语义类型（工具层节点语义归一）
CANVAS_TOOL_NODE_TYPE_TO_CANONICAL: dict[str, str] = {
    "smart-image": "image",
    "image": "image",
    "smart-prompt": "text",
    "text": "text",
    # 组装导出：成片以 video 节点落到画布（metadata.content = 成片 URL）
    "video": "video",
    "audio": "audio",
    # 大类容器：原生组节点（2026-11-11）。画布浏览器侧按注册类型接受
    # （canvas-agent-ops.ts 的 add_node 用 isRegisteredNodeType 判定），
    # group 是内建类型；容器靠成员 metadata.groupId 建立归属。
    "group": "group",
}

# ---------- infinite-canvas 通道映射（契约出处 canvas-agent/src/canvas/schemas.ts） ----------

# 对端节点类型闭集（内建注册类型：image/text/config/video/audio/group）
INFINITE_CANVAS_NODE_TYPES: tuple[str, ...] = (
    "image", "text", "config", "video", "audio", "group",
)

# 画布领域语义类型 → infinite-canvas 节点类型
CANONICAL_TO_INFINITE_CANVAS_NODE_TYPE: dict[str, str] = {
    "image": "image",
    "text": "text",
    "video": "video",
    "audio": "audio",
    "group": "group",
}

# 工具层节点类型 → infinite-canvas 节点类型（经 canonical 合成；写入转换依赖）
CANVAS_TOOL_TO_INFINITE_CANVAS_NODE_TYPE: dict[str, str] = {
    k: CANONICAL_TO_INFINITE_CANVAS_NODE_TYPE[v]
    for k, v in CANVAS_TOOL_NODE_TYPE_TO_CANONICAL.items()
}

# image/text 节点负载统一存 metadata.content：image 存图片 URL、text 存正文
# （对端 compactNode 只透出 metadata，schemas.ts metadata 为 recordSchema）
INFINITE_CANVAS_IMAGE_MEDIA_FIELD = "content"

# canvas_apply_ops ops 类型闭集（schemas.ts canvasOpSchema discriminatedUnion type 字段）
INFINITE_CANVAS_OP_TYPES: tuple[str, ...] = (
    "add_node", "update_node", "delete_node", "delete_connections",
    "connect_nodes", "group_nodes", "ungroup_nodes",
    "set_viewport", "select_nodes", "run_generation",
)

# 本项目实际使用的工具白名单（须全部属于画布工具闭集，L2 后由会话层白名单校验）
INFINITE_CANVAS_USED_TOOLS: tuple[str, ...] = (
    "canvas_list_projects",
    "canvas_get_state",
    "canvas_get_selection",
    "canvas_select_nodes",
    "canvas_apply_ops",
    "canvas_group_nodes",
    "canvas_ungroup_nodes",
    "canvas_generate_image",
    "generation_get_status",
    "assets_list",
    "assets_add",
    "site_navigate",
)
