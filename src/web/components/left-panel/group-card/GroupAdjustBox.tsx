import { createSignal, Show } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import type { Draft } from '@/types';

/**
 * 组级微调输入行。
 * 挂在分组底部占满组宽；仅悬停卡片时原位展开（收起态 pointer-events:none），
 * 内容跟随当前悬停的卡（每张卡的输入各自保存互不干扰）；聚焦输入期间保持可见。
 * 每张草稿卡独立的微调输入内容（组内多卡各自微调互不干扰）。
 */
export function GroupAdjustBox(props: {
  drafts: Draft[];
  /** 分组在列表中的序号（accessor：排序后须响应式刷新） */
  index: () => number;
  groupTitle: () => string;
  adjustLabel: string;
  /** 当前悬停的草稿卡 id（未悬停时默认第一张） */
  hoverDraftId: () => string;
  cardsHover: () => boolean;
  setCardsHover: (v: boolean) => void;
  /** 把输入框容器元素注册给父组件（卡片行移出判定用） */
  registerRef: (el: HTMLDivElement) => void;
}) {
  const [adjustTexts, setAdjustTexts] = createSignal<Record<string, string>>({});

  /** 当前生效的微调目标卡：跟随悬停的卡（悬停切换时输入内容随之切换），
   * 未悬停过默认第一张 */
  const activeDraft = () =>
    props.drafts.find((d) => d.id === props.hoverDraftId()) || props.drafts[0];
  /** 生效卡的小标编号（组号-卡序号，与 Agent 上下文对齐） */
  const activeCode = () => {
    const d = activeDraft();
    const idx = d ? props.drafts.findIndex((x) => x.id === d.id) : -1;
    return idx >= 0 ? `${props.index()}-${idx + 1}` : '';
  };

  /** 对指定草稿卡发送微调意见（定位到卡而非「当前草稿」，组内多卡时不会改错卡） */
  function sendAdjustFor(draftId: string, code: string) {
    const text = (adjustTexts()[draftId] || '').trim();
    if (!text) return;
    // 用分组标题 + 卡编号，让 Agent 能准确定位
    sendUserMessage(
      `对${props.adjustLabel}列表${props.index()}「${props.groupTitle()}」的第 ${code} 卡提出微调意见：${text}`,
    );
    setAdjustTexts((prev) => ({ ...prev, [draftId]: '' }));
  }

  return (
    <Show when={props.drafts.length > 0}>
      <div
        ref={(el) => props.registerRef(el)}
        class={`card-adjust-box ${props.cardsHover() ? 'open' : ''}`}
        onMouseEnter={() => props.setCardsHover(true)}
      >
        <input
          type="text"
          class="card-adjust-input"
          placeholder={`对第 ${activeCode()} 卡提出修改意见…`}
          value={adjustTexts()[activeDraft()?.id || ''] || ''}
          onInput={(e) => {
            const id = activeDraft()?.id || '';
            setAdjustTexts((prev) => ({ ...prev, [id]: e.currentTarget.value }));
          }}
          onKeyDown={(e) => {
            const d = activeDraft();
            if (e.key === 'Enter' && d) sendAdjustFor(d.id, activeCode());
          }}
        />
        <button
          type="button"
          class="card-adjust-btn"
          onClick={() => { const d = activeDraft(); if (d) sendAdjustFor(d.id, activeCode()); }}
        >
          微调
        </button>
      </div>
    </Show>
  );
}
