当前工作台状态 JSON 如下（每轮自动刷新）：
{{#if selected_draft_id}}
用户当前选中的草稿：draft_id={{selected_draft_id}}（类型 {{selected_type}}）。studio-actions 里的 "current" 指向它。
{{/if}}

{{state_json}}
