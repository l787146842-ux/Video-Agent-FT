/* eslint-disable max-lines */ // 消息流元素聚合（卡片/时间线/闸机 chips），拆分另行立项
import { For, createSignal, Show, onMount, onCleanup } from 'solid-js';
import { useNavigate } from '@solidjs/router';
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
import { AgentTimeline, timelineFromMessage, stageLabelFromMessage } from './AgentTimeline';
import { ConfirmActions } from './ConfirmActions';
import { UserRefBlocks } from './UserRefBlocks';
import type { ChatMessage } from '@/types';

/**
 * 单条聊天消息
 * user：右侧气泡（有 parts 时按文字+缩略图交错还原排版）；agent：markdown 渲染。
 * 支持 docCard（文档完成卡片）、imageCard（生图结果，可点击看原图/可拖拽）、confirm（阶段确认卡片 + 操作条）。
 */
export function ChatMessageItem(props: {
  message: ChatMessage;
  isLast: boolean;
  /** 814F7：是否为最后一条含闸机拦截警告的消息（「本次放行」按钮挂载点） */
  isGateTarget?: boolean;
}) {
  const msg = () => props.message;
  const isUser = () => msg().sender === 'user';
  const navigate = useNavigate();
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

  /** 用户消息是否带 Skill / 文档引用块（Q5：渲染进气泡内部） */
  const hasRefBlocks = () =>
    ((msg().docBlocks || []).length > 0) || ((msg().skillBlocks || []).length > 0);

  /** 是否含闸机拦截类警告（B2/F13：结构化判定——trace.gates 存在 ok=false 条目，
   * 不再对文案做 includes('拦截') 字符串匹配） */
  const gateRecords = () => {
    const out: Array<{ rule_id: string; layer: string; message: string; skill_name?: string }> = [];
    (msg().trace?.steps || []).forEach((s) => {
      (s.gates || []).forEach((g) => {
        if (!g.ok) out.push({
          rule_id: g.rule_id,
          layer: g.layer,
          message: g.message || '',
          skill_name: g.skill_name,
        });
      });
    });
    return out;
  };
  const hasGateWarning = () => gateRecords().length > 0;

  /** 本次放行（§2.4）：显式用户指令 + gate_overrides 随消息留痕，后端单次消费 */
  const overrideOnce = () => {
    void sendUserMessage('放行本次拦截，继续任务', { gateOverrides: ['all'] });
  };

  /** 用户气泡正文：纯 Skill 唤起时正文与 Skill 块重名，隐藏正文只留块 */
  const userText = () => {
    const raw = msg().text || '';
    const skills = msg().skillBlocks || [];
    if (raw.trim() && skills.length === 1 && raw.trim() === skills[0]) return '';
    return raw;
  };

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

      {/* 阶段完成卡（B2/F12·D4：可展开、默认展开；正文=本轮概述（确认文案）+执行清单。
          确认文案与模型正文判重防双显；历史消息同样可展开，暂停点回看不丢失） */}
      <Show when={msg().confirm}>
        <StageCard msg={msg} />
      </Show>

      {/* 过程时间线（深度思考 + 已处理操作，折叠面板；内容不进下次 LLM 上下文） */}
      <Show when={!isUser()}>
        <AgentTimeline
          reasoning={timeline().reasoning}
          items={timeline().items}
          thinkingMs={msg().thinkingMs}
        />
      </Show>

      {/* 消息气泡：agent 用 markdown 渲染；用户的 Skill/文档块也进气泡内（Q5） */}
      <Show when={!isUser() && msg().text}>
        <span class="msg-author">
          {msg().modelName || 'Agent'}
        </span>
        {/* 模型降级等警示：常驻展示在 agent 气泡上（刷新后仍可见） */}
        <Show when={(msg().warnings || []).length > 0 || hasGateWarning()}>
          <div class="msg-warnings">
            {/* B2/F13：闸机判定 chips（结构化来源标注：「平台」/「Skill『xxx』」） */}
            <For each={gateRecords()}>
              {(g) => (
                <div class="gate-chip-row">
                  <span class={`gate-chip gate-chip-${g.layer === 'platform' ? 'platform' : 'skill'}`}>
                    {g.layer === 'platform'
                      ? t('rp.msg.gatePlatform')
                      : t('rp.msg.gateSkill', { name: g.skill_name || '' })}
                  </span>
                  <span class="gate-chip-msg">{g.message || g.rule_id}</span>
                </div>
              )}
            </For>
            <For each={msg().warnings || []}>
              {(w) => <div class="msg-warning-line">⚠ {w}</div>}
            </For>
            {/* 814F7/B2：拦截类警告附「本次放行」按钮（结构化挂载，仅最新一条，单次生效留痕） */}
            <Show when={props.isGateTarget && hasGateWarning()}>
              <button type="button" class="gate-override-btn" onClick={overrideOnce}>
                {t('rp.msg.gateOverride')}
              </button>
            </Show>
          </div>
        </Show>
        {/* 记忆命中可视化（4.7）：本轮 Agent 参考了哪些长期记忆（折叠展示） */}
        <Show when={(msg().memoryHits || []).length > 0}>
          <details class="msg-memory-hits">
            <summary>{t('rp.msg.memoryRefs', { count: (msg().memoryHits || []).length })}</summary>
            <For each={msg().memoryHits || []}>
              {(h) => (
                <div class="memory-hit-line">
                  <span class="memory-hit-date">{h.date}</span>
                  {h.content}
                </div>
              )}
            </For>
          </details>
        </Show>
        <div
          class="chat-bubble chat-markdown"
          innerHTML={renderMarkdown(msg().text)}
        />
        {/* U1：鉴权/供应商类错误气泡附「检查 API 配置」跳转 */}
        <Show when={msg().settingsHint}>
          <button
            type="button"
            class="gate-override-btn"
            onClick={() => navigate('/settings')}
          >
            {t('rp.msg.checkSettings')}
          </button>
        </Show>
      </Show>

      {/* 用户气泡：Skill 块/文档块与正文、内联媒体同一个气泡展示（Q5） */}
      <Show when={isUser() && (userText() || hasRefBlocks() || hasInlineMedia())}>
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
            parts={msg().parts!}
            onImageClick={(url) => setLightboxUrl(absUrl(url))}
          />
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

/**
 * 阶段完成卡（B2/F12·D4）：可展开、默认展开。
 * 正文=本轮概述（确认文案，与模型正文判重防双显）+ 执行清单（actionLog）。
 * 历史消息同样可展开——暂停点回看不丢失（吸收 Qoder 问题 12）。
 */
function StageCard(props: { msg: () => ChatMessage }) {
  const [open, setOpen] = createSignal(true);
  const msg = () => props.msg();
  const confirmText = () => {
    const c = msg().confirm;
    return typeof c === 'string' ? c : '';
  };
  /** 确认文案与模型正文判重：正文已包含同样句子时卡片只留执行清单 */
  const bodyText = () => {
    const c = confirmText().trim();
    if (!c) return '';
    const norm = (s: string) => s.replace(/[\s“”'"]/g, '');
    if (norm(msg().text || '').includes(norm(c))) return '';
    return c;
  };
  const hasBody = () => !!bodyText() || (msg().actionLog || []).length > 0;

  return (
    <div class={`stage-card ${open() ? 'expanded' : ''}`}>
      <button
        type="button"
        class="stage-card-header"
        onClick={() => setOpen(!open())}
        aria-expanded={open()}
      >
        <FiCheckCircle size={15} class="stage-check" />
        <span class="stage-card-title">
          {stageLabelFromMessage(msg())
            ? `${stageLabelFromMessage(msg())} · ${t('rp.msg.stageDone')}`
            : t('rp.msg.stageDone')}
        </span>
        <Show when={msg().appliedActions}>
          <span class="stage-card-badge">
            {t('rp.msg.appliedOps', { count: msg().appliedActions ?? 0 })}
          </span>
        </Show>
        <Show when={hasBody()}>
          {open() ? <FiChevronDown size={13} class="stage-card-arrow" /> : <FiChevronRight size={13} class="stage-card-arrow" />}
        </Show>
      </button>
      <Show when={open() && hasBody()}>
        <div class="stage-card-body">
          <Show when={bodyText()}>
            <p class="stage-card-summary">{bodyText()}</p>
          </Show>
          <Show when={(msg().actionLog || []).length > 0}>
            <ul class="stage-card-ops">
              <For each={msg().actionLog || []}>
                {(op) => <li>{op}</li>}
              </For>
            </ul>
          </Show>
        </div>
      </Show>
    </div>
  );
}
