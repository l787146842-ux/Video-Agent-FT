/**
 * 消息流滚动定位桥（搜索命中/轮次跳转 → ChatFeed 命令式滚动）。
 *
 * 搜索条与消息流属于不同组件树，经模块级 signal 传递跳转请求：
 * - 请求方调用 requestScrollToMessage(index)（seq 递增保证同目标可重复触发）；
 * - ChatFeed 用 createEffect 跟踪 scrollRequest()，负责展开渲染窗口、
 *   滚动到目标并做一次性高亮。
 */
import { createSignal } from 'solid-js';

/** 跳转请求（seq 单调递增，effect 据此识别新请求） */
export interface ScrollRequest {
  /** 目标消息在原数组中的下标 */
  index: number;
  seq: number;
}

const [request, setRequest] = createSignal<ScrollRequest | null>(null);
let seq = 0;

/** 请求把消息流滚动到指定下标的消息（并短暂高亮） */
export function requestScrollToMessage(index: number): void {
  seq += 1;
  setRequest({ index, seq });
}

/** ChatFeed 侧读取当前请求（响应式） */
export function scrollRequest(): ScrollRequest | null {
  return request();
}
