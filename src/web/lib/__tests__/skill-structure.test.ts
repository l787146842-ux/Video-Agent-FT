/**
 * skill-structure 解析/序列化 round-trip 单测。
 * fixtures 覆盖：标题式（通用格式）与旧标签文本（只作普通文本，不触发章节解析）。
 */
import { describe, it, expect } from 'vitest';
import {
  parseSkillStructure, serializeSkillStructure, splitFrontmatter,
  sanitizeSkillSlug, blankSkillTemplate, stripDescPrefix, sectionMeta,
  frontmatterMeta,
} from '@/lib/skill-structure';

const TAG_FIXTURE = `---
kind: pipeline
version: '1.0'
---

# 剧本生视频（需上传剧本）

> 调用规则：本 Skill 面向「已有剧本」的短视频工业化生成。

<planner>
**完整视频的阶段逻辑和依赖关系：**
1. 总结剧本。 → script_analyze。
2. 编写规格。 → text_editor。
</planner>

<storyboard_shots>
只创建分镜分组。
</storyboard_shots>

散落的补充说明文本。
`;

const HEADING_FIXTURE = `# 电影级叙事短片

> 调用规则：适用于高质感电影级叙事短片创作。

## 流程规划（三段式）

1. 建立全局规格。
2. 结构化分镜设计。

### 子步骤

- 子步骤留在节内正文。

## 提示词写法

- 中文分层描述。
`;

describe('splitFrontmatter', () => {
  it('含 --- 块：逐字保留边界行', () => {
    const { frontmatter, body } = splitFrontmatter(TAG_FIXTURE);
    expect(frontmatter.startsWith('---\n')).toBe(true);
    expect(frontmatter.endsWith('---\n')).toBe(true);
    expect(frontmatter).toContain('kind: pipeline');
    expect(body.startsWith('\n# 剧本生视频')).toBe(true);
  });
  it('无 --- 块：frontmatter 空串', () => {
    expect(splitFrontmatter('# a\n\nbody').frontmatter).toBe('');
  });
});

describe('parseSkillStructure（旧标签按普通文本）', () => {
  const s = parseSkillStructure(TAG_FIXTURE);
  it('name/description 提取且剥离前缀', () => {
    expect(s.name).toBe('剧本生视频（需上传剧本）');
    expect(s.description).toBe('本 Skill 面向「已有剧本」的短视频工业化生成。');
    expect(s.format).toBe('heading');
  });
  it('标签不再触发章节解析，整段作为前言', () => {
    expect(s.sections.map((x) => x.kind)).toEqual(['preamble']);
    expect(s.sections[0].body).toContain('<planner>');
    expect(s.sections[0].body).toContain('散落的补充说明文本');
  });
});

describe('parseSkillStructure（标题式）', () => {
  const s = parseSkillStructure(HEADING_FIXTURE);
  it('## 切分、### 留在节内', () => {
    expect(s.format).toBe('heading');
    expect(s.sections.map((x) => x.title)).toEqual(['流程规划（三段式）', '提示词写法']);
    expect(s.sections[0].body).toContain('### 子步骤');
    expect(s.sections[0].rawHead).toBe('## 流程规划（三段式）');
  });
});

describe('旧式 skill_name/skill_description 声明行已退役（批 C）', () => {
  const LEGACY_FIXTURE = `---
version: '1.0'
---

skill_name: "旧式 Skill"
skill_description: "旧式描述"
<planner>
流程
</planner>
`;
  it('不再解析为名称/描述（正文口径只认 `# ` 标题与 `>` 引用块）', () => {
    const s = parseSkillStructure(LEGACY_FIXTURE);
    expect(s.name).toBe('');
    expect(s.description).toBe('');
    expect(s.nameStyle).toBe('none');
    expect(s.descStyle).toBe('none');
  });
  it('声明行留在正文不再剔出（结构化视图名称/描述权威 = frontmatter 元数据）', () => {
    const s = parseSkillStructure(LEGACY_FIXTURE);
    expect(s.sections.some((x) => x.body.includes('skill_name'))).toBe(true);
  });
});

describe('frontmatterMeta（名称/描述展示权威，批 C）', () => {
  it('读取 name/description 键（与后端 _parse_doc 同口径）', () => {
    const content = `---
name: 演示 Skill
description: 需要演示时调用
---

# 正文标题
`;
    expect(frontmatterMeta(content)).toEqual({ name: '演示 Skill', description: '需要演示时调用' });
  });
  it('带引号值去引号', () => {
    const m = frontmatterMeta(`---\nname: "引号名"\ndescription: '引号描述'\n---\n`);
    expect(m).toEqual({ name: '引号名', description: '引号描述' });
  });
  it('无 frontmatter 返回空', () => {
    expect(frontmatterMeta('# 仅正文')).toEqual({ name: '', description: '' });
  });
});

