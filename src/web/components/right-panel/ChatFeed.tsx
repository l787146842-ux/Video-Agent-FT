import { createEffect, createSignal, createMemo, For, Show, onCleanup } from 'solid-js';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { groupTurns } from '@/lib/turn-groups';
import { deriveAffordances } from '@/lib/message-affordances';
import { ChatMessageItem } from './ChatMessageItem';
import { StreamingIndicator } from './StreamingIndicator';
import { StreamingBubble } from './StreamingBubble';
import { AgentTimeline } from './AgentTimeline';

/** 判断是否接近底部（阈值 80px） */
function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

/**
 * 聊天消息流：<For> keyed 列表 + 智能自动滚底
 * 用户手动上滚时不强制拉底，回到底部后恢复自动滚动。
 */
export function ChatFeed() {
  let feedRef: HTMLDivElement | undefined;
  const [autoScroll, setAutoScroll] = createSignal(true);
  let rafId: number | undefined;

  // 监听用户滚动：离开底部时暂停自动滚动
  function onScroll() {
    if (feedRef) setAutoScroll(isNearBottom(feedRef));
  }

  // 消息数或流式文本变化时滚动到底部（仅 autoScroll 开启时）
  createEffect(() => {
    void chatState.messages.length;
    void chatState.streamingText;
    void chatState.streamingStatus;
    if (!autoScroll()) return;
    if (rafId !== undefined) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = undefined;
      if (feedRef) feedRef.scrollTop = feedRef.scrollHeight;
    });
  });

  onCleanup(() => { if (rafId !== undefined) cancelAnimationFrame(rafId); });

  /** 消息交互派生层（审核整改批 3：P8 收敛）：哪条消息挂哪个交互件的
   * 全部判定归 lib/message-affordances 单一纯函数（语义零变更，vitest 钉死）：
   * 确认卡目标（文档卡/图片卡追加在确认之后不顶掉引导按钮）、闸机放行目标
   * （结构化判定替代文案匹配）、建议动作目标（新用户消息即失效）、
   * 暂停卡生命周期（active/answered/expired）与已回应所选值。 */
  const affordances = createMemo(() =>
    deriveAffordances(chatState.messages, chatState.isStreaming));

  /** ：轮次分组（同 turnId 聚合，旧消息相邻兜底）——一轮的
   * 正文/文档卡/图片卡收进同一容器，消除消息流碎片化 */
  const groups = createMemo(() => groupTurns(chatState.messages));

  /** 轮次组头部信息：模型名 + 耗时 meta 上提（组内逐条不再重复渲染） */
  const turnHeader = (indices: number[]) => {
    const msgs = chatState.messages;
    let modelName = '';
    let meta = '';
    indices.forEach((i) => {
      if (!modelName && msgs[i].modelName) modelName = msgs[i].modelName || '';
      if (!meta && msgs[i].meta) meta = msgs[i].meta || '';
    });
    return { modelName: modelName || 'Agent', meta };
  };

  return (
    <div ref={feedRef} data-testid="chat-feed" class="chat-feed" onScroll={onScroll}>
      <For each={groups()}>
        {(g) => (
          <Show
            when={g.kind === 'turn'}
            fallback={
              <ChatMessageItem
                message={chatState.messages[g.indices[0]]}
                isLast={affordances()[g.indices[0]].confirmTarget}
                isGateTarget={affordances()[g.indices[0]].gateTarget}
                isSuggestedTarget={affordances()[g.indices[0]].suggestedTarget}
                editable={affordances()[g.indices[0]].editable}
                confirmState={affordances()[g.indices[0]].confirmState}
                answeredValue={affordances()[g.indices[0]].answeredValue}
              />
            }
          >
            <div class="turn-group">
              <Show when={turnHeader(g.indices).meta || g.indices.length > 1}>
                <div class="turn-group-header">
                  <span class="turn-group-model">{turnHeader(g.indices).modelName}</span>
                  <Show when={turnHeader(g.indices).meta}>
                    <span class="turn-group-meta">{turnHeader(g.indices).meta}</span>
                  </Show>
                </div>
              </Show>
              <For each={g.indices}>
                {(idx) => (
                  <ChatMessageItem
                    message={chatState.messages[idx]}
                    isLast={affordances()[idx].confirmTarget}
                    isGateTarget={affordances()[idx].gateTarget}
                    isSuggestedTarget={affordances()[idx].suggestedTarget}
                    editable={affordances()[idx].editable}
                    confirmState={affordances()[idx].confirmState}
                    answeredValue={affordances()[idx].answeredValue}
                    hideChrome
                  />
                )}
              </For>
            </div>
          </Show>
        )}
      </For>

      {/* 流式过程时间线：深度思考/工具操作实时追加（完成并入消息 trace，不重复展示） */}
      <Show when={chatState.isStreaming}>
        <div class="chat-msg agent">
          <AgentTimeline
            reasoning={() => chatState.streamingReasoning}
            items={chatState.streamingTools}
            live
            liveStatus={() => chatState.streamingStatus}
          />
        </div>
      </Show>

      {/* 流式中的临时 agent 消息（markdown 节流渲染，避免每个 delta 全量解析掉帧） */}
      <StreamingBubble />

      <StreamingIndicator />

      {/* 无消息时（如新建项目）：只在左上角淡显一句能力提示，不占对话流的完整消息卡片 */}
      <Show when={!chatState.messages.length && !chatState.isStreaming}>
        <div class="chat-feed-hint">{t('rp.feed.hint')}</div>
      </Show>
    </div>
  );
}
