/**
 * Skill 结构化模型：Markdown ↔ 结构化（name/description/sections）无损往返。
 * 与后端 skill_docs.py 同口径（通用标题式）：
 *  Markdown 标题（## 切分，无 ## 时降级 ###；更深层级留在节内正文）；
 *  旧 <tag> 只作普通文本，不触发章节解析。
 * frontmatter（--- 块）原样保留不显示，仅源码模式可见可改。
 * 裸键兼容域拆出 skill-bare-keys.ts / 新建模板拆出 skill-template.ts（250 行红线），
 * 本文件原路径重导出保持调用方零改动。
 */

import { extractBareKeys } from './skill-bare-keys';

export { extractBareKeys };
export { blankSkillTemplate } from './skill-template';

export interface SkillSection {
  /** 唯一键：标题文本 / __preamble__N（散落段） */
  id: string;
  /** 显示标题（preamble 为「前言」） */
  title: string;
  body: string;
  kind: 'heading' | 'preamble';
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
  format: 'heading';
  /** name 来源：heading `# ` 行 / 导入期裸键（`skill_name:`）兼容兜底；
   * 名称/描述展示权威 = 后端 frontmatter 元数据（见 frontmatterMeta） */
  nameStyle: 'heading' | 'none';
  /** description 来源：`>` 引用块 / 无 */
  descStyle: 'quote' | 'none';
}

/** 章节显示元数据（通用口径：标题原文即显示名，不再有平台标签映射） */
export function sectionMeta(sec: SkillSection): { label: string; hint?: string } {
  return { label: sec.title || sec.id };
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

  // Markdown 标题（## 优先，无则 ###）
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
