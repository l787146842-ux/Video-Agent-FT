/**
 * UserBubble.tsx — 用户消息气泡排版还原（自 ChatMessageItem 拆分，
 * 前端物理行数 250 红线收敛）。
 *
 * 正常态按 parts 还原排版（文字 + 内联媒体交错，Skill/文档引用块进气泡内）；
 * 编辑中原地变为 InlineEditBox（提交 = 截断重答，由父组件闭环）。
 */
import { Show } from 'solid-js';
import { absUrl } from '@/lib/chat/chat-image-drag';
import type { ChatMessage } from '@/types';
import { RichBubble } from './RichBubble';
import { UserRefBlocks } from './UserRefBlocks';
import { InlineEditBox } from './InlineEditBox';

export function UserBubble(props: {
  message: ChatMessage;
  /** 原地编辑进行中（父组件信号访问器，保持细粒度响应） */
  editing: () => boolean;
  /** 该消息当前可编辑（与 editing 同时成立时编辑框接管） */
  editable?: boolean;
  onSubmit: (text: string) => Promise<boolean>;
  onCancel: () => void;
  /** 内联媒体点击（已转绝对地址，父组件开 lightbox） */
  onImageClick: (url: string) => void;
}) {
  const msg = () => props.message;

  /** 是否含内联媒体（有则用富文本气泡还原排版） */
  const hasInlineMedia = () => (msg().parts || []).some((p) => p.type !== 'text');

  /** 是否带 Skill / 文档引用块（渲染进气泡内部） */
  const hasRefBlocks = () =>
    ((msg().docBlocks || []).length > 0) || ((msg().skillBlocks || []).length > 0);

  /** 气泡正文：纯 Skill 唤起时正文与 Skill 块重名，隐藏正文只留块 */
  const userText = () => {
    const raw = msg().text || '';
    const skills = msg().skillBlocks || [];
    if (raw.trim() && skills.length === 1 && raw.trim() === skills[0]) return '';
    return raw;
  };

  return (
    <Show
      when={props.editing() && props.editable}
      fallback={
        <Show when={userText() || hasRefBlocks() || hasInlineMedia()}>
          <Show
            when={hasInlineMedia()}
            fallback={
              <div class="chat-bubble">
                <Show when={hasRefBlocks()}>
                  <UserRefBlocks message={msg()} />
                </Show>
                <Show when={userText()}>
                  <span class="user-bubble-text">{userText()}</span>
                </Show>
              </div>
            }
          >
            <RichBubble
              before={
                <Show when={hasRefBlocks()}>
                  <UserRefBlocks message={msg()} />
                </Show>
              }
              parts={msg().parts || []}
              onImageClick={(url) => props.onImageClick(absUrl(url))}
            />
          </Show>
        </Show>
      }
    >
      <InlineEditBox
        initial={msg().text || ''}
        onCancel={props.onCancel}
        onSubmit={props.onSubmit}
      />
    </Show>
  );
}
