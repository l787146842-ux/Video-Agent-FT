# Skill 加载拒载外置文案（M3 批2：注册表=加载唯一门户）
# 三类语义区分：已停用（开关注销）/ 未注册被拒（磁盘存在但注册失败）/ 未找到
# 消费方：tools/document_tools.ReadSkillTool（load_prompt_section/render_prompt_section 分节读取）

## DISABLED
Skill「{{name}}」已停用，不可读取（停用=真停用）

## UNREGISTERED
Skill「{{name}}」在磁盘存在但未通过注册（frontmatter 缺 name/description 声明或内容损坏），不可加载；请到 Skill 工作台查看并修复该 Skill 包

## NOT_FOUND
未找到 Skill「{{name}}」。可用 Skill：{{available}}
