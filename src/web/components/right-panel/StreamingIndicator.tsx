import { Show } from 'solid-js';
import { BsRobot } from 'solid-icons/bs';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';

/**
 * 流式状态指示器：头像 + 打字点动画 + 状态文本。
 * 时间线已有条目（深度思考/工具操作）时不再重复显示打字动画，
 * 避免与 AgentTimeline 的运行态条目视觉冲突。
 */
export function StreamingIndicator() {
  const noTimelineYet = () =>
    !chatState.turnLedger.items.length && !chatState.turnLedger.reasoning;
  return (
    <Show when={chatState.isStreaming && !chatState.streamingText && noTimelineYet()}>
      <div class="chat-msg agent">
        <div class="chat-bubble streaming-bubble">
          {/* role=status 隐含 aria-live=polite，状态文案变更对读屏器可闻 */}
          <div class="streaming-indicator" role="status">
            <BsRobot size={14} class="icon-accent-blue" />
            <span class="typing-dots">
              <span /><span /><span />
            </span>
            <span class="streaming-status-text">{chatState.turnLedger.statusText || t('rp.streaming.thinking')}</span>
          </div>
        </div>
      </div>
    </Show>
  );
}
