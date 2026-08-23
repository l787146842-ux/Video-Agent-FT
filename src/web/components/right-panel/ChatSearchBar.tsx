import { createMemo, createSignal, For, Show, onMount } from 'solid-js';
import { FiSearch, FiX } from 'solid-icons/fi';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import {
  searchMessages, turnJumpEntries, type SearchHit, type TurnEntry,
} from '@/lib/message-search';
import { requestScrollToMessage } from '@/lib/chat/chat-scroll-bridge';

/**
 * 消息搜索与轮次跳转条（会话标签栏下方展开）：
 * - 有查询词：全文搜索消息（正文/文档卡名），命中即跳转并高亮；
 * - 无查询词：列出全部轮次组（问/答摘录），点击跳转到该轮开头。
 * 滚动定位经 chat-scroll-bridge 委托 ChatFeed（含渲染窗口按需展开）。
 */
export function ChatSearchBar(props: { onClose: () => void }) {
  const [query, setQuery] = createSignal('');
  let inputRef: HTMLInputElement | undefined;
  onMount(() => inputRef?.focus());

  const hits = createMemo<SearchHit[]>(() => searchMessages(chatState.messages, query()));
  const turns = createMemo<TurnEntry[]>(() => turnJumpEntries(chatState.messages));
  const hasQuery = createMemo(() => query().trim() !== '');

  const jumpTo = (index: number) => {
    requestScrollToMessage(index);
    props.onClose();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      props.onClose();
      return;
    }
    // Enter：跳到当前列表第一条（有搜索结果优先）
    if (e.key === 'Enter') {
      e.preventDefault();
      const first = hasQuery() ? hits()[0]?.index : turns()[0]?.index;
      if (first !== undefined) jumpTo(first);
    }
  };

  return (
    <div class="chat-search-bar" role="search" onKeyDown={onKeyDown}>
      <div class="chat-search-input-row">
        <FiSearch size={13} class="chat-search-icon" />
        <input
          ref={inputRef}
          class="chat-search-input"
          type="text"
          value={query()}
          placeholder={t('rp.search.placeholder')}
          aria-label={t('rp.search.open')}
          onInput={(e) => setQuery(e.currentTarget.value)}
        />
        <button
          type="button"
          class="chat-search-close"
          title={t('rp.lightbox.close')}
          onClick={() => props.onClose()}
        >
          <FiX size={14} />
        </button>
      </div>

      {/* 搜索结果（有查询词时） */}
      <Show when={hasQuery()}>
        <div class="chat-search-section-title">{t('rp.search.results')}</div>
        <Show
          when={hits().length > 0}
          fallback={<div class="chat-search-empty">{t('rp.search.noResult')}</div>}
        >
          <div class="chat-search-list" role="listbox" aria-label={t('rp.search.results')}>
            <For each={hits()}>
              {(hit) => (
                <button
                  type="button"
                  role="option"
                  aria-selected="false"
                  class="chat-search-item"
                  onClick={() => jumpTo(hit.index)}
                >
                  <span class={`chat-search-tag ${hit.sender === 'user' ? 'ask' : 'answer'}`}>
                    {hit.sender === 'user' ? t('rp.search.ask') : t('rp.search.answer')}
                  </span>
                  <span class="chat-search-snippet">{hit.snippet}</span>
                </button>
              )}
            </For>
          </div>
        </Show>
      </Show>

      {/* 轮次跳转（无查询词时） */}
      <Show when={!hasQuery() && turns().length > 0}>
        <div class="chat-search-section-title">{t('rp.search.turns')}</div>
        <div class="chat-search-list" role="listbox" aria-label={t('rp.search.turns')}>
          <For each={turns()}>
            {(entry) => (
              <button
                type="button"
                role="option"
                aria-selected="false"
                class="chat-search-item"
                onClick={() => jumpTo(entry.index)}
              >
                <span class={`chat-search-tag ${entry.kind}`}>
                  {entry.kind === 'ask' ? t('rp.search.ask') : t('rp.search.answer')}
                </span>
                <span class="chat-search-snippet">{entry.label}</span>
              </button>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
}
