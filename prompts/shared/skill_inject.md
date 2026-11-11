# Skill 注入文案（目录/选中/来源标记的单一事实源）
# 注入条件：目录段=注册表有可用条目；选中段=用户选中 Skill；来源标记=frontmatter.source 非 platform
# 消费方：core/prompt_builder（build_skill_catalog / build_selected_skill_block /
#          build_skill_metadata_header）与 tools/document_tools.read_skill

## HEADER
== Skill 目录（渐进式披露，总纲见 protocol《渐进式披露总纲》：上下文只常驻各 Skill 的名称与摘要；选中 Skill 默认注入主文档全文，超预算时注入开头与标题目录；其余分册与其余 Skill 全文经 read_skill 按需加载，不要凭目录摘要自行推测流程细节）==

## SELECTED
用户当前在前端选中了「{{skill_name}}」，其主文档已注入（见文末选中段）；分册（references/…）与其他 Skill 全文，需要时经 read_skill 读取。

## STYLE_LAYERS
另有风格层叠加生效：{{style_names}}（风格层正文零注入，执行产出前先 read_skill 读取各风格层）。

## OMITTED
（另有 {{count}} 个已启用 Skill 未列出：目录按最近使用序截断；需要完整名单可调 list_skills，具体 Skill 全文仍经 read_skill 按需读取）

## SELECTED_NOTE
== 当前选中 Skill「{{name}}」：下方已注入主文档正文（超预算时为开头与标题目录）；分册经 read_skill(name="{{name}}", resource="references/xxx.md") 读取，章节续读用 section/start ==

## TOC_NOTE
== 标题目录（正文按需经 read_skill(name="{{name}}", section="标题") 读取） ==

## TRUNC_NOTE
== 当前选中 Skill「{{name}}」主文档共 {{total}} 字，超过注入预算，下方只注入前 {{head}} 字与标题目录；其余正文经 read_skill(name="{{name}}", start={{head}}) 续读 ==

## META_LINE
来源：社区/外部导入（出处：{{source}}）

## READ_NOTE
（该 Skill 为社区/外部导入，出处：{{source}}，来源信息供知情）
