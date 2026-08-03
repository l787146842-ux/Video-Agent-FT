/* eslint-disable max-lines -- 存量超行（铁律 10.1），待后续拆分；新增代码仍受规则约束 */
import { For, createSignal, Show, onMount, onCleanup } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiChevronRight, FiDownload, FiFileText, FiImage, FiX,
} from 'solid-icons/fi';
import { renderMarkdown } from '@/lib/markdown';
import { sendUserMessage } from '@/lib/agent-actions';
import { openDocsPanel } from '@/stores/docs';
import { endCanvasImageDrag } from '@/stores/canvas';
import { safeUrl } from '@/lib/utils';
import { createImageDrag, absUrl } from '@/lib/chat-image-drag';
import { t } from '@/lib/locale';
import { RichBubble } from './RichBubble';
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
  const [expanded, setExpanded] = createSignal(false);
  /** 无确认请求的「阶段完成」卡片展开态（展示具体操作清单） */
  const [opsExpanded, setOpsExpanded] = createSignal(false);
  /** 执行轨迹折叠区展开态 */
  const [traceOpen, setTraceOpen] = createSignal(false);
  /** 原图预览（lightbox）当前打开的图片地址 */
  const [lightboxUrl, setLightboxUrl] = createSignal('');

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

      {/* 无确认请求但执行过操作：展示可展开的「阶段完成」卡片（含具体操作清单，刷新后从历史重建） */}
      <Show when={!msg().confirm && (msg().appliedActions || 0) > 0 && (msg().actionLog || []).length}>
        <div class={`stage-card ${opsExpanded() ? 'expanded' : ''}`}>
          <button
            type="button"
            class="stage-card-header"
            onClick={() => setOpsExpanded(!opsExpanded())}
          >
            <FiCheckCircle size={15} class="stage-check" />
            <span class="stage-card-title">{t('rp.msg.stageDone')}</span>
            <span class="stage-card-badge">
              {t('rp.msg.appliedOps', { count: msg().appliedActions ?? 0 })}
            </span>
            <FiChevronDown size={13} class="stage-arrow" />
          </button>
          <div class="stage-card-body">
            <ul class="stage-op-list">
              <For each={msg().actionLog}>{(op) => <li class="stage-op-item">{op}</li>}</For>
            </ul>
          </div>
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

      {/* 执行轨迹（默认收起）：每轮推理耗时/操作数，供排障与理解 Agent 干什么 */}
      <Show when={!isUser() && (msg().trace?.steps || []).length}>
        <div class={`trace-card ${traceOpen() ? 'expanded' : ''}`}>
          <button
            type="button"
            class="trace-card-header"
            onClick={() => setTraceOpen(!traceOpen())}
          >
            <span class="trace-card-title">{t('rp.msg.trace')}</span>
            <span class="trace-card-summary">
              {t('rp.msg.traceSummary', { rounds: msg().trace!.steps!.length, seconds: ((msg().trace!.total_ms || 0) / 1000).toFixed(1) })}
            </span>
            <FiChevronDown size={12} class="trace-arrow" />
          </button>
          <div class="trace-card-body">
            <For each={msg().trace!.steps}>
              {(s) => (
                <div class="trace-step">
                  {t('rp.msg.traceStep', { step: s.step, seconds: (s.timing_ms / 1000).toFixed(1) })}
                  <Show when={s.actions_applied}> · {t('rp.msg.traceOps', { count: s.actions_applied })}</Show>
                  <Show when={s.finish_reason}> · {s.finish_reason}</Show>
                </div>
              )}
            </For>
          </div>
        </div>
      </Show>

      {/* 确认操作条（仅最后一条带 confirm 的消息，旧版 confirm-actions + confirm-btn） */}
      <Show when={msg().confirm && props.isLast}>
        <div class="confirm-actions">
          <button
            type="button"
            class="confirm-btn primary"
            onClick={() => void sendUserMessage(t('rp.msg.confirmText'))}
          >
            {t('rp.msg.confirmContinue')}
          </button>
          <button
            type="button"
            class="confirm-btn secondary"
            onClick={() => {
              document.getElementById('chatInputTextarea')?.focus();
            }}
          >
            {t('rp.msg.adjust')}
          </button>
        </div>
      </Show>
    </div>
  );
}
