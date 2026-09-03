# 选中草稿指针段外置文案（硬编码文案外置，单一表述源）
# 消费方：core/prompt_builder._sec_selected_draft（load_prompt_section 分节读取）
# 注入条件：context.selected_draft_id 非空（用户选中某草稿）时由 prompt_builder 独立成段注入

## POINTER
用户当前选中的草稿：draft_id={{draft_id}}（类型 {{draft_type}}）。
