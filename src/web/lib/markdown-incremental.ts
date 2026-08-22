/**
 * 增量 markdown 渲染：已完成段落缓存 + 尾段增量解析。
 *
 * 背景：流式每 120ms 全量重解析 + innerHTML 全量替换是 O(n²)，长回复掉帧。
 * 方案：按块级边界（围栏外的空行）切段——已闭合段落的 HTML 缓存后不再重解析，
 * 每 tick 只增量 parse 尾段；已闭合段与全量渲染逐字节一致，最终消息仍走
 * ChatMessageItem 全量渲染兜底（松列表等跨空行结构流式期间可能暂显拆分形态）。
 *
 * 边界处理：
 * - 未闭合代码围栏：围栏内空行不算边界，围栏起点之后的内容全部留在尾段增量解析；
 * - 表格尾段：表格行以单换行延续，最后一个空行之后（含进行中的表格）留在尾段；
 * - 文本以空行收尾：空行随前段闭合，尾段为空串（只产一次空渲染）；
 * - 高亮升级：闭合段缓存后异步做 hljs 增强并原位替换缓存值，通知宿主重渲染。
 */
import { renderMarkdown } from '@/lib/markdown';

/** 围栏开启行：至多 3 空格缩进 + ≥3 个 ` 或 ~（CommonMark 宽松匹配） */
const FENCE_OPEN_RE = /^\s{0,3}(`{3,}|~{3,})/;
/** 围栏闭合行：同字符、长度 ≥ 开启长度，行内无其它内容 */
function isFenceClose(line: string, ch: string, len: number): boolean {
  const m = /^\s{0,3}(`{3,}|~{3,})\s*$/.exec(line);
  return !!m && m[1].startsWith(ch) && m[1].length >= len;
}

/**
 * 按「围栏外空行」切段。不变式：closed.join('') + tail === src。
 * closed 每项含其后的空行分隔符（缓存键即原文切片，追加文本不改变既有键）。
 */
export function splitSegments(src: string): { closed: string[]; tail: string } {
  const closed: string[] = [];
  let segStart = 0;
  let inFence = false;
  let fenceCh = '';
  let fenceLen = 0;
  const lines = src.split('\n');
  let pos = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const next = pos + line.length + 1; // 含换行符（最后一行越界无碍，slice 会钳制）
    if (inFence) {
      if (isFenceClose(line, fenceCh, fenceLen)) inFence = false;
    } else {
      const open = FENCE_OPEN_RE.exec(line);
      if (open) {
        inFence = true;
        fenceCh = open[1][0];
        fenceLen = open[1].length;
      } else if (line.trim() === '' && i < lines.length - 1) {
        // 围栏外的空行 = 块级边界：闭合当前段（空行随段带走，保证拼接还原原文）
        closed.push(src.slice(segStart, next));
        segStart = next;
      }
    }
    pos = next;
  }
  return { closed, tail: src.slice(segStart) };
}

/** 段落缓存 + 升级订阅（宿主在升级后重渲染一次即可拿到高亮版 HTML） */
export interface IncrementalCache {
  entries: Map<string, string>;
  subscribe: (cb: () => void) => () => void;
}

/** 模块内部视角：额外携带升级通知器（不暴露到导出类型，避免宿主误用） */
interface CacheInternals extends IncrementalCache { notify: () => void; }

export function createIncrementalCache(): IncrementalCache {
  const listeners = new Set<() => void>();
  const cache: CacheInternals = {
    entries: new Map<string, string>(),
    subscribe: (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    notify: () => listeners.forEach((cb) => cb()),
  };
  return cache;
}

/** 闭合段缓存 miss 时的高亮升级（fire-and-forget）：动态 import 保持 chunk 拆分 */
function queueSegmentEnhance(cache: IncrementalCache, key: string, plainHtml: string): void {
  void import('@/lib/code-highlight').then(({ enhanceHtmlString }) => enhanceHtmlString(plainHtml))
    .then((enhanced) => {
      // 仅当缓存值仍是本次的纯 HTML 时替换（流已重启/键被覆盖则放弃）
      if (cache.entries.get(key) === plainHtml && enhanced !== plainHtml) {
        cache.entries.set(key, enhanced);
        (cache as CacheInternals).notify();
      }
    })
    .catch(() => { /* 高亮失败保留纯 HTML，不影响可读性 */ });
}

/**
 * 增量渲染：已闭合段走缓存（含高亮升级版），尾段每次全量 parse（尾段通常很短）。
 * src 为空时清空缓存（新会话/新流不复用旧段落）。
 */
export function renderMarkdownIncremental(src: string, cache: IncrementalCache): string {
  if (!src) {
    cache.entries.clear();
    return renderMarkdown(src);
  }
  const { closed, tail } = splitSegments(src);
  let html = '';
  for (const seg of closed) {
    let segHtml = cache.entries.get(seg);
    if (segHtml === undefined) {
      segHtml = renderMarkdown(seg);
      cache.entries.set(seg, segHtml);
      if (/<pre/.test(segHtml)) queueSegmentEnhance(cache, seg, segHtml);
    }
    html += segHtml;
  }
  return html + renderMarkdown(tail);
}
