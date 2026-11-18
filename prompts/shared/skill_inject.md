# Skill 注入文案（目录/选中/来源标记的单一事实源）
# 注入条件：目录段=注册表有可用条目；选中段=用户选中 Skill；来源标记=frontmatter.source 非 platform
# 消费方：core/prompt_builder（build_skill_catalog / build_selected_skill_block /
#          build_skill_metadata_header）与 tools/document_tools.read_skill

## HEADER
== Skill 目录（渐进式披露，总纲见 protocol《渐进式披露总纲》：上下文只常驻各 Skill 的名称与摘要；Skill 正文不常驻，匹配到任务或用户触发时再加载；不要凭目录摘要自行推测流程细节）==

## SELECTED
用户当前在前端选中了「{{skill_name}}」；正文不常驻，执行前用 read_skill(name="{{skill_name}}") 读取全文，分册（references/…）用 read_skill(name="{{skill_name}}", resource="references/xxx.md") 读取。

## STYLE_LAYERS
另有风格层叠加生效：{{style_names}}（风格层正文零注入，执行产出前先 read_skill 读取各风格层）。

## OMITTED
（另有 {{count}} 个已启用 Skill 未列出：目录按最近使用序截断；需要完整名单可调 list_skills，具体 Skill 全文仍经 read_skill 按需读取）

## SELECTED_NOTE
== 当前主 Skill「{{name}}」：正文未常驻；执行前调 read_skill(name="{{name}}") 读取全文，分册经 read_file(skill="{{name}}", file_path="references/xxx.md") 读取 ==

## SELECTED_NOTE_USER_ONLY
== 当前主 Skill「{{name}}」为用户专用：正文只在用户消息带 `/{{slug}}` 时一次性注入；如果本轮对话中没有对应的 skill_content，不要自行执行该 Skill，也不要调 read_skill（会被拒绝）。分册用 read_file(skill="{{slug}}", file_path="references/xxx.md") 读取 ==

## TOC_NOTE
== 标题目录（正文按需经 read_skill(name="{{name}}", section="标题") 读取） ==

## REFS_NOTE
== 本 Skill 的分册（正文因超预算被截断，以下路径取自全文引用，需要时经 read_skill(name="{{name}}", resource="路径") 读取） ==

## TRUNC_NOTE
== 当前选中 Skill「{{name}}」主文档共 {{total}} 字，超过注入预算，下方只注入前 {{head}} 字与标题目录；其余正文经 read_skill(name="{{name}}", start={{head}}) 续读 ==

## META_LINE
来源：社区/外部导入（出处：{{source}}）

## READ_NOTE
（该 Skill 为社区/外部导入，出处：{{source}}，来源信息供知情）
