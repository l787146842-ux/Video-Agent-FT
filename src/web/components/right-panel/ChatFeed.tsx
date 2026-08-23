import { createEffect, createSignal, createMemo, For, Show, onCleanup } from 'solid-js';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { groupTurns, stabilizeGroups, type TurnGroup } from '@/lib/turn-groups';
import { deriveAffordances } from '@/lib/message-affordances';
import { computeFeedStart, expandFeedWindow, extraForIndex } from '@/lib/feed-window';
import { scrollRequest } from '@/lib/chat/chat-scroll-bridge';
import { ChatMessageItem } from './ChatMessageItem';
import { StreamingIndicator } from './StreamingIndicator';
import { StreamingBubble } from './StreamingBubble';
import { AgentTimeline } from './AgentTimeline';
import { StageProgressBar } from './StageProgressBar';
import { EmptyStateCard } from './EmptyStateCard';

/** 判断是否接近底部（阈值 80px） */
function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

/** 钉底后的跟随帧预算：content-visibility 占位高度逐段兑现（每轮布局只展开
 * 视口能容上的条目），长内容需要多轮「钉底→撑开→再钉底」才真正到底；
 * 高度一稳定即早停，预算只是上限（jsdom 静态几何首帧即停，不受影响） */
const PIN_FOLLOWUP_FRAMES = 64;
/** 搜索定位高亮时长（一次性闪烁后摘除） */
const FLASH_MS = 1600;

/**
 * 聊天消息流：<For> keyed 列表 + 智能自动滚底 + 窗口化渲染。
 * 用户手动上滚时不强制拉底，回到底部后恢复自动滚动；
 * 长会话只渲染近段消息（feed-window），向前按需展开，DOM 节点数封顶。
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

  /** 渲染窗口：只渲染近段消息，start 之前的头部折叠为「显示更早」按钮；
   * 会话清空（切换/新建）时展开量复位 */
  const [extra, setExtra] = createSignal(0);
  const start = createMemo(() => computeFeedStart(chatState.messages.length, extra()));
  createEffect(() => { if (!chatState.messages.length && extra() > 0) setExtra(0); });

  /** 向前展开一批：补偿 scrollTop，视口内容不跳位 */
  function showEarlier() {
    const el = feedRef;
    const before = el ? el.scrollHeight : 0;
    setExtra(expandFeedWindow(extra()));
    requestAnimationFrame(() => {
      if (el) el.scrollTop += el.scrollHeight - before;
    });
  }

  /** 搜索/轮次跳转：先展开窗口纳入目标，两帧后定位滚动并一次性高亮 */
  createEffect(() => {
    const req = scrollRequest();
    if (!req) return;
    const total = chatState.messages.length;
    if (req.index < 0 || req.index >= total) return;
    const need = extraForIndex(req.index, total);
    if (need > extra()) setExtra(need);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const el = feedRef?.querySelector(`[data-msg-index="${req.index}"]`);
      if (!(el instanceof HTMLElement)) return;
      el.scrollIntoView?.({ block: 'center' });
      el.classList.add('search-flash');
      setTimeout(() => el.classList.remove('search-flash'), FLASH_MS);
    }));
  });

  /** 消息交互派生层：哪条消息挂哪个交互件的全部判定归
   * lib/message-affordances 单一纯函数（全量消息口径，按下标消费） */
  const affordances = createMemo(() =>
    deriveAffordances(chatState.messages, chatState.isStreaming));

  /** 轮次分组（窗口切片口径；组引用经 stabilizeGroups 稳定化，
   * <For> 只做尾部增量 diff，content-visibility 高度缓存不失效）。
   * 注意：g.indices 为窗口内局部下标，全局下标 = start() + 局部下标 */
  let lastGroups: TurnGroup[] = [];
  const groups = createMemo(() => {
    const visible = chatState.messages.slice(start());
    const next = stabilizeGroups(lastGroups, groupTurns(visible));
    lastGroups = next;
    return next;
  });

  /** 轮次组头部信息：模型名 + 耗时 meta 上提（组内逐条不再重复渲染） */
  const turnHeader = (indices: number[]) => {
    const msgs = chatState.messages;
    const offset = start();
    let modelName = '';
    let meta = '';
    indices.forEach((i) => {
      if (!modelName && msgs[offset + i].modelName) modelName = msgs[offset + i].modelName || '';
      if (!meta && msgs[offset + i].meta) meta = msgs[offset + i].meta || '';
    });
    return { modelName: modelName || 'Agent', meta };
  };

  return (
    <div
      ref={feedRef}
      data-testid="chat-feed"
      class="chat-feed"
      /* 推理中消息流标忙碌态，读屏器可据此延迟播报增量 */
      aria-busy={chatState.isStreaming}
      onScroll={onScroll}
    >
      {/* 窗口化：头部折叠区入口（展开补偿 scrollTop，视口不跳位） */}
      <Show when={start() > 0}>
        <button type="button" class="feed-show-earlier" onClick={showEarlier}>
          {t('rp.feed.showEarlier', { n: start() })}
        </button>
      </Show>

      <For each={groups()}>
        {(g) => (
          <Show
            when={g.kind === 'turn'}
            fallback={
              <ChatMessageItem
                message={chatState.messages[start() + g.indices[0]]}
                isLast={affordances()[start() + g.indices[0]].confirmTarget}
                isGateTarget={affordances()[start() + g.indices[0]].gateTarget}
                isSuggestedTarget={affordances()[start() + g.indices[0]].suggestedTarget}
                editable={affordances()[start() + g.indices[0]].editable}
                regenerable={affordances()[start() + g.indices[0]].regenerable}
                branchable={affordances()[start() + g.indices[0]].branchable}
                copyable={affordances()[start() + g.indices[0]].copyable}
                docSavable={affordances()[start() + g.indices[0]].docSavable}
                confirmState={affordances()[start() + g.indices[0]].confirmState}
                answeredValue={affordances()[start() + g.indices[0]].answeredValue}
                domIndex={start() + g.indices[0]}
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
                    message={chatState.messages[start() + idx]}
                    isLast={affordances()[start() + idx].confirmTarget}
                    isGateTarget={affordances()[start() + idx].gateTarget}
                    isSuggestedTarget={affordances()[start() + idx].suggestedTarget}
                    editable={affordances()[start() + idx].editable}
                    regenerable={affordances()[start() + idx].regenerable}
                    branchable={affordances()[start() + idx].branchable}
                    copyable={affordances()[start() + idx].copyable}
                    docSavable={affordances()[start() + idx].docSavable}
                    confirmState={affordances()[start() + idx].confirmState}
                    answeredValue={affordances()[start() + idx].answeredValue}
                    domIndex={start() + idx}
                    hideChrome
                  />
                )}
              </For>
            </div>
          </Show>
        )}
      </For>

      {/* 流式过程：阶段进度条 + 深度思考/工具操作时间线（完成并入消息 trace，不重复展示） */}
      <Show when={chatState.isStreaming}>
        <div class="chat-msg agent">
          <StageProgressBar />
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

      {/* 无消息时（如新建项目）：引导卡（能力提示 + 示例指令，点击即发送） */}
      <Show when={!chatState.messages.length && !chatState.isStreaming}>
        <EmptyStateCard />
      </Show>
    </div>
  );
}
