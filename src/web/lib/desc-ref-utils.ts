/**
 * 分镜正文内联引用块纯工具（对齐 Flova 批）：正文里的引用 = 本镜 sceneRefs
 * 在 desc 文本中的视图。
 * - 识别：sceneRefs 解析为标题后在 desc 中出现的 → 内联块（最长优先防重叠误切）；
 * - 渲染：纯文本 ↔ DOM（块复用 mention-chip 概念图+名称 chip；编辑态块内带 ×）；
 * - 序列化：保存时块还原为纯名（desc 存储保持纯文本，不带 @ token）；
 * - 同步：编辑保存时 sceneRefs 按「旧 − 正文已消失提及 + @ 插入」派生。
 */
import { escapeRe, makeChip, type MediaKind } from '@/lib/prompt-ref-utils';
import type { ShotGroup } from '@/types';

export interface KeyElementLike {
  id?: string;
  title?: string;
  drafts?: Array<{ imgUrl?: string }>;
}

/**
 * 前端归一单一事实源：剥离中文类别前缀（“角色：”/“场景:”/“道具1” 等），
 * 使数据层的类别化标题与正文里的裸名对齐（如 “角色：程心” → “程心”）。
 * 正则与中文集与后端 A1 契约完全一致（CN_CAT_PREFIX_RE / TITLE_CJK_RE）：
 * 可选前缀 元素|关键元素 + 类别词 场景|道具|人物|角色|音频|载具 + 后缀（编号分支或冒号分支）。
 * 三不变量：① 只剥不加；② 剥后为空则返原文；③ 剥后无中文字符则返原文。
 */
export function stripCategoryPrefix(title: string): string {
  if (!title) return title;
  const stripped = title.replace(
    /^(?:元素|关键元素)?(?:场景|道具|人物|角色|音频|载具)(?:[_\-\s]?\d+\s*|\s*[：:]\s*)/,
    '',
  );
  if (!stripped) return title;                          // 剥后为空 → 返原文
  if (!/[\u4e00-\u9fff]/.test(stripped)) return title;  // 剥后无中文 → 返原文
  return stripped;                                      // 只剥不加
}

/** sceneRefs 存关键元素 id（ke-xxx）或标题；统一解析为归一标题（同 SceneRefsChips 口径） */
export function resolveRefTitle(ref: string, keyElements: KeyElementLike[]): string {
  const el = keyElements.find((k) => k.id === ref || k.title === ref);
  return stripCategoryPrefix(el?.title || String(ref));
}

/**
 * K7 批（2026-09-16）：显示标题归一单一事实源——GroupHeader / SceneRefsChips
 * 本地副本收敛到本函数：① 剥英文标识前缀（Element_/Shot_ 等：字母组+必需
 * 分隔符，防误剥 S1 星环号球形舱 类混合标题）；② 剥中文类别前缀（同
 * stripCategoryPrefix 正则与三不变量）；③ 去非中文字符（下划线/字母数字
 * 噪声，口径同 b6011a5：月球_基地 → 月球基地），但无下划线且无英文前缀的
 * 混合标题（AA（双A））原样保留；结果为空回退原文。仅显示层归一，
 * 数据层标题原样存储（台账 #10）。
 */
export function normalizeDisplayTitle(title: string): string {
  const raw = String(title || '');
  if (!raw) return raw;
  const en = raw.replace(/^[A-Za-z]+[_\-\s]+/, '').trim();
  const cat = stripCategoryPrefix(en);
  const ident = cat
    .split('_')
    .filter((seg) => /[\u4e00-\u9fff]/.test(seg))
    .join('')
    .trim();
  return ident || cat || raw;
}

/**
 * 内联块候选名：候选源 = keyElements 全集（不再局限本镜 sceneRefs）。
 * 每个元素产两种形态——原全称 + 归一裸名（stripCategoryPrefix），Set 去重，
 * ≥2 字符守卫（此处为唯一加守卫点），按长度降序（最长优先防重叠误切）。
 * group 参数保留仅为调用点稳定，候选不再依赖 sceneRefs。
 */
export function descChipNames(
  _group: Pick<ShotGroup, 'sceneRefs'>,
  keyElements: KeyElementLike[],
): string[] {
  const titles = new Set<string>();
  keyElements.forEach((k) => {
    const raw = k.title;
    if (!raw) return;
    if (raw.length >= 2) titles.add(raw);            // 原全称
    const bare = stripCategoryPrefix(raw);
    if (bare.length >= 2) titles.add(bare);          // 归一裸名
  });
  return [...titles].sort((a, b) => b.length - a.length);
}

/** 元素首张概念图（块缩略图）；无图返回 ''（渲染为纯名块，对齐 Flova pill）。
 *  查表按归一标题比对：块名可能是裸名（“程心”），元素标题可能是类别全称（“角色：程心”）。 */
function elementThumb(title: string, keyElements: KeyElementLike[]): string {
  const norm = stripCategoryPrefix(title);
  const el = keyElements.find((k) => stripCategoryPrefix(k.title || '') === norm);
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

/** 编辑保存时 sceneRefs 同步：新 = 旧 − 正文已消失提及的引用 + @ 插入的标题
 *  + 裸名提及 auto 源（K4 批 2026-09-16 对齐 flova：提及即绑定）。
 *  无增删返回 null（调用方不必写库）。 */
export function syncSceneRefsAfterEdit(
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
    ...added.map((t) => stripCategoryPrefix(String(t))),
  ]);
  const auto: string[] = [];
  descChipNames({ sceneRefs: [] }, keyElements).forEach((n) => {
    if (!serializedText.includes(n)) return;
    const el = keyElements.find(
      (k) => k.title === n || stripCategoryPrefix(k.title || '') === n);
    const canon = el?.title || n;
    if (!canon) return;
    if (boundNorm.has(stripCategoryPrefix(canon))) return;
    if (!auto.includes(canon)) auto.push(canon);
  });
  if (kept.length === prevRefs.length && !added.length && !auto.length) return null;
  return [...kept, ...added, ...auto];
}
