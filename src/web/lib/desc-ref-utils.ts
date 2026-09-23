/**
 * 分镜正文内联引用块纯工具（对齐 Flova 批）：正文里的引用 = 本镜 shotRefs
 * 在 desc 文本中的视图。
 * - 识别：shotRefs 解析为标题后在 desc 中出现的 → 内联块（最长优先防重叠误切）；
 * - 渲染：纯文本 ↔ DOM（块复用 mention-chip 概念图+名称 chip；编辑态块内带 ×）；
 * - 序列化：保存时块还原为纯名（desc 存储保持纯文本，不带 @ token）；
 * - 同步：编辑保存时 shotRefs 按「旧 − 正文已消失提及 + @ 插入」派生。
 */
import { escapeRe, makeChip, type MediaKind } from '@/lib/prompt-ref-utils';
import type { DraftType, ShotGroup } from '@/types';

export interface KeyElementLike {
  id?: string;
  title?: string;
  drafts?: Array<{ imgUrl?: string }>;
}

/** 容器 ID 约定类型前缀（2026-09-17 裁决；后端 _GROUP_TITLE_PREFIX 同契约镜像） */
export const GROUP_TITLE_PREFIX: Record<DraftType, string> = {
  keyElement: 'Element_',
  shot: 'Shot_',
  audio: 'Audio_',
};

const TYPE_PREFIXES = Object.values(GROUP_TITLE_PREFIX);

/**
 * 前端归一单一事实源：剥容器类型前缀取名字（2026-09-17 裁决对齐 flova：
 * 纯结构性，只认 Element_/Shot_/Audio_ 三个前缀，无词表翻译）；
 * 显示/引用匹配共用，后端 strip_type_prefix 同契约。
 */
export function stripTypePrefix(title: string): string {
  const t = String(title || '').trim();
  for (const p of TYPE_PREFIXES) {
    if (t.startsWith(p)) return t.slice(p.length);
  }
  return t;
}

/** 写口归一（2026-09-17 裁决）：幂等补容器类型前缀，名字原样（后端 normalize_group_title 同契约） */
export function canonicalGroupTitle(title: string, type: DraftType): string {
  const t = String(title || '').trim();
  const prefix = GROUP_TITLE_PREFIX[type] || '';
  if (!prefix || !t || t.startsWith(prefix)) return t;
  return prefix + t;
}

/** shotRefs 存关键元素 id（ke-xxx）或标题；统一解析为归一标题（同 ShotRefsChips 口径） */
export function resolveRefTitle(ref: string, keyElements: KeyElementLike[]): string {
  const el = keyElements.find((k) => k.id === ref || k.title === ref);
  return stripTypePrefix(el?.title || String(ref));
}

/**
 * K7 批（2026-09-16）显示标题归一单一事实源，2026-09-17 裁决收敛（对齐 flova）：
 * 显示层只剥容器类型前缀（Element_/Shot_/Audio_），其余原样显示
 * （名字 = 模型原文，平台不做二次清洗）；数据层标题原样存储（台账 #10）。
 */
export function normalizeDisplayTitle(title: string): string {
  return stripTypePrefix(title);
}

/** 组标题显示归一（flova 对齐批 2026-09-17）：剥容器前缀后迭代剥 leading 编号
 * 令牌（镜号/场号：`01 ` / `S1 ·` / `S02·` / `场一·`）——flova 标题纯描述，
 * 本项目存量标题编号由显示层兜底归一；仅用于组标题显示（不进
 * normalizeDisplayTitle：避免误剥数字开头元素名，如「二维空间平面」）；
 * 数据层标题原样存储（台账 #10）。 */
const LEADING_CODE_TOKENS = [
  /^\d{1,3}\s*[、.·\-)］]\s*/,
  /^\d{1,3}\s+(?=\S)/,
  /^[Ss]\d{1,3}\s*[·.・\-]\s*/,
  /^场[一二三四五六七八九十两\d]{1,3}\s*[·.、\-]\s*/,
];
export function normalizeDisplayGroupTitle(title: string): string {
  let t = stripTypePrefix(title);
  for (let i = 0; i < 4; i++) {
    const before = t;
    for (const re of LEADING_CODE_TOKENS) t = t.replace(re, '');
    if (t === before) break;
  }
  return t;
}

/**
 * 内联块候选名：候选源 = keyElements 全集（不再局限本镜 shotRefs）。
 * 每个元素产两种形态——原全称 + 归一名字（stripTypePrefix），Set 去重，
 * ≥2 字符守卫（此处为唯一加守卫点），按长度降序（最长优先防重叠误切）。
 * group 参数保留仅为调用点稳定，候选不再依赖 shotRefs。
 */
