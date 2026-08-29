# Skill 目录段外置文案（渐进披露口径，单一表述源）
# 消费方：core/prompt_builder.build_skill_catalog（load_prompt_section 分节读取）

## HEADER
== Skill 目录（渐进式披露，总纲见《重要规则》：上下文只常驻各 Skill 的名称与摘要；选中 Skill 的正文头部按预算注入，全文与其余 Skill 经 read_skill 按需加载，不要凭目录摘要自行推测流程细节）==

## SELECTED
用户当前在前端选中了「{{skill_name}}」，其正文头部已按渐进披露预算注入（见文末选中段）；超出预算的其余部分与其他 Skill 全文，需要时经 read_skill 读取。

## STYLE_LAYERS
另有风格层叠加生效：{{style_names}}（风格层正文不经预算注入，执行产出前先 read_skill 读取各风格层）。
