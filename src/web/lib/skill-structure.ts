/**
 * Skill 结构化模型：Markdown ↔ 结构化（name/description/sections）无损往返。
 * 与后端 skill_docs.py 同口径双格式：
 *  1. 外部导出原生 <tag>…</tag> 章节（tag 白名单对齐 SECTION_TAG_STAGES）；
 *  2. Markdown 标题式（## 切分，无 ## 时降级 ###；更深层级留在节内正文）。
 * frontmatter（--- 块）原样保留不显示，仅源码模式可见可改。
 * 裸键兼容域拆出 skill-bare-keys.ts / 新建模板拆出 skill-template.ts（250 行红线），
 * 本文件原路径重导出保持调用方零改动。
 */

import { extractBareKeys } from './skill-bare-keys';

export { extractBareKeys };
export { blankSkillTemplate } from './skill-template';

export interface SkillSection {
  /** 唯一键：tag 名 / 标题文本 / __preamble__N（散落段） */
  id: string;
  /** 显示标题（preamble 为「前言」） */
  title: string;
  body: string;
  kind: 'tag' | 'heading' | 'preamble';
  /** heading 节原始标题行（如「## 流程规划」），序列化逐字写回 */
  rawHead?: string;
}

export interface SkillStructure {
  /** 含 --- 边界行的原文块（无则空串） */
  frontmatter: string;
  name: string;
  /** 不含「调用规则：」前缀 */
  description: string;
  sections: SkillSection[];
  format: 'tag' | 'heading';
  /** name 来源：heading `# ` 行 / 导入期裸键（`skill_name:`）兼容兜底；
   * 名称/描述展示权威 = 后端 frontmatter 元数据（见 frontmatterMeta） */
  nameStyle: 'heading' | 'none';
  /** description 来源：`>` 引用块 / 无 */
  descStyle: 'quote' | 'none';
}

/** 章节 tag 白名单（对齐后端 SECTION_TAG_STAGES 键） */
export const SECTION_TAGS = [
  'planner', 'resource_prepare_and_analyze', 'multimodal_analyze_tool',
  'script_analyze', 'text_editor', 'storyboard_designer',
  'storyboard_key_elements', 'storyboard_shots', 'storyboard_audio',
  'write_media_prompt', 'write_the_prompt', 'media_generator', 'generation',
  'image_generate', 'generate_video', 'audio_generate', 'video_assembler',
] as const;

/** 章节显示名/提示映射（未命中时 label 回退 tag/标题原文） */
const SECTION_META: Record<string, { label: string; hint?: string }> = {
  planner: { label: '流程规划', hint: '告诉 AI 按什么顺序推进、步骤之间有什么依赖，以及应该怎样和用户交互。' },
  script_analyze: { label: '素材分析', hint: '告诉 AI 看完素材后要产出什么，比如提取分镜、整理人物描述，或做裁切这类基础处理。' },
  resource_prepare_and_analyze: { label: '素材分析', hint: '告诉 AI 看完素材后要产出什么，比如提取分镜、整理人物描述，或做裁切这类基础处理。' },
  multimodal_analyze_tool: { label: '素材分析', hint: '告诉 AI 看完素材后要产出什么，比如提取分镜、整理人物描述，或做裁切这类基础处理。' },
  text_editor: { label: '文档编写', hint: '告诉 AI 要写哪些项目文档、文档里必须包含哪些条目。' },
  storyboard_key_elements: { label: '关键元素', hint: '角色/场景/道具分组的创建与描述规范。' },
  storyboard_shots: { label: '分镜设计', hint: '分镜分组的创建与描述规范（景别/运镜/时长/引用元素）。' },
  storyboard_audio: { label: '音频层', hint: '台词/BGM/旁白音频层的建立规范。' },
  storyboard_designer: { label: '故事板设计', hint: '关键元素/分镜/音频的故事板整体规范。' },
  write_media_prompt: { label: '提示词写法', hint: '图/视频提示词的语言与内容规范。' },
  write_the_prompt: { label: '提示词写法', hint: '图/视频提示词的语言与内容规范。' },
  media_generator: { label: '媒体生成', hint: '出图/出视频/出音频的参考与参数规范。' },
  generation: { label: '媒体生成', hint: '出图/出视频/出音频的参考与参数规范。' },
  image_generate: { label: '媒体生成', hint: '出图/出视频/出音频的参考与参数规范。' },
  generate_video: { label: '媒体生成', hint: '出图/出视频/出音频的参考与参数规范。' },
  audio_generate: { label: '媒体生成', hint: '出图/出视频/出音频的参考与参数规范。' },
  video_assembler: { label: '组装导出', hint: '最终剪辑与导出引导规范。' },
};

