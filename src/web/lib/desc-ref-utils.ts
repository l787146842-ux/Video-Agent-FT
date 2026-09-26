/**
 * 分镜正文内联引用块纯工具（对齐 Flova 批）：正文里的引用 = 本镜 shotRefs
 * 在 desc 文本中的视图。
 * - 识别：shotRefs 解析为标题后在 desc 中出现的 → 内联块（最长优先防重叠误切）；
 * - 渲染：纯文本 ↔ DOM（块复用 mention-chip 概念图+名称 chip；编辑态块内带 ×）；
 * - 序列化：保存时块还原为纯名（desc 存储保持纯文本，不带 @ token）；
 * - 同步：编辑保存时 shotRefs 按「旧 − 正文已消失提及 + @ 插入」派生。
 */
import { escapeRe, makeChip, type MediaKind } from '@/lib/prompt-ref-utils';
import {
  GROUP_TITLE_PREFIX, canonicalGroupTitle, elementAliasName, elementNameVariants,
  stripTypePrefix,
} from '@/lib/group-title';
import type { ShotGroup } from '@/types';

export interface KeyElementLike {
  id?: string;
  title?: string;
  drafts?: Array<{ id?: string; imgUrl?: string }>;
}

// 标题前缀归一 + 元素名形态下沉叶子模块（2026-09-26，破 `prompt-mentions` 导入环
// 并消除 `stripTypePrefix` 的两份抄写）；此处 re-export 保持既有导入路径不变。
export { GROUP_TITLE_PREFIX, stripTypePrefix, canonicalGroupTitle, elementAliasName, elementNameVariants };

/** shotRefs 存关键元素 id（ke-xxx）或标题；统一解析为归一标题（同 ShotRefsChips 口径） */
export function resolveRefTitle(ref: string, keyElements: KeyElementLike[]): string {
  const el = resolveRefElement(ref, keyElements);
  return stripTypePrefix(el?.title || String(ref));
}

/**
 * 引用 → 关键元素组（**点击跳转链唯一入口**）。
 *
 * 2026-09-25 修（跳转不稳定根因）：此前跳转链 `ui.ts` 用**逐字比对**
 * （`k.title === title || k.id === title`），而落库引用存在裸名（`程心`）与
 * 全称（`Element_程心`）两种形态 ⇒ 裸名恒不命中，表现为「有时跳有时不跳」。
 * 平台其余各处（本文件 `elementThumb`、后端 `storyboard_ops.find_ref_group`）
 * 早已 canonical，唯独点击链漏了；本函数即把那条统一到 canonical 单一入口。
 *
 * 写口已同批归一（后端 `canonicalize_shot_refs`：落库恒为元素组全称），
 * 本函数负责**存量裸名数据**的读时兼容——两侧同契约，杜绝第四次比对式。
 */
export function resolveRefElement(
  ref: string,
  keyElements: KeyElementLike[],
): KeyElementLike | undefined {
  const raw = String(ref ?? '').trim();
  if (!raw) return undefined;
  // ① 组 id 精确命中（最高优先，无歧义）
  const byId = keyElements.find((k) => k.id === raw);
  if (byId) return byId;
  // ② 逐字标题命中（存量带前缀数据）
  const byTitle = keyElements.find((k) => k.title === raw);
  if (byTitle) return byTitle;
  // ③ canonical 命中（裸名 ↔ 带前缀双向等同）
  const key = stripTypePrefix(raw);
  return keyElements.find((k) => stripTypePrefix(k.title || '') === key);
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
 * 每个元素产**全部形态**——原全称 + 归一名字 + 括注主名（`elementNameVariants`
 * 唯一入口），Set 去重，≥2 字符守卫（此处为唯一加守卫点），
 * 按长度降序（最长优先防重叠误切）。
 * group 参数保留仅为调用点稳定，候选不再依赖 shotRefs。
 */
export function descChipNames(
  _group: Pick<ShotGroup, 'shotRefs'>,
  keyElements: KeyElementLike[],
): string[] {
  const titles = new Set<string>();
  keyElements.forEach((k) => {
    elementNameVariants(k.title || '').forEach((v) => {
      if (v.length >= 2) titles.add(v);
    });
  });
  return [...titles].sort((a, b) => b.length - a.length);
}

/** 元素首张概念图（块缩略图）；无图返回 ''（渲染为纯名块，对齐 Flova pill）。
 *  查表走 `elementNameVariants` 唯一入口：块名可能是括注主名（「艾AA」），
 *  而元素标题带容器前缀与括注（「Element_艾AA（AA）」）——2026-09-26 前只用
 *  stripTypePrefix 单式比对，主名块查不到缩略图 ⇒ 图块不显图（本次一并收敛）。 */
function elementThumb(title: string, keyElements: KeyElementLike[]): string {
  const variants = elementNameVariants(title);
  const el = keyElements.find((k) =>
    elementNameVariants(k.title || '').some((v) => variants.includes(v)));
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
    // 元素回查走**变体唯一入口**（2026-09-26）：正文可能写的是括注主名
    // （`艾AA`）而标题是 `Element_艾AA（AA）`——逐字/剥前缀两式都比不中。
    const el = keyElements.find((k) => elementNameVariants(k.title || '').includes(n));
    const canon = el?.title || n;
    if (!canon) return;
    if (boundNorm.has(stripTypePrefix(canon))) return;
    if (!auto.includes(canon)) auto.push(canon);
  });
  if (kept.length === prevRefs.length && !added.length && !auto.length) return null;
  return [...kept, ...added, ...auto];
}
