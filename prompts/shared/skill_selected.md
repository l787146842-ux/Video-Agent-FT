# 选中 Skill 段外置文案（B1：按需加载注入，单一表述源）
# 消费方：core/prompt_builder.build_selected_skill_block（load_prompt_section 分节读取）
# （预算式正文头部注入（HEAD_TRUNCATED/HEAD_FULL/CONTINUE_NOTE）已随
#  B1 裁决 2026-08-31 退役：默认注入收窄为 <planner> 段全文 + 章节目录。）

## SELECTED_NOTE
== 当前选中 Skill「{{name}}」：下方已注入流程（planner）段全文与章节目录；其余章节正文按需经 read_skill(name="{{name}}", section="章节名") 读取 ==

## TOC_NOTE
== 章节目录（正文按需经 read_skill(name="{{name}}", section="章节名") 读取） ==