/** 章节显示元数据（label + hint） */
export function sectionMeta(sec: SkillSection): { label: string; hint?: string } {
  const meta = SECTION_META[sec.id] || SECTION_META[sec.title];
  return meta || { label: sec.title };
}

/** 剥离「调用规则：/调用规则:」前缀 */
export function stripDescPrefix(text: string): string {
  return text.replace(/^调用规则\s*[:：]\s*/, '').trim();
}

/** 清理 slug：只保留中文/英文/数字/连字符（与后端 _SLUG_RE 口径对齐） */
export function sanitizeSkillSlug(raw: string): string {
  return raw
    .trim()
    .replace(/[\s_]+/g, '-')
    .replace(/[^\w一-鿿-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 48);
}

/** 拆分 frontmatter（首行 --- 起、下一 --- 止；含边界行逐字保留） */
export function splitFrontmatter(content: string): { frontmatter: string; body: string } {
  const text = content || '';
  if (!text.startsWith('---\n') && text !== '---' && !text.startsWith('---\r\n')) {
    return { frontmatter: '', body: text };
  }
  const m = text.match(/^---[\r\n][\s\S]*?[\r\n]---[\r\n]?/);
  if (!m) return { frontmatter: '', body: text };
  return { frontmatter: m[0], body: text.slice(m[0].length) };
}

const TAG_RE = new RegExp(
  `<(${SECTION_TAGS.join('|')})>([\\s\\S]*?)</\\1>`, 'gi',
);

/** 解析 Skill 全文为结构化模型（正文口径：只认 `# ` 标题与 `>` 引用块；
 * 名称/描述的展示权威在 frontmatter 元数据，见 frontmatterMeta） */
export function parseSkillStructure(content: string): SkillStructure {
  const { frontmatter, body: rawBody } = splitFrontmatter(content || '');
  // 裸键兼容：无 --- 块时剥离头部连续裸键行（只读兼容，不写回）
  let body = rawBody;
  let bareName = '';
  let bareDesc = '';
  if (!frontmatter) {
    const head = rawBody.split('\n');
    const bk = extractBareKeys(head);
    if (bk.consumed > 0) {
      bareName = bk.name;
      bareDesc = bk.description;
      body = head.slice(bk.consumed).join('\n').replace(/^\n+/, '');
    }
  }
  const lines: string[] = body.split('\n');

  // 1) name：首个 `# ` 行；2) description：标题后首个连续 > 引用块
  let name = '';
  let titleIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^#\s+/.test(lines[i])) { name = lines[i].replace(/^#\s+/, '').trim(); titleIdx = i; break; }
  }
  let descEnd = titleIdx;
  let description = '';
  if (titleIdx >= 0) {
    const quote: string[] = [];
    let j = titleIdx + 1;
    while (j < lines.length && lines[j].trim() === '') j++;
    while (j < lines.length && lines[j].trimStart().startsWith('>')) {
      quote.push(lines[j].trimStart().replace(/^>\s?/, ''));
      j++;
    }
    if (quote.length) { description = stripDescPrefix(quote.join('\n').trim()); descEnd = j - 1; }
  }
  // 裸键兜底：正文无 `# ` 标题 / `>` 引块时用导入期裸键声明补齐（只读兼容）
  if (!name) name = bareName;
  if (!description) description = bareDesc;

  const rest = lines.slice(descEnd + 1).join('\n');
  const sections: SkillSection[] = [];
  let preambleN = 0;
  const pushPreamble = (text: string) => {
    if (!text.trim()) return;
    sections.push({ id: `__preamble__${preambleN++}`, title: '前言', body: text.trim(), kind: 'preamble' });
  };

  // 格式 1：<tag> 章节
  TAG_RE.lastIndex = 0;
  const tagMatches = [...rest.matchAll(TAG_RE)];
  if (tagMatches.length > 0) {
    let cursor = 0;
    for (const m of tagMatches) {
      pushPreamble(rest.slice(cursor, m.index));
      const tag = m[1].toLowerCase();
      sections.push({ id: tag, title: sectionMeta({ id: tag, title: tag, body: '', kind: 'tag' }).label, body: m[2].trim(), kind: 'tag' });
      cursor = (m.index || 0) + m[0].length;
    }
    pushPreamble(rest.slice(cursor));
    return {
      frontmatter, name, description,
      sections, format: 'tag',
      nameStyle: name ? 'heading' : 'none',
      descStyle: description ? 'quote' : 'none',
    };
  }

  // 格式 2：Markdown 标题（## 优先，无则 ###）
  const headRe = /^##\s+/m.test(rest) ? /^#{2}\s+/m : /^#{2,3}\s+/m;
  const headMatches = [...rest.matchAll(new RegExp(headRe.source, 'gm'))];
  if (headMatches.length === 0) {
    pushPreamble(rest);
  } else {
    pushPreamble(rest.slice(0, headMatches[0].index));
    headMatches.forEach((hm, i) => {
      const lineEnd = rest.indexOf('\n', hm.index || 0);
      const headEnd = lineEnd === -1 ? rest.length : lineEnd;
      const headLine = rest.slice(hm.index, headEnd).trim();
      const title = headLine.replace(/^#+\s+/, '').trim();
      if (!title) return;
      const end = i + 1 < headMatches.length ? headMatches[i + 1].index : rest.length;
      sections.push({ id: title, title, body: rest.slice(headEnd + 1, end).trim(), kind: 'heading', rawHead: headLine });
    });
  }
  return {
    frontmatter, name, description,
    sections, format: 'heading',
    nameStyle: name ? 'heading' : 'none',
    descStyle: description ? 'quote' : 'none',
  };
}

/** 序列化结构化模型为 Skill Markdown（frontmatter/标题/引用/章节顺序无损） */
export function serializeSkillStructure(s: SkillStructure): string {
  const out: string[] = [];
  if (s.frontmatter.trim()) out.push(s.frontmatter.trim());
  if (s.name.trim()) out.push(`# ${s.name.trim()}`);
  if (s.description.trim()) {
    const descLines = s.description.trim().split('\n');
    out.push(descLines.map((l, i) => (i === 0 ? `> 调用规则：${l}` : `> ${l}`)).join('\n'));
  }
  for (const sec of s.sections) {
    if (sec.kind === 'preamble') out.push(sec.body.trim());
    else if (sec.kind === 'tag') out.push(`<${sec.id}>\n${sec.body.trim()}\n</${sec.id}>`);
    else out.push(`${sec.rawHead || `## ${sec.title}`}\n\n${sec.body.trim()}`);
  }
  return out.filter((p) => p !== '').join('\n\n') + '\n';
}

/** frontmatter 元数据只读解析（批 C）：名称/描述的单一权威 = 后端
 * skill_docs.py 的 frontmatter 解析，前端只在无网/编辑期做同口径读取。
 * 仅识别 `name:`/`description:` 键（与后端 _parse_doc 对齐）；无 --- 块时
 * 兜底裸键兼容（与后端 _extract_bare_keys 同口径）。不写回——修改走源码模式原文。 */
export function frontmatterMeta(content: string): { name: string; description: string } {
  const { frontmatter } = splitFrontmatter(content || '');
  if (!frontmatter) {
    const bk = extractBareKeys((content || '').split('\n'));
    return { name: bk.name, description: bk.description };
  }
  let name = '';
  let description = '';
  for (const line of frontmatter.split('\n')) {
    if (!name) {
      const m = line.match(/^\s*name\s*:\s*["']?(.*?)["']?\s*$/);
      if (m) { name = m[1].trim(); continue; }
    }
    if (!description) {
      const m = line.match(/^\s*description\s*:\s*["']?(.*?)["']?\s*$/);
      if (m) { description = m[1].trim(); continue; }
    }
  }
  return { name, description };
}
