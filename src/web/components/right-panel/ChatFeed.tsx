import { createEffect, createSignal, createMemo, For, Show, onCleanup } from 'solid-js';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { groupTurns, type TurnGroup } from '@/lib/turn-groups';
import { deriveAffordances } from '@/lib/message-affordances';
import { ChatMessageItem } from './ChatMessageItem';
import { StreamingIndicator } from './StreamingIndicator';
import { StreamingBubble } from './StreamingBubble';
import { AgentTimeline } from './AgentTimeline';

/** 判断是否接近底部（阈值 80px） */
function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

/** 钉底后的跟随帧预算：content-visibility 占位高度逐段兑现（每轮布局只展开
 * 视口能容下的条目），长内容需要多轮「钉底→撑开→再钉底」才真正到底；
 * 高度一稳定即早停，预算只是上限（jsdom 静态几何首帧即停，不受影响） */
const PIN_FOLLOWUP_FRAMES = 64;

/**
 * 聊天消息流：<For> keyed 列表 + 智能自动滚底
 * 用户手动上滚时不强制拉底，回到底部后恢复自动滚动。
 */
export function ChatFeed() {
  let feedRef: HTMLDivElement | undefined;
  const [autoScroll, setAutoScroll] = createSignal(true);
  let rafId: number | undefined;
  /** 程序化钉底进行中标记：钉底赋值 scrollTop 引发的 scroll 事件异步派发，
   *  期间不得据其翻转 autoScroll（钳制事件离底很远，会把跟随自锁死） */
  let pinning = false;
  let followupLeft = 0;
  let lastPinnedHeight = 0;

  // 监听用户滚动：离开底部时暂停自动滚动（钉底期间的事件跳过）
  function onScroll() {
    if (!feedRef || pinning) return;
    setAutoScroll(isNearBottom(feedRef));
  }

  /** 钉底一帧；之后逐帧检测布局兑现——高度仍在增长则继续钉底 */
  function pinToBottom() {
    if (!feedRef) return;
    pinning = true;
    feedRef.scrollTop = feedRef.scrollHeight;
    lastPinnedHeight = feedRef.scrollHeight;
    if (followupLeft > 0) {
      followupLeft -= 1;
      rafId = requestAnimationFrame(() => {
        rafId = undefined;
        if (feedRef && feedRef.scrollHeight !== lastPinnedHeight) pinToBottom();
        else pinning = false;
      });
    } else {
      pinning = false;
    }
  }

  // 消息数或流式文本变化时滚动到底部（仅 autoScroll 开启时）
  createEffect(() => {
    void chatState.messages.length;
    void chatState.streamingText;
    void chatState.streamingStatus;
    if (!autoScroll()) return;
    followupLeft = PIN_FOLLOWUP_FRAMES;
    if (rafId !== undefined) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = undefined;
      pinToBottom();
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
   * 正文/文档卡/图片卡收进同一容器，消除消息流碎片化。
   * P4 滚底回归修复：groupTurns 每次返回全新对象，而 Solid <For> 按对象
   * identity diff——引用不稳导致每条消息变化都全树拆建，content-visibility
   * 高度缓存随之失效，滚底 effect 读到的 scrollHeight 塌缩为占位估算值，
   * 钉底钉在错的高度上，真实布局撑开后视口停回顶部。此处对结构未变的组
   * 复用旧引用（组内下标恒为连续区间，首下标+长度相等即同组），<For>
   * 只做尾部增量 diff，既有节点与其高度缓存全部保留。 */
  let lastGroups: TurnGroup[] = [];
  const groups = createMemo(() => {
    const next = groupTurns(chatState.messages);
    const prev = lastGroups;
    const out: TurnGroup[] = [];
    for (let i = 0; i < next.length; i += 1) {
      const n = next[i];
      const p = prev[i];
      if (p && p.kind === n.kind && p.turnId === n.turnId
        && p.indices.length === n.indices.length
        && p.indices[0] === n.indices[0]) {
        out.push(p);
      } else {
        out.push(n);
      }
    }
    lastGroups = out;
    return out;
  });

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
