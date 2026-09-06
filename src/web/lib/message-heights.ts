/**
 * 消息高度缓存：content-visibility 占位校准（治长会话滚动跳变）。
 *
 * 背景：长会话虚拟化给屏外消息按 contain-intrinsic-size: auto 120px 占位，
 * 真实高度常达数百上千 px，滚动进入视口的瞬间逐条撑高总高度；叠加
 * .chat-feed overflow-anchor:none（钉底优先的既定取舍，见 224626a），
 * 表现为滚轮/拖滚动条「跳很远」。业界标准解法（csswg-drafts#7807 / web.dev）
 * 是量出真实高度回填占位，而非调锚定——本模块即「量身高记小本本」。
 *
 * 占位高度三层来源（取首个命中）：
 *   1. localStorage 缓存：本机真实渲染过的消息（跨刷新永久精准）；
 *   2. 内容形态启发式估算：没量过的按字数/行数/卡片粗估，
 *      把误差从「几十倍」压到「几成」；
 *   3. CSS 兜底 120px（chat-feed-core.css，仅无 JS 环境生效）。
 *
 * 缓存键 = 内容形态摘要（sender/kind/字数/头部/卡片判别），刻意不含 ts/meta
 * 等本地易变字段（后端历史无 ts，含了会让重载后全部 miss）；改写/截断重答/
 * 历史压缩后内容变 → 键变 → 自动失效，不依赖会随插入漂移的数组下标。
 * 键碰撞只会让近似消息复用近似高度，无实害。
 */
import type { ChatMessage } from '@/types';

const LS_KEY = 'ftdyb.msg-heights.v1';
/** 缓存条目上限（最旧先出；一条约 100B，500 条 ≈ 50KB） */
const MAX_ENTRIES = 500;
/** 估算下限 = CSS 兜底值（保持与 chat-feed-core.css 一致） */
const MIN_HEIGHT = 120;
/** 估算上限：超长文本一律封顶（RO 渲染后即以真实值为准） */
const MAX_ESTIMATE = 8000;
/** 真实高度入缓存的下限：低于此视为量测噪声不入库 */
const CACHE_MIN = 40;
/** 估算常数：13px 字号 × 1.55 行高 ≈ 20px/行 */
const LINE_H = 20;
/** 气泡内每行可容字符量级（88% 面板宽、CJK 13px 的中庸取值） */
const CHARS_PER_LINE = 30;
/** 气泡内边距 + 元信息行等固定余量 */
const CHROME_H = 44;
/** 卡片单元粗估高（文档卡/确认卡/账本卡/媒体卡折算） */
const CARD_H = 170;
/** 回填落盘防抖间隔 */
const SAVE_DEBOUNCE_MS = 600;

const heights = new Map<string, number>();
let loaded = false;
let saveTimer: ReturnType<typeof setTimeout> | undefined;

function load(): void {
  if (loaded) return;
  loaded = true;
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    for (const [k, v] of Object.entries(JSON.parse(raw) as Record<string, number>)) {
      if (typeof v === 'number' && v >= CACHE_MIN) heights.set(k, v);
    }
  } catch { /* 隐私模式/数据损坏：降级为纯内存估算 */ }
}

function scheduleSave(): void {
  if (saveTimer !== undefined) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = undefined;
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(Object.fromEntries(heights)));
    } catch { /* 配额满/隐私模式：保留内存缓存即可 */ }
  }, SAVE_DEBOUNCE_MS);
}

/** 真实高度回填入口（trackMessageHeight 内部调用；导出供单测） */
export function rememberHeight(key: string, h: number): void {
  if (!key || h < CACHE_MIN) return;
  const prev = heights.get(key);
  if (prev !== undefined && Math.abs(prev - h) < 2) return;
  heights.delete(key); // 重插刷新最旧顺位（Map 按插入序淘汰）
  heights.set(key, h);
  while (heights.size > MAX_ENTRIES) {
    const oldest = heights.keys().next().value;
    if (oldest === undefined) break;
    heights.delete(oldest);
  }
  scheduleSave();
}

interface MsgShape {
  sender: string;
  kind: string;
  head: string;
  chars: number;
  hardLines: number;
  cardUnits: number;
  flags: boolean[];
  counts: number[];
}

