import { Show } from 'solid-js';
import { BsRobot } from 'solid-icons/bs';
import { chatState } from '@/stores/chat';

/** 流式状态指示器：头像 + 打字点动画 + 状态文本 */
export function StreamingIndicator() {
  return (
    <Show when={chatState.isStreaming && !chatState.streamingText}>
      <div class="chat-msg agent">
        <div class="chat-bubble streaming-bubble">
          <div class="streaming-indicator">
            <BsRobot size={14} class="icon-accent-blue" />
            <span class="typing-dots">
              <span /><span /><span />
            </span>
            <span class="streaming-status-text">{chatState.streamingStatus || '正在思考…'}</span>
          </div>
        </div>
      </div>
    </Show>
  );
}
