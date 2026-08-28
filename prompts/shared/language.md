== 语言规则 ==
- 思考与回复始终跟随用户最新一条消息的语言：用户用中文则全程用中文思考与回复，用户用英文则全程用英文。
- 本文件只管「对话语言」：产物提示词的语言不在各 Skill 正文中重复声明，统一以 prompt_gates.resolve_prompt_language（用户选择 > Skill 声明 > 平台默认）为唯一裁决源。
- 机械防回潮：scripts/scan_skills.py --gate 的 skill_lang_claim 探针拦截 Skill 正文再现声明性语言规则。
