import { BsRobot } from 'solid-icons/bs';
import { ChatFeed } from './ChatFeed';
import { ChatInput } from './ChatInput';
import { state } from '@/stores/studio';
import { useSplitter } from '@/hooks/use-splitter';
import { t } from '@/lib/locale';

/**
 * 右侧聊天面板（对齐旧版布局）：
 * 头部（机器人图标 + Agent + 状态点）→ 消息流
 * → 拖拽把手（上下拖动调输入框高度，100-400px）→ 一体化输入区
 */
export default function RightPanel() {
  const inputSplit = useSplitter(150, {
    axis: 'y',
    min: 100,
    max: 400,
    invert: true,
    storageKey: 'splitChatInput',
  });

  return (
    <div class="panel-column">
      {/* Agent Header（旧版 right-header + agent-title + agent-status-dot） */}
      <div class="right-header">
        <div class="agent-title">
          <BsRobot size={16} class="icon-accent-blue" />
          <span>Agent</span>
        </div>
        <span
          class={`agent-status-dot ${state.agentBusy ? 'busy' : ''}`}
          title={state.agentBusy ? t('rp.header.busy') : t('rp.header.idle')}
        />
      </div>

      <ChatFeed />

      {/* 输入区与消息区之间的拖拽分隔线（旧版 chat-resize-handle） */}
      <div
        class={`chat-resize-handle ${inputSplit.dragging() ? 'dragging' : ''}`}
        title={t('rp.header.resizeHint')}
        onMouseDown={(e) => inputSplit.onMouseDown(e)}
      />

      <div class="chat-input-shell" style={{ height: `${inputSplit.size()}px` }}>
        <ChatInput />
      </div>
    </div>
  );
}
