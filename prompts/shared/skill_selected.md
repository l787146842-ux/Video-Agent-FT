# 选中 Skill 段外置文案（正文经渐进披露预算化注入，单一表述源）
# 消费方：core/prompt_builder.build_selected_skill_block（load_prompt_section 分节读取）

## HEAD_TRUNCATED
== 当前选中 Skill「{{name}}」：正文头部已按渐进披露预算注入（见下方正文头部）；其余部分经 read_skill(name="{{name}}", section/start) 续读 ==

## HEAD_FULL
== 当前选中 Skill「{{name}}」：全文已按渐进披露预算完整注入（见下方正文） ==

## CONTINUE_NOTE
……（正文头部到此为止：全文共 {{total}} 字，已注入前 {{injected}} 字；其余部分传 read_skill(name="{{name}}", start={{start}}) 续读，或传 section 读取指定章节）
