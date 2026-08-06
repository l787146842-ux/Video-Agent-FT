import { For, createSignal, Show, onMount, onCleanup } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiChevronRight, FiDownload, FiFileText, FiImage, FiX, FiZap,
} from 'solid-icons/fi';
import { renderMarkdown } from '@/lib/markdown';
import { openDocsPanel } from '@/stores/docs';
import { endCanvasImageDrag } from '@/stores/canvas';
import { safeUrl } from '@/lib/utils';
import { createImageDrag, absUrl } from '@/lib/chat-image-drag';
import { t } from '@/lib/locale';
import { RichBubble } from './RichBubble';
import { AgentTimeline, timelineFromMessage } from './AgentTimeline';
import { ConfirmActions } from './ConfirmActions';
import type { ChatMessage } from '@/types';

/**
 * 单条聊天消息
 * user：右侧气泡（有 parts 时按文字+缩略图交错还原排版）；agent：markdown 渲染。
 * 支持 docCard（文档完成卡片）、imageCard（生图结果，可点击看原图/可拖拽）、confirm（阶段确认卡片 + 操作条）。
 */
export function ChatMessageItem(props: {
  message: ChatMessage;
  isLast: boolean;
}) {
  const msg = () => props.message;
  const isUser = () => msg().sender === 'user';
  // 阶段完成卡默认展开（任务完成后直接可见结果），仅用户主动点击才折叠
  const [expanded, setExpanded] = createSignal(true);
  /** 原图预览（lightbox）当前打开的图片地址 */
  const [lightboxUrl, setLightboxUrl] = createSignal('');

  /** 过程时间线数据（从消息 trace/actionLog 重建，刷新后不丢） */
  const timeline = () => timelineFromMessage(msg());

  const drag = createImageDrag();

  // Esc 关闭原图预览
  function onDocKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') setLightboxUrl('');
  }
  onMount(() => document.addEventListener('keydown', onDocKeyDown));
  onCleanup(() => document.removeEventListener('keydown', onDocKeyDown));

  /** 用户消息是否含内联媒体（有则用富文本气泡还原排版） */
  const hasInlineMedia = () => !!msg().parts && msg().parts!.some((p) => p.type !== 'text');

  return (
    <div class={`chat-msg ${isUser() ? 'user' : 'agent'}`}>
      {/* 文档完成卡片（旧版 doc-card） */}
      <Show when={typeof msg().docCard === 'string' && msg().docCard}>
        <button
          type="button"
          class="doc-card"
          onClick={() => openDocsPanel(String(msg().docCard))}
        >
          <FiFileText size={15} class="doc-card-icon" />
          <span class="doc-card-name">{String(msg().docCard)}</span>
          <span class="doc-card-status">{t('rp.msg.docDone')}</span>
          <FiChevronRight size={12} class="doc-card-arrow" />
        </button>
      </Show>

      {/* 生图结果图片卡片（可拖拽到文件夹/画布） */}
      <Show when={msg().imageCard && msg().imageCard!.image_urls.length > 0}>
        <div class="image-card">
          <div class="image-card-header">
            <FiImage size={14} />
            <span>{t('rp.msg.imageResult')}</span>
            <Show when={msg().imageCard!.provider}>
              <span class="image-card-provider">{msg().imageCard!.provider}</span>
            </Show>
          </div>
          <div class="image-card-grid">
            <For each={msg().imageCard!.image_urls}>
              {(url, idx) => {
                const fname = () => url.split('/').pop()?.split('?')[0] || `image-${idx() + 1}.png`;
                return (
                  <div
                    class="image-card-thumb"
                    draggable="true"
                    onDragStart={(e) => drag.handleImageDragStart(e, url, fname())}
                    onDragEnd={() => endCanvasImageDrag()}
                    onPointerDown={(e) => drag.onThumbPointerDown(e, url, fname())}
                    onClick={() => { if (!drag.wasMoved()) setLightboxUrl(absUrl(url)); }}
                    title={t('rp.msg.imageTip', { name: fname() })}
                  >
                    <img
                      src={safeUrl(url)}
                      alt={fname()}
                      loading="lazy"
                      onLoad={() => drag.prefetchDragFile(url, fname())}
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none';
                      }}
                    />
                    <span class="image-card-label">{fname()}</span>
                    <button
                      type="button"
                      class="image-card-download"
                      title={t('rp.msg.download')}
                      onClick={(e) => {
                        e.stopPropagation();
                        const a = document.createElement('a');
                        a.href = absUrl(url);
                        a.download = fname();
                        a.click();
                      }}
                    >
                      <FiDownload size={12} />
                    </button>
                  </div>
                );
              }}
            </For>
          </div>
        </div>
      </Show>

      {/* 原图预览 lightbox：点击缩略图打开，点击背景/Esc 关闭 */}
      <Show when={lightboxUrl()}>
        <div class="image-lightbox" onClick={() => setLightboxUrl('')}>
          <img
            src={lightboxUrl()}
            alt={t('rp.msg.lightboxAlt')}
            onClick={(e) => e.stopPropagation()}
          />
          <div class="image-lightbox-actions">
            <a
              href={lightboxUrl()}
              download=""
              title={t('rp.msg.downloadOriginal')}
              onClick={(e) => e.stopPropagation()}
            >
              <FiDownload size={16} />
            </a>
            <button type="button" title={t('rp.msg.closeEsc')} onClick={() => setLightboxUrl('')}>
              <FiX size={18} />
            </button>
          </div>
        </div>
      </Show>

      {/* 阶段确认卡片（旧版 stage-card） */}
      <Show when={msg().confirm}>
        <div class={`stage-card ${expanded() ? 'expanded' : ''}`}>
          <button
            type="button"
            class="stage-card-header"
            onClick={() => setExpanded(!expanded())}
          >
            <FiCheckCircle size={15} class="stage-check" />
            <span class="stage-card-title">{t('rp.msg.stageDone')}</span>
            <Show when={msg().appliedActions}>
              <span class="stage-card-badge">
                {t('rp.msg.appliedOps', { count: msg().appliedActions ?? 0 })}
              </span>
            </Show>
            <FiChevronDown size={13} class="stage-arrow" />
          </button>
          <div class="stage-card-body">
            {msg().confirm}
            <Show when={(msg().actionLog || []).length}>
              <ul class="stage-op-list">
                <For each={msg().actionLog}>{(op) => <li class="stage-op-item">{op}</li>}</For>
              </ul>
            </Show>
          </div>
        </div>
      </Show>

      {/* 过程时间线（深度思考 + 已处理操作，折叠面板；内容不进下次 LLM 上下文） */}
      <Show when={!isUser()}>
        <AgentTimeline
          reasoning={timeline().reasoning}
          items={timeline().items}
          thinkingMs={msg().thinkingMs}
        />
      </Show>

      {/* 用户消息引用块：文档附件 / Skill（发送后才附加，点击查看对应文档） */}
      <Show when={isUser() && ((msg().docBlocks || []).length > 0 || (msg().skillBlocks || []).length > 0)}>
        <div class="msg-ref-blocks">
          <For each={msg().skillBlocks || []}>
            {(name) => (
              <button
                type="button"
                class="msg-ref-block msg-ref-skill"
                title={`查看 Skill：${name}`}
                onClick={() => void openDocsPanel(name)}
              >
                <FiZap size={12} />
                <span class="msg-ref-name">{name}</span>
              </button>
            )}
          </For>
          <For each={msg().docBlocks || []}>
            {(name) => (
              <button
                type="button"
                class="msg-ref-block msg-ref-doc"
                title={`查看文档：${name}`}
                onClick={() => void openDocsPanel(name)}
              >
                <FiFileText size={12} />
                <span class="msg-ref-name">{name}</span>
              </button>
            )}
          </For>
        </div>
      </Show>

      {/* 消息气泡（旧版 chat-bubble + msg-author） */}
      <Show when={msg().text}>
        <Show when={!isUser()}>
          <span class="msg-author">
            {msg().modelName || 'Agent'}
          </span>
        </Show>
        <Show
          when={isUser()}
          fallback={
            <div
              class="chat-bubble chat-markdown"
              innerHTML={renderMarkdown(msg().text)}
            />
          }
        >
          {/* 用户气泡：含内联媒体时按文字+缩略图交错还原排版 */}
          <Show
            when={hasInlineMedia()}
            fallback={<div class="chat-bubble">{msg().text}</div>}
          >
            <RichBubble
              parts={msg().parts!}
              onImageClick={(url) => setLightboxUrl(absUrl(url))}
            />
          </Show>
        </Show>
      </Show>

      {/* 元信息（旧版 msg-meta） */}
      <Show when={msg().meta}>
        <div class="msg-meta">{msg().meta}</div>
      </Show>

      {/* 确认操作区（仅最后一条带 confirm 的消息：候选项单选卡片 / 确认按钮） */}
      <Show when={msg().confirm && props.isLast}>
        <ConfirmActions message={msg()} />
      </Show>
    </div>
  );
}
