/**
 * 新建 Skill 空白模板（三段式骨架）：与 skill-structure 解析口径往返一致。
 * 自 skill-structure.ts 拆出（前端 250 行红线），原路径重导出保持调用方零改动。
 */

/** 新建 Skill 空白模板（三段式骨架）：头部含最小可注册 frontmatter
 *（注册侧必填即 name/description 非空，见 registry.py 注册校验）。
 * C1c 裁决 2026-08-31：书写约定提示随模板下发——frontmatter 仅
 * name/description 必填、其余键全部可选零警告；导入的外部 Skill
 *（如 Flova 裸键 skill_name:/skill_description: 无 --- 形态）同样可注册。 */
export function blankSkillTemplate(): string {
  return [
    '---',
    'name: 新 Skill',
    'description: 一句话说明何时使用本 Skill',
    '---',
    '',
    '<!-- 书写约定：frontmatter 仅 name/description 必填，其余键全部可选；',
    '     流程纪律（何时暂停、何时确认）直接写进下方散文，平台不再读取机械声明键 -->',
    '',
    '# 新 Skill',
    '',
    '> 调用规则：一句话说明何时使用本 Skill',
    '',
    '## 流程规划',
    '',
    '1. 第一步做什么，调用哪个工具',
    '2. 第二步做什么，何时暂停等待用户确认',
    '',
    '## 提示词写法',
    '',
    '- 提示词语言与内容规范',
    '',
  ].join('\n');
}