/** 内容形态提取：键与估算共用同一摘要，保证「键相同 ⇔ 形态相同」 */
function shapeOf(msg: ChatMessage): MsgShape {
  const text = msg.text || '';
  let cardUnits = 0;
  if (msg.docCard) cardUnits += 2;
  if (msg.imageCard || msg.videoCard) cardUnits += 2.5; // 含媒体预览区
  if (msg.confirm || msg.decisionForm || msg.confirmOptions?.length) cardUnits += 2;
  cardUnits += (msg.actionLog?.length ?? 0) * 0.5;
  cardUnits += (msg.docBlocks?.length ?? 0) + (msg.skillBlocks?.length ?? 0);
  cardUnits += (msg.parts ?? []).filter((p) => p.type !== 'text').length * 0.5;
  cardUnits += (msg.warnings?.length ?? 0) * 0.15;
  if (msg.errorDetail) cardUnits += 1;
  return {
    sender: msg.sender,
    kind: msg.kind ?? '',
    head: text.slice(0, 64),
    chars: text.length,
    hardLines: text ? text.split('\n').length : 0,
    cardUnits,
    flags: [
      Boolean(msg.docCard), Boolean(msg.imageCard), Boolean(msg.videoCard),
      Boolean(msg.confirm || msg.decisionForm), Boolean(msg.errorDetail),
      Boolean(msg.settingsHint), Boolean(msg.snapshotId),
    ],
    counts: [
      msg.confirmOptions?.length ?? 0, msg.actionLog?.length ?? 0,
      msg.docBlocks?.length ?? 0, msg.skillBlocks?.length ?? 0,
      msg.parts?.length ?? 0,
    ],
  };
}

/** 内容形态摘要键：改写/截断/压缩后自动失效的稳定性由「内容即键」保证 */
export function messageHeightKey(msg: ChatMessage): string {
  const s = shapeOf(msg);
  return [s.sender, s.kind, s.chars, s.head, ...s.flags.map(Number), ...s.counts].join('|');
}

/** 没量过的消息按内容形态粗估（首翻误差从几十倍压到几成；渲染后即被真实值取代） */
export function estimateMessageHeight(msg: ChatMessage): number {
  const s = shapeOf(msg);
  const wrapLines = Math.ceil(s.chars / CHARS_PER_LINE);
  const lines = Math.max(s.hardLines, wrapLines);
  const h = CHROME_H + Math.max(0, lines - 1) * LINE_H + s.cardUnits * CARD_H;
  return Math.min(MAX_ESTIMATE, Math.max(MIN_HEIGHT, Math.round(h)));
}

/** 消息的 contain-intrinsic-size 值（inline 覆写 CSS 兜底；缓存 → 估算 顺位） */
export function messageIntrinsicSize(msg: ChatMessage): string {
  load();
  const cached = heights.get(messageHeightKey(msg));
  return `auto ${cached ?? estimateMessageHeight(msg)}px`;
}

let sharedRO: ResizeObserver | undefined;
const keyFns = new WeakMap<Element, () => string>();

function onROEntries(entries: ResizeObserverEntry[]): void {
  for (const entry of entries) {
    const keyOf = keyFns.get(entry.target);
    if (!keyOf) continue;
    rememberHeight(keyOf(), Math.round(entry.target.getBoundingClientRect().height));
  }
}

/** 消息根元素挂共享 ResizeObserver：真实渲染（含从占位展开）时回填缓存。
 *  keyOf 取 getter——消息对象原地更新（如确认卡 appliedActions）时键实时取新。
 *  无 ResizeObserver 环境（jsdom/老浏览器）返回 no-op，功能降级为纯估算。 */
export function trackMessageHeight(el: HTMLElement, keyOf: () => string): () => void {
  if (typeof ResizeObserver === 'undefined') return () => {};
  if (!sharedRO) sharedRO = new ResizeObserver(onROEntries);
  keyFns.set(el, keyOf);
  sharedRO.observe(el);
  return () => {
    keyFns.delete(el);
    sharedRO?.unobserve(el);
  };
}
