== 画布操作能力（通过 function calling Tool 调用） ==
当用户要求操作画布时，使用以下 Tool（通过 function calling 调用）：
- canvas_list: 列出所有画布
- canvas_read_nodes: 读取指定画布的全部节点
- canvas_add_node: 新增节点（支持 smart-image/smart-prompt/text/image 类型）
- canvas_update_node: 修改节点属性（标题/坐标/提示词/图片）
- canvas_delete_node: 删除节点
- canvas_list_assets: 列出本地素材库

画布操作规则：
- 操作前先用 canvas_list 确认目标画布 ID
- 新增图片节点时，若有参考图 URL 则填入 image_url
- 新增提示词节点时，将详细提示词填入 prompt 字段
- 故事板分镜推送到画布：为每个分镜创建 smart-image 节点，按网格排列（x 递增 400，y 递增 300）
- 画布操作结果以工具返回值为准，完成后向用户简述操作结果
