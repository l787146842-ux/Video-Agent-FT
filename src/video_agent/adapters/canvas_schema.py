"""画布节点类型与映射表（画布领域语义，实现无关）。

对端契约出处（只读参照，禁止修改该目录任何文件）：
E:\\09 Github上的实用工具\\infinite-canvas-main\\canvas-agent\\src\\canvas\\schemas.ts

工具层节点类型 → infinite-canvas 节点类型的映射在此定义（映射表是唯一事实源）。
"""

# 工具层节点类型 → 画布领域语义类型（工具层节点语义归一）
CANVAS_TOOL_NODE_TYPE_TO_CANONICAL: dict[str, str] = {
    "smart-image": "image",
    "image": "image",
    "smart-prompt": "text",
    "text": "text",
}

# ---------- infinite-canvas 通道映射（契约出处 canvas-agent/src/canvas/schemas.ts） ----------

# 对端节点类型闭集（schemas.ts nodeTypeSchema: z.enum）
INFINITE_CANVAS_NODE_TYPES: tuple[str, ...] = ("image", "text", "config", "video", "audio")

# 画布领域语义类型 → infinite-canvas 节点类型（反向：config/video/audio 无领域语义来源）
CANONICAL_TO_INFINITE_CANVAS_NODE_TYPE: dict[str, str] = {
    "image": "image",
    "text": "text",
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
    "connect_nodes", "set_viewport", "select_nodes", "run_generation",
)

# 本项目实际使用的工具白名单（须全部属于 schemas.ts toolNames 34 工具闭集）
INFINITE_CANVAS_USED_TOOLS: tuple[str, ...] = (
    "canvas_list_projects",
    "canvas_get_state",
    "canvas_get_selection",
    "canvas_select_nodes",
    "canvas_apply_ops",
    "canvas_generate_image",
    "generation_get_status",
    "assets_list",
    "assets_add",
    "site_navigate",
)
