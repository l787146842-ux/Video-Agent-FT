import { createSignal, Show } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { adjustScopeActions, type AdjustScopeTarget } from '@/stores/adjust-scopes';
import type { Draft, DraftType } from '@/types';

/**
 * 组级微调输入行。
 * 挂在分组底部占满组宽；仅悬停卡片时原位展开（收起态 pointer-events:none），
 * 内容跟随当前悬停的卡（每张卡的输入各自保存互不干扰）；聚焦输入期间保持可见。
 * 每张草稿卡独立的微调输入内容（组内多卡各自微调互不干扰）。
 *
 * 发送通道（批 S3 微调真子对话）：提交走 openThread + sendAdjust——幂等取/建
 * 隐藏线程并直起 scope 任务（事件进浮窗不进主聊天区）；线程接口失败
 * （4xx/契约字段缺失，含旧后端无接口）回落旧 sendUserMessage 拼文本路径。
 * 重入即重开（任务 #19）：聚焦输入框/空文本点微调按钮即 openThread 重开浮窗
 * 并装载历史（不提交也开）；关闭浮窗后再点入口能找回刚才的对话。
 */
export function GroupAdjustBox(props: {
  drafts: Draft[];
  /** 分组所属类别（scope.cat，与 Agent 上下文口径一致） */
  type: DraftType;
  /** 分组 id（scope.group_id） */
  groupId: string;
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

  const clearText = (draftId: string) => {
    setAdjustTexts((prev) => ({ ...prev, [draftId]: '' }));
  };

  /** 旧路径（回落）：拼定位文本进主对话 */
  function sendLegacy(code: string, text: string) {
    sendUserMessage(
      `对${props.adjustLabel}列表${props.index()}「${props.groupTitle()}」的第 ${code} 卡提出微调意见：${text}`,
    );
  }

  /** 当前生效卡的微调目标定位（提交/重入共用同一形态，幂等键一致） */
  function scopeTarget(draftId: string, code: string): AdjustScopeTarget {
    return {
      kind: 'adjust',
      cat: props.type,
      group_id: props.groupId,
      draft_id: draftId,
      label: `${props.groupTitle()} 第 ${code} 卡`,
    };
  }

  /** 重入打开浮窗（不提交）：幂等取/建线程并装载历史；失败静默不打扰输入 */
  function reopenThread() {
    const d = activeDraft();
    if (!d) return;
    void adjustScopeActions.openThread(scopeTarget(d.id, activeCode()));
  }

  /** 对指定草稿卡发送微调意见（定位到卡而非「当前草稿」，组内多卡时不会改错卡）：
   *  先幂等取/建线程并弹浮窗，再向线程提交 scope 任务；提交后自动弹浮窗（=open）。
   *  空文本 = 重开浮窗装载历史（任务 #19：不提交也开），不发送空消息。 */
  async function sendAdjustFor(draftId: string, code: string) {
    const text = (adjustTexts()[draftId] || '').trim();
    if (!text) {
      await adjustScopeActions.openThread(scopeTarget(draftId, code));
      return;
    }
    const target = scopeTarget(draftId, code);
    // 探测/回落：线程接口失败（4xx/契约字段缺失）→ 回落旧拼文本路径
    const opened = await adjustScopeActions.openThread(target);
    if (!opened) {
      sendLegacy(code, text);
      clearText(draftId);
      return;
    }
    // 同目标运行中拒重复提交（sendAdjust 内守卫 + toast；未受理时保留输入）
    const sent = adjustScopeActions.sendAdjust(target, text);
    if (sent) clearText(draftId);
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
          onFocus={() => reopenThread()}
          onInput={(e) => {
            const id = activeDraft()?.id || '';
            setAdjustTexts((prev) => ({ ...prev, [id]: e.currentTarget.value }));
          }}
          onKeyDown={(e) => {
            const d = activeDraft();
            if (e.key === 'Enter' && d) void sendAdjustFor(d.id, activeCode());
          }}
        />
        <button
          type="button"
          class="card-adjust-btn"
          onClick={() => { const d = activeDraft(); if (d) void sendAdjustFor(d.id, activeCode()); }}
        >
          微调
        </button>
      </div>
    </Show>
  );
}
