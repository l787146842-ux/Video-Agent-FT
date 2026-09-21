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
import type { PauseQaPair } from '@/lib/turn-groups';
import { RichBubble } from './RichBubble';
import { UserRefBlocks } from './UserRefBlocks';
import { InlineEditBox } from './InlineEditBox';
import { PauseQaBlock } from './PauseQaBlock';

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
  /** 一问一答回执（批K）：非空时在气泡内逐问渲染「问题 → 你的选择」；
   *  取代旧的 agent 卡下泛化选项对勾区 */
  pauseQa?: PauseQaPair[];
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

  /** 问答回执（批K）：有配对数据才渲染；它本身就是「回答」的呈现，
   *  故此时正文（那串逐行拼接的答案）退居为纯文本兜底，不必再重复强调 */
  const qa = () => props.pauseQa || [];

  return (
    <Show
      when={props.editing() && props.editable}
      fallback={
        <Show when={userText() || hasRefBlocks() || hasInlineMedia() || qa().length > 0}>
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
                <Show when={qa().length > 0}>
                  <PauseQaBlock pairs={qa()} />
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
            {/* 富文本分支同样挂问答回执（带内联媒体的回应也要能回看） */}
            <Show when={qa().length > 0}>
              <div class="chat-bubble">
                <PauseQaBlock pairs={qa()} />
              </div>
            </Show>
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
