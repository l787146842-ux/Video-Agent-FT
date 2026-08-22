import { For, createSignal, Show, onMount, onCleanup } from 'solid-js';
import { useNavigate } from '@solidjs/router';
import {
  FiCheckCircle, FiChevronRight, FiFileText,
} from 'solid-icons/fi';
import { sendUserMessage } from '@/lib/agent-actions';
import { chatState } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { openDocsPanel } from '@/stores/docs';
import { isHumanReadableSuggestedValue } from '@/lib/suggested-guard';
import { resendNearestUserMessage } from '@/lib/resend';
import { editMessageInBranch } from '@/lib/edit-branch';
import { absUrl } from '@/lib/chat-image-drag';
import { t } from '@/lib/locale';
import { RichBubble } from './RichBubble';
import { AgentTimeline, timelineFromMessage } from './AgentTimeline';
import { ConfirmActions } from './ConfirmActions';
import { StageCard } from './StageCard';
import { UserRefBlocks } from './UserRefBlocks';
import { ImageResultCard } from './ImageResultCard';
import { VideoResultCard } from './VideoResultCard';
import { ImageLightbox } from './ImageLightbox';
import { GateWarnings } from './GateWarnings';
import { MemoryHits } from './MemoryHits';
import { MarkdownBubble } from './MarkdownBubble';
import type { ChatMessage } from '@/types';

/**
 * 单条聊天消息
 * user：右侧气泡（有 parts 时按文字+缩略图交错还原排版）；agent：markdown 渲染。
 * 支持 docCard（文档完成卡片）、imageCard（生图结果，可点击看原图/可拖拽）、confirm（阶段确认卡片 + 操作条）。
 */
