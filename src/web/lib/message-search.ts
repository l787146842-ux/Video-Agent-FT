/**
 * 消息搜索与轮次跳转的纯函数派生（长创作会话回看不靠手滚）。
 *
 * - searchMessages：大小写不敏感的正文/文档卡名匹配，返回带上下文摘录的命中；
 * - turnJumpEntries：按轮次组生成跳转条目（问/答前缀 + 首条正文摘录）。
 * 渲染与滚动定位由组件层消费（下标语义 = 原消息数组下标）。
 */
import type { ChatMessage } from '@/types';
import { groupTurns } from './turn-groups';

/** 单条搜索命中 */
export interface SearchHit {
  /** 命中原消息数组下标（滚动定位用） */
  index: number;
  sender: ChatMessage['sender'];
  /** 命中点前后截取的摘录（命中原文保留在中间） */
  snippet: string;
}

/** 轮次跳转条目 */
export interface TurnEntry {
  /** 组首消息下标（滚动定位用） */
  index: number;
  kind: 'ask' | 'answer';
  label: string;
}

/** 命中消息的可搜索文本（正文 + 文档卡名，空白扁平化为单空格便于摘录） */
function searchableText(m: ChatMessage): string {
  return `${m.text || ''}\n${m.docCard || ''}`.replace(/\s+/g, ' ').trim();
}

/** 以命中点为中心截取摘录（前后各 context 字符，超出加省略号） */
function makeSnippet(flat: string, at: number, matchLen: number, context = 18): string {
  const start = Math.max(0, at - context);
  const end = Math.min(flat.length, at + matchLen + context);
  const pre = start > 0 ? '…' : '';
  const post = end < flat.length ? '…' : '';
  return pre + flat.slice(start, end) + post;
}

/**
 * 搜索消息：trim 后空查询返回空；命中上限 limit（防超长会话一次全渲染）。
 */
export function searchMessages(
  messages: ChatMessage[], query: string, limit = 50,
): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: SearchHit[] = [];
  for (let i = 0; i < messages.length && hits.length < limit; i += 1) {
    const flat = searchableText(messages[i]);
    const at = flat.toLowerCase().indexOf(q);
    if (at < 0) continue;
    hits.push({
      index: i,
      sender: messages[i].sender,
      snippet: makeSnippet(flat, at, q.length),
    });
  }
  return hits;
}

/** 摘录长度上限（轮次跳转标签） */
const LABEL_MAX = 26;

function shortLabel(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > LABEL_MAX ? `${flat.slice(0, LABEL_MAX)}…` : flat;
}

/**
 * 轮次跳转条目：每个轮次组一条（用户组=问，agent 组=答），
 * 标签 = 组首消息正文摘录；空会话返回空。
 */
export function turnJumpEntries(messages: ChatMessage[]): TurnEntry[] {
  return groupTurns(messages)
    .map((g) => {
      const first = messages[g.indices[0]];
      if (!first) return null;
      if (g.kind === 'user') {
        return { index: g.indices[0], kind: 'ask' as const, label: shortLabel(first.text || '') };
      }
      const text = first.text || first.docCard || '';
      return { index: g.indices[0], kind: 'answer' as const, label: shortLabel(text) };
    })
    .filter((e): e is TurnEntry => e !== null && e.label !== '');
}
