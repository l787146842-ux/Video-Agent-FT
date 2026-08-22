/**
 * 聊天输入框插入请求桥接
 *
 * 左栏草稿卡片（DraftCard）右击「添加到对话」时，与右栏 ChatInput 属于不同
 * 组件树，无法直接拿到编辑器光标。这里用一个模块级 signal 队列解耦：
 * - 卡片侧调用 requestInsertMedia() 入队
 * - ChatInput 用 createEffect 跟踪队列变化，消费并插入到当前光标处
 *
 * 同时支持纯文本注入（空卡片回退为「针对草稿「xxx」：」文本引用）。
 * 用户气泡「编辑」回填请求（与排队消息编辑同款通道，
 * ChatInput 消费时走同款换行追加回填语义）。
 */
import { createSignal } from 'solid-js';
import type { InlineMedia } from '@/types';

export type InsertRequest =
  | { kind: 'media'; media: InlineMedia }
  | { kind: 'text'; text: string }
  | { kind: 'skill'; name: string }
  | { kind: 'edit_backfill'; text: string };

const [queue, setQueue] = createSignal<InsertRequest[]>([]);

/** 请求把一个内联媒体缩略块插入到聊天输入框光标处 */
export function requestInsertMedia(media: InlineMedia): void {
  setQueue((prev) => [...prev, { kind: 'media', media }]);
}

/** 请求把一段纯文本插入到聊天输入框光标处 */
export function requestInsertText(text: string): void {
  if (!text) return;
  setQueue((prev) => [...prev, { kind: 'text', text }]);
}

/** 请求把一个 Skill 引用块（图标+名称 chip）插入到聊天输入框光标处 */
export function requestInsertSkill(name: string): void {
  if (!name) return;
  setQueue((prev) => [...prev, { kind: 'skill', name }]);
}

/** 请求把已发送用户消息的正文回填到聊天输入框（用户气泡编辑控制点；
 * ChatInput 按排队消息编辑同款语义消费：换行追加、不冲掉正在输入的内容） */
export function requestEditBackfill(text: string): void {
  if (!text.trim()) return;
  setQueue((prev) => [...prev, { kind: 'edit_backfill', text }]);
}

/** 供 createEffect 跟踪的队列长度（变化即触发消费） */
export function insertRequestCount(): number {
  return queue().length;
}

/** ChatInput 消费全部待插入请求（取出并清空队列） */
export function takeInsertRequests(): InsertRequest[] {
  const cur = queue();
  if (cur.length) setQueue([]);
  return cur;
}