export function ChatMessageItem(props: {
  message: ChatMessage;
  isLast: boolean;
  /** 是否为最后一条含闸机拦截警告的消息（「本次放行」按钮挂载点） */
  isGateTarget?: boolean;
  /** 暂停卡生命周期（answered/expired 时阶段卡挂徽标，回看不迷惑） */
  confirmState?: 'active' | 'answered' | 'expired' | 'none';
  /** 轮次容器内渲染——作者名/meta 上提到组头，本条不再重复 */
  hideChrome?: boolean;
  /** 已回应暂停卡的「当时所选值」（其后首条用户消息文本） */
  answeredValue?: string;
  /** 是否为最后一条携带建议动作的消息（重试/继续按钮挂载点） */
  isSuggestedTarget?: boolean;
  /** 用户气泡编辑控制点挂载位（经 deriveAffordances 派生） */
  editable?: boolean;
  /** 消息在全局数组中的下标（搜索/轮次跳转的定位锚点 data-msg-index） */
  domIndex?: number;
}) {
  const msg = () => props.message;
  const isUser = () => msg().sender === 'user';
  const navigate = useNavigate();
  /** 原图预览（lightbox）当前打开的图片地址 */
  const [lightboxUrl, setLightboxUrl] = createSignal('');

  /** 建议动作 value 护栏（实现见 lib/suggested-guard）：
   *  value 会直入用户气泡与 LLM 历史，契约 = 与 label 同值的人类可读文本 */

  /** 重试 = 机械重发上一条用户消息原内容（含富文本附件），零模型猜测；
   * continue/next = 发送后端下发的固定 value 文本
   * （next=状态驱动下一步建议，点击即显式用户指令） */
  const runSuggested = (act: { kind: 'retry' | 'continue' | 'next'; value: string }) => {
    if (act.kind === 'retry') {
      resendNearestUserMessage(chatState.messages.length - 1);
      return;
    }
    if (act.value) {
      if (!isHumanReadableSuggestedValue(act.value)) {
        console.warn('[ChatMessageItem] 建议动作 value 非人类可读，拒发:', act.value);
        showToast(t('rp.suggested.valueRejected'), 'warning');
        return;
      }
      void sendUserMessage(act.value);
    }
  };

  /** 轮级 regenerate：任意 agent 回复可重跑（机械重发其前最近用户消息，
   * 与 retry 同语义，实现见 lib/resend）；末条已有 suggested retry 不重复挂载 */
  const regenerate = () => {
    const here = chatState.messages.indexOf(msg());
    if (here > 0) resendNearestUserMessage(here - 1);
  };

  /** 过程时间线数据（从消息 trace/actionLog 重建，刷新后不丢） */
  const timeline = () => timelineFromMessage(msg());

  /** 用户消息是否含内联媒体（有则用富文本气泡还原排版） */
  const hasInlineMedia = () => (msg().parts || []).some((p) => p.type !== 'text');

  /** 用户消息是否带 Skill / 文档引用块（渲染进气泡内部） */
  const hasRefBlocks = () =>
    ((msg().docBlocks || []).length > 0) || ((msg().skillBlocks || []).length > 0);

  /** 用户气泡正文：纯 Skill 唤起时正文与 Skill 块重名，隐藏正文只留块 */
  const userText = () => {
    const raw = msg().text || '';
    const skills = msg().skillBlocks || [];
    if (raw.trim() && skills.length === 1 && raw.trim() === skills[0]) return '';
    return raw;
  };

  // Esc 关闭内联媒体原图预览（生图卡的预览由 ImageResultCard 自管）
  function onDocKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') setLightboxUrl('');
  }
  onMount(() => document.addEventListener('keydown', onDocKeyDown));
  onCleanup(() => document.removeEventListener('keydown', onDocKeyDown));

  return (
    <div class={`chat-msg ${isUser() ? 'user' : 'agent'}`} data-msg-index={props.domIndex}>
      {/* 文档完成卡片（keyed Show 避免 String()/非空断言） */}
      <Show when={msg().docCard} keyed>
        {(doc) => (
          <button
            type="button"
            class="doc-card"
            onClick={() => openDocsPanel(doc)}
          >
            <FiFileText size={15} class="doc-card-icon" />
            <span class="doc-card-name">{doc}</span>
            <span class="doc-card-status">{t('rp.msg.docDone')}</span>
            <FiChevronRight size={12} class="doc-card-arrow" />
          </button>
        )}
      </Show>

      {/* 生图结果卡 / 视频结果内联预览卡（拖拽/下载/lightbox 均在各自 Card 内） */}
      <Show when={msg().imageCard} keyed>{(card) => <ImageResultCard card={card} />}</Show>
      <Show when={msg().videoCard} keyed>{(card) => <VideoResultCard card={card} />}</Show>

      {/* 阶段完成卡：可展开、默认展开；正文=本轮概述（确认文案）+执行清单。
          确认文案与模型正文判重防双显；历史消息同样可展开，暂停点回看不丢失） */}
      <Show when={msg().confirm}>
        <StageCard msg={msg} state={props.confirmState || 'none'} />
      </Show>

      {/* 已回应暂停卡的「当时选了哪项」对勾标注（只读回看）。
          匹配规则：所选值 = 其后首条用户消息文本，与选项 value/label 相等即命中；
          无匹配只灰显不标对勾（防误标） */}
      <Show when={msg().confirm && (props.answeredValue || '') && (msg().confirmOptions || []).length > 0}>
        <div class="answered-options">
          <For each={msg().confirmOptions || []}>
            {(opt) => {
              const lines = (props.answeredValue || '')
                .split('\n').map((s) => s.trim()).filter(Boolean);
              const chosen = () =>
                opt.value === props.answeredValue || opt.label === props.answeredValue
                || lines.includes(opt.value ?? '') || lines.includes(opt.label ?? '');
              return (
                <span class={`answered-option${chosen() ? ' chosen' : ''}`}>
                  <Show when={chosen()}>
                    <FiCheckCircle size={12} class="answered-option-check" />
                  </Show>
                  {opt.label}
                  <Show when={chosen()}>
                    <span class="answered-option-tag">{t('rp.msg.chosen')}</span>
                  </Show>
                </span>
              );
            }}
          </For>
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

      {/* 消息气泡：agent 用 markdown 渲染；用户的 Skill/文档块也进气泡内 */}
      <Show when={!isUser() && msg().text}>
        {/* 轮次容器内作者名已上提到组头，不重复渲染 */}
        <Show when={!props.hideChrome}>
          <span class="msg-author">
            {msg().modelName || 'Agent'}
          </span>
        </Show>
        {/* 模型降级等警示 + 闸机拦截 chips + 本次放行（见 GateWarnings） */}
        <GateWarnings message={msg()} isGateTarget={props.isGateTarget} />
        {/* 记忆命中可视化（见 MemoryHits） */}
        <MemoryHits message={msg()} />
        {/* markdown 气泡抽出（高亮补刷 + 代码块复制委托在组件内接线） */}
        <MarkdownBubble text={msg().text} />
        {/* 鉴权/供应商类错误气泡附「检查 API 配置」跳转 */}
        <Show when={msg().settingsHint}>
          <button
            type="button"
            class="gate-override-btn"
            onClick={() => navigate('/settings')}
          >
            {t('rp.msg.checkSettings')}
          </button>
        </Show>
        {/* 错误技术详情折叠（人话在气泡，上游原始报文默认收起） */}
        <Show when={msg().errorDetail}>
          <details class="msg-error-detail">
            <summary>技术详情</summary>
            <pre class="msg-error-detail-body">{msg().errorDetail}</pre>
          </details>
        </Show>
        {/* 建议动作按钮（重试=机械重发上一条用户消息；继续=固定文本） */}
        <Show when={props.isSuggestedTarget && (msg().suggestedActions || []).length > 0}>
          <div class="suggested-actions">
            <For each={msg().suggestedActions || []}>
              {(act) => (
                <button
                  type="button"
                  class="suggested-action-btn"
                  onClick={() => runSuggested(act)}
                >
                  {act.kind === 'retry'
                    // 后端/本地派生可下发显式 label（如「继续刚才的任务」），无 label 回落「重试」
                    ? (act.label || t('rp.msg.retry'))
                    : (act.kind === 'next' && act.label ? act.label : t('rp.msg.continueTask'))}
                </button>
              )}
            </For>
          </div>
        </Show>
        {/* 轮级 regenerate：非末尾 agent 回复挂重跑按钮（末条已有 suggested retry） */}
        <Show when={!props.isSuggestedTarget}>
          <button
            type="button"
            class="msg-regenerate-btn"
            title={t('rp.msg.regenerate')}
            onClick={regenerate}
          >
            {t('rp.msg.regenerate')}
          </button>
        </Show>
      </Show>

      {/* 系统动作行（如「本次放行」）：不占用户气泡形态，回看不误认为用户打过这句话 */}
      <Show when={isUser() && msg().kind === 'system_action'}>
        <div class="system-action-line">{msg().text}</div>
      </Show>

      {/* 用户气泡：Skill 块/文档块与正文、内联媒体同一个气泡展示 */}
      <Show when={isUser() && msg().kind !== 'system_action' && (userText() || hasRefBlocks() || hasInlineMedia())}>
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
            onImageClick={(url) => setLightboxUrl(absUrl(url))}
          />
        </Show>
      </Show>

      {/* 用户气泡编辑控制点：编辑即分支——快照派生新对话，原对话不变，
          修改后的内容在新对话输入框确认后走统一发送入口发出 */}
      <Show when={props.editable}>
        <button
          type="button"
          class="msg-edit-btn"
          title={t('rp.msg.editTitle')}
          onClick={() => void editMessageInBranch(msg().text || '')}
        >
          {t('rp.msg.edit')}
        </button>
      </Show>

      {/* 内联媒体原图预览 lightbox（共享组件） */}
      <ImageLightbox url={lightboxUrl} onClose={() => setLightboxUrl('')} />

      {/* 元信息（轮次容器内已上提到组头，不重复渲染） */}
      <Show when={msg().meta && !props.hideChrome}>
        <div class="msg-meta">{msg().meta}</div>
      </Show>

      {/* 确认操作区（仅最后一条带 confirm 的消息：候选项单选卡片 / 确认按钮） */}
      <Show when={msg().confirm && props.isLast}>
        <ConfirmActions message={msg()} />
      </Show>
    </div>
  );
}