describe('裸键兼容（导入期只读，与后端 _extract_bare_keys 同口径）', () => {
  const BARE_FIXTURE = `# 首行非裸键即不探测（与后端一致）
skill_name: 不生效的裸键行（不在文档首行起）
`;
  it('头部连续裸键（含带引号值）：名称/描述正确解析，正文不含裸键行', () => {
    const content = `skill_name: 裸键技能\nskill_description: "导入自外部平台"\n\n# 正文标题\n\n正文内容。\n`;
    expect(frontmatterMeta(content)).toEqual({ name: '裸键技能', description: '导入自外部平台' });
    const s = parseSkillStructure(content);
    expect(s.name).toBe('正文标题'); // 正文 `# ` 标题优先，裸键仅作兜底
    expect(s.sections.every((x) => !x.body.includes('skill_name:'))).toBe(true);
    // 无 `#` 标题时裸键兜底补齐名称/描述（修复导入技能前端显示为空）
    const noHead = parseSkillStructure(`skill_name: 裸键技能\nskill_description: 导入自外部平台\n\n正文。\n`);
    expect(noHead.name).toBe('裸键技能');
    expect(noHead.description).toBe('导入自外部平台');
  });
  it('首个非裸键行即停；单键/无裸键文档不受影响（首行 --- 的 YAML 仍走原路径）', () => {
    // 首行非裸键 → 不探测（与后端一致）
    expect(frontmatterMeta(BARE_FIXTURE)).toEqual({ name: '', description: '' });
    // 仅 skill_name 单键 → description 空串不报错
    const single = frontmatterMeta('skill_name: 单键技能\n\n正文。');
    expect(single).toEqual({ name: '单键技能', description: '' });
    // 首行 --- 的 YAML 技能仍走原路径（回归）
    expect(frontmatterMeta(TAG_FIXTURE)).toEqual({ name: '', description: '' });
    const s = parseSkillStructure(TAG_FIXTURE);
    expect(s.name).toBe('剧本生视频（需上传剧本）');
  });
});

describe('round-trip', () => {
  it('旧标签文本：parse(serialize(parse)) 深相等', () => {
    const once = parseSkillStructure(TAG_FIXTURE);
    const twice = parseSkillStructure(serializeSkillStructure(once));
    expect(twice).toEqual(once);
  });
  it('标题式：parse(serialize(parse)) 深相等', () => {
    const once = parseSkillStructure(HEADING_FIXTURE);
    const twice = parseSkillStructure(serializeSkillStructure(once));
    expect(twice).toEqual(once);
  });
  it('frontmatter 与散落段不丢', () => {
    const twice = parseSkillStructure(serializeSkillStructure(parseSkillStructure(TAG_FIXTURE)));
    expect(twice.frontmatter).toContain('kind: pipeline');
    expect(twice.sections.some((x) => x.kind === 'preamble')).toBe(true);
  });
});

describe('serialize 细节', () => {
  it('description 序列化补回「调用规则：」前缀，多行仅首行带', () => {
    const s = parseSkillStructure(HEADING_FIXTURE);
    s.description = '第一行\n第二行';
    const out = serializeSkillStructure(s);
    expect(out).toContain('> 调用规则：第一行\n> 第二行');
  });
  it('stripDescPrefix 兼容半角冒号', () => {
    expect(stripDescPrefix('调用规则: x')).toBe('x');
    expect(stripDescPrefix('调用规则：x')).toBe('x');
    expect(stripDescPrefix('x')).toBe('x');
  });
});

describe('工具函数', () => {
  it('sanitizeSkillSlug', () => {
    expect(sanitizeSkillSlug('剧本 生视频_!x')).toBe('剧本-生视频-x');
    expect(sanitizeSkillSlug('--a--')).toBe('a');
  });
  it('blankSkillTemplate 可解析', () => {
    const s = parseSkillStructure(blankSkillTemplate());
    expect(s.sections.map((x) => x.id)).toContain('三、制作流程');
  });
  it('blankSkillTemplate 是通用标题式骨架（2026-11-11 迁移）', () => {
    const s = parseSkillStructure(blankSkillTemplate());
    expect(s.sections.map((x) => x.id)).toEqual([
      '一、这个 Skill 做什么', '二、开工前先确认', '三、制作流程',
      '四、结构与素材', '五、专业方法', '六、参考资料',
    ]);
    expect(s.sections.every((x) => x.kind === 'heading')).toBe(true);
    expect(s.format).toBe('heading');
    expect(s.name).toBe('新 Skill');
    for (const sec of s.sections) expect(sec.body.trim().length).toBeGreaterThan(0);
  });
  it('章节显示名回退标题原文（不再有平台标签映射）', () => {
    const s = parseSkillStructure(blankSkillTemplate());
    const flow = s.sections.find((x) => x.title.includes('制作流程'))!;
    expect(sectionMeta(flow).label).toBe(flow.title);
  });
  it('blankSkillTemplate 含可注册 frontmatter（name/description 非空）', () => {
    const raw = blankSkillTemplate();
    const s = parseSkillStructure(raw);
    expect(s.frontmatter.startsWith('---\n')).toBe(true);
    expect(s.frontmatter).toContain('name:');
    expect(s.frontmatter).toContain('description:');
    const meta = frontmatterMeta(raw);
    expect(meta.name).toBe('新 Skill');
    expect(meta.description).toBe('一句话说明何时使用本 Skill');
  });
});
