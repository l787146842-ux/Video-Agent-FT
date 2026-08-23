/**
 * 消息悬停工具条（任务 #17 新交互模型）。
 *
 * 仅鼠标悬停该消息（或键盘 focus-within）时可见——CSS 显隐归
 * chat-feed-core.css（.chat-msg:hover / :focus-within），本组件只负责
 * 按 affordances 矩阵渲染按钮集与该消息的 HH:MM 时间戳：
 * - 用户消息：复制；最后一条额外「编辑」（非忙碌）
 * - agent 回复：复制、分支；最后一条额外「重新生成」
 * 按钮均为真实 <button>（Tab 可达），data-testid 供 e2e 钉死。
 */
import { Show } from 'solid-js';
import { FiCopy, FiEdit2, FiGitBranch, FiRefreshCw } from 'solid-icons/fi';
import { t } from '@/lib/locale';

export function MessageHoverToolbar(props: {
  /** HH:MM 时间戳（消息无 ts 时为空串，不渲染） */
  time?: string;
  copyable?: boolean;
  editable?: boolean;
  branchable?: boolean;
  regenerable?: boolean;
  /** 用户消息右对齐 / agent 消息左对齐 */
  align?: 'left' | 'right';
  onCopy: () => void;
  onEdit?: () => void;
  onBranch?: () => void;
  onRegenerate?: () => void;
}) {
  return (
    <div
      class={`msg-hover-toolbar${props.align === 'right' ? ' align-right' : ''}`}
      data-testid="msg-hover-toolbar"
    >
      <Show when={props.time}>
        <span class="msg-hover-time">{props.time}</span>
      </Show>
      <Show when={props.copyable}>
        <button
          type="button"
          class="msg-act-btn"
          data-testid="msg-act-copy"
          title={t('rp.msg.copy')}
          aria-label={t('rp.msg.copy')}
          onClick={() => props.onCopy()}
        >
          <FiCopy size={13} />
        </button>
      </Show>
      <Show when={props.editable}>
        <button
          type="button"
          class="msg-act-btn"
          data-testid="msg-act-edit"
          title={t('rp.msg.editTitle')}
          aria-label={t('rp.msg.edit')}
          onClick={() => props.onEdit?.()}
        >
          <FiEdit2 size={13} />
        </button>
      </Show>
      <Show when={props.branchable}>
        <button
          type="button"
          class="msg-act-btn"
          data-testid="msg-act-branch"
          title={t('rp.msg.branch')}
          aria-label={t('rp.msg.branch')}
          onClick={() => props.onBranch?.()}
        >
          <FiGitBranch size={13} />
        </button>
      </Show>
      <Show when={props.regenerable}>
        <button
          type="button"
          class="msg-act-btn"
          data-testid="msg-act-regenerate"
          title={t('rp.msg.regenerate')}
          aria-label={t('rp.msg.regenerate')}
          onClick={() => props.onRegenerate?.()}
        >
          <FiRefreshCw size={13} />
        </button>
      </Show>
    </div>
  );
}