export function descChipNames(
  _group: Pick<ShotGroup, 'shotRefs'>,
  keyElements: KeyElementLike[],
): string[] {
  const titles = new Set<string>();
  keyElements.forEach((k) => {
    const raw = k.title;
    if (!raw) return;
    if (raw.length >= 2) titles.add(raw);            // 原全称
    const bare = stripTypePrefix(raw);
    if (bare.length >= 2) titles.add(bare);          // 归一名字
  });
  return [...titles].sort((a, b) => b.length - a.length);
}

/** 元素首张概念图（块缩略图）；无图返回 ''（渲染为纯名块，对齐 Flova pill）。
 *  查表按归一标题比对：块名可能是名字（“程心”），元素标题可能带类型前缀（“Element_程心”）。 */
function elementThumb(title: string, keyElements: KeyElementLike[]): string {
  const norm = stripTypePrefix(title);
  const el = keyElements.find((k) => stripTypePrefix(k.title || '') === norm);
  return (el?.drafts || []).map((d) => d.imgUrl || '').find(Boolean) || '';
}

/** 纯文本 → 正文 DOM：命中标题渲染为 mention-chip 内联块；editable 时块内追加 ×
 *  删除钮；\n 保留在文本节点里（容器 pre-wrap 呈现分段）。 */
export function renderDescToDOM(
  el: HTMLElement,
  text: string,
  names: string[],
  keyElements: KeyElementLike[],
  editable: boolean,
): void {
  el.textContent = '';
  if (!text) return;
  if (!names.length) {
    el.textContent = text;
    return;
  }
  const re = new RegExp(`(${names.map(escapeRe).join('|')})`, 'g');
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
    const chip = makeChip(m[1], {
      url: elementThumb(m[1], keyElements),
      type: 'image' as MediaKind,
    });
    // 读态块可点跳转（覆盖 makeChip 的「点击放大」title）；编辑态块无独立动作
    chip.title = editable ? '' : '点击跳转到该关键元素';
    if (editable) {
      const x = document.createElement('span');
      x.className = 'desc-ref-remove';
      x.title = '移除该引用';
      x.textContent = '×';
      chip.appendChild(x);
    }
    el.appendChild(chip);
    last = m.index + m[0].length;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}

/** 正文 DOM → 纯文本（保存口径）：块还原为纯名（不带 @），块级边界还原 \n */
export function serializeDescDOM(root: HTMLElement): string {
  let out = '';
  let firstBlock = true;
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      // 不间断空格（chip 后的占位）规范化为普通空格，保证存储文本干净
      out += (node.nodeValue || '').replace(/\u00a0/g, ' ');
      return;
    }
    if (!(node instanceof HTMLElement)) return;
    if (node.classList.contains('mention-chip')) {
      out += node.dataset.name || '';
      return;
    }
    if (node.tagName === 'BR') { out += '\n'; return; }
    const isBlock = /^(DIV|P|LI)$/.test(node.tagName);
    if (isBlock && !firstBlock && out && !out.endsWith('\n')) out += '\n';
    firstBlock = false;
    node.childNodes.forEach(walk);
  };
  root.childNodes.forEach(walk);
  return out;
}

/** 编辑保存时 shotRefs 同步：新 = 旧 − 正文已消失提及的引用 + @ 插入的标题
 *  + 裸名提及 auto 源（K4 批 2026-09-16 对齐 flova：提及即绑定）。
 *  无增删返回 null（调用方不必写库）。 */
export function syncShotRefsAfterEdit(
  prevRefs: string[],
  serializedText: string,
  insertedTitles: string[],
  keyElements: KeyElementLike[],
): string[] | null {
  const kept = prevRefs.filter((r) =>
    serializedText.includes(resolveRefTitle(String(r), keyElements)));
  const keptTitles = new Set(kept.map((r) => resolveRefTitle(String(r), keyElements)));
  const added = insertedTitles.filter((t) => !keptTitles.has(t));
  // auto 源：正文里提及的元素名（原全称/归一裸名）不在 kept/added 时自动补绑；
  // 存储口径归一到元素原标题（与后端 scan_bare_name_mentions 同口径）
  const boundNorm = new Set([
    ...kept.map((r) => resolveRefTitle(String(r), keyElements)),
    ...added.map((t) => stripTypePrefix(String(t))),
  ]);
  const auto: string[] = [];
  descChipNames({ shotRefs: [] }, keyElements).forEach((n) => {
    if (!serializedText.includes(n)) return;
    const el = keyElements.find(
      (k) => k.title === n || stripTypePrefix(k.title || '') === n);
    const canon = el?.title || n;
    if (!canon) return;
    if (boundNorm.has(stripTypePrefix(canon))) return;
    if (!auto.includes(canon)) auto.push(canon);
  });
  if (kept.length === prevRefs.length && !added.length && !auto.length) return null;
  return [...kept, ...added, ...auto];
}
