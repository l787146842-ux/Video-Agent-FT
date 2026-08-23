/**
 * 建议动按钮条（任务 #17：错误/停止气泡的唯一建议渲染通道）。
 *
 * 读消息持久化的 suggestedActions（刷新后不丢）：
 * - retry = 机械重发最近用户消息原内容（「继续刚才的任务」沿用此语义）
 * - continue/next = 发送后端下发的固定 value（人类可读护栏在 suggested-guard）
 */
import { For } from 'solid-js';
import { sendUserMessage } from '@/lib/agent-actions';
import { resendNearestUserMessage } from '@/lib/chat/resend';
import { chatState } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { isHumanReadableSuggestedValue } from '@/lib/suggested-guard';
import { t } from '@/lib/locale';

/** 建议动作（与 ChatMessage.suggestedActions 元素同形） */
export interface SuggestedAction {
  kind: 'retry' | 'continue' | 'next';
  label: string;
  value: string;
}

export function SuggestedActionBar(props: { actions: SuggestedAction[] }) {
  /** value 直入用户气泡与 LLM 历史，契约 = 人类可读文本 */
  const run = (act: SuggestedAction) => {
    if (act.kind === 'retry') {
      resendNearestUserMessage(chatState.messages.length - 1);
      return;
    }
    if (act.value) {
      if (!isHumanReadableSuggestedValue(act.value)) {
        console.warn('[SuggestedActionBar] 建议动作 value 非人类可读，拒发:', act.value);
        showToast(t('rp.suggested.valueRejected'), 'warning');
        return;
      }
      void sendUserMessage(act.value);
    }
  };

  return (
    <div class="suggested-actions">
      <For each={props.actions}>
        {(act) => (
          <button
            type="button"
            class="suggested-action-btn"
            onClick={() => run(act)}
          >
            {act.kind === 'retry'
              // 后端/本地派生可下发显式 label（如「继续刚才的任务」），无 label 回落「重试」
              ? (act.label || t('rp.msg.retry'))
              : (act.kind === 'next' && act.label ? act.label : t('rp.msg.continueTask'))}
          </button>
        )}
      </For>
    </div>
  );
}
