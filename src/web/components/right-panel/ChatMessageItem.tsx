import { createSignal, Show, onMount, onCleanup } from 'solid-js';
import { useNavigate } from '@solidjs/router';
import { chatState } from '@/stores/chat';
import { showToast } from '@/stores/toast';
import { saveMessageAsDoc } from '@/stores/docs';
import { truncateResendAction } from '@/lib/chat/truncate-resend';
import { branchAtMessage } from '@/lib/message-branch';
import { copyText } from '@/lib/code-copy';
import { t } from '@/lib/locale';
import { settledLedgerForMessage } from '@/lib/turn-ledger';
import { DocCard } from './doc-card-menu';
import { UserBubble } from './UserBubble';
import { TurnLedgerCard } from './TurnLedgerCard';
import { ConfirmActions } from './ConfirmActions';
import { ImageResultCard } from './ImageResultCard';
import { VideoResultCard } from './VideoResultCard';
import { Lightbox } from '@/components/Lightbox';
import { GateWarnings } from './GateWarnings';
import { MarkdownBubble } from './MarkdownBubble';
import { MessageHoverToolbar } from './MessageHoverToolbar';
import { SuggestedActionBar } from './SuggestedActionBar';
import { DecisionFormCard, decisionFormFields } from './DecisionFormCard';
import type { MessageAffordance } from '@/lib/message-affordances';
import type { ChatMessage } from '@/types';

/** epoch ms → HH:MM（悬停工具条时间戳；无 ts 返回空串不显示） */
function formatHHMM(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/**
 * 单条聊天消息
 * user：右侧气泡（有 parts 时按文字+缩略图交错还原排版）；agent：markdown 渲染。
 * 支持 docCard（文档完成卡片）、imageCard（生图结果，可点击看原图/可拖拽）、confirm（阶段确认卡片 + 操作条）。
 * 悬停工具条：复制/编辑/分支/重新生成按 affordances 矩阵挂载，
 * 仅悬停或键盘 focus-within 可见；编辑 = 原地编辑框 → 截断重答。
 */
export function ChatMessageItem(props: {
  message: ChatMessage;
  /** 交互挂载派生结果（唯一判定源 lib/message-affordances.deriveAffordances）：
   * 确认卡挂载点（原 isLast 语义）/ 闸机「本次放行」挂载点 / 建议动作挂载点 /
   * 悬停工具条矩阵（编辑=末条用户消息；重新生成=末条普通 agent 回复；
   * 分支=agent 回复；复制=有正文；存为文档=含正文的助手消息）/
   * 暂停卡生命周期（answered/expired 时阶段卡挂徽标，回看不迷惑）
   * 与已回应暂停卡的「当时所选值」 */
  affordance: MessageAffordance;
  /** 轮次容器内渲染——作者名/meta 上提到组头，本条不再重复 */
  hideChrome?: boolean;
  /** 消息在全局数组中的下标（分支分叉点 up_to_index / 搜索跳转锚点） */
  domIndex?: number;
}) {
  const msg = () => props.message;
  const isUser = () => msg().sender === 'user';
  const navigate = useNavigate();
  /** 原图预览（lightbox）当前打开的图片地址 */
  const [lightboxUrl, setLightboxUrl] = createSignal('');
  /** 原地编辑进行中（该用户消息气泡变为编辑框） */
  const [editing, setEditing] = createSignal(false);
  /** 重新生成 in-flight 守卫（与 InlineEditBox sending 同模式：响应回来前禁二次触发） */
  const [regenerating, setRegenerating] = createSignal(false);
  /** 存为文档 in-flight 守卫（同模式：PUT 回来前禁二次触发） */
  const [savingDoc, setSavingDoc] = createSignal(false);

  /** 悬停工具条动作 */
  const doCopy = async () => {
    const ok = await copyText(msg().text || '');
    showToast(t(ok ? 'rp.msg.copied' : 'rp.code.copyFailed'), ok ? 'success' : 'warning');
  };
  const doBranch = () => {
    const idx = props.domIndex ?? chatState.messages.indexOf(msg());
    void branchAtMessage(idx);
  };
  /** 重新生成 = 截断重答无 text（机械重答最后一条用户消息，原地更新）；
   * 双击守卫：请求未回前二次点击直接忽略 */
  const doRegenerate = async () => {
    if (regenerating()) return;
    setRegenerating(true);
    try {
      await truncateResendAction();
    } finally {
      setRegenerating(false);
    }
  };
  /** 原地编辑提交：截断重答带新正文；成功后关闭编辑框（消息列表已截断刷新） */
  const submitEdit = async (text: string) => {
    const ok = await truncateResendAction(text);
    if (ok) setEditing(false);
    return ok;
  };
  /** 存为文档：不经 LLM，把该条正文直接 upsert 进项目文档；
   * 成功后 toast + 打开文档面板（stores/docs 内闭环）；双击守卫同重新生成 */
  const doSaveDoc = async () => {
    if (savingDoc()) return;
    setSavingDoc(true);
    try { await saveMessageAsDoc(msg().text || ''); } finally { setSavingDoc(false); }
  };

  /** 悬停工具条挂载判定：矩阵内任一动作可挂（系统动作行/卡片无动作不挂） */
  const hasToolbar = () => !!(
    props.affordance.copyable || props.affordance.editable || props.affordance.branchable
    || props.affordance.regenerable || props.affordance.docSavable
  );

  /** settled 账本数据源（F2 阶段二）：翻转账本优先/空账本回落 trace/actionLog
   * 重建的判定归 lib/turn-ledger 单一纯函数（settledLedgerForMessage） */
  const settledLedger = () => settledLedgerForMessage(msg());

  // Esc 关闭内联媒体原图预览（生图卡的预览由 ImageResultCard 自管）
  function onDocKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') setLightboxUrl('');
  }
  onMount(() => document.addEventListener('keydown', onDocKeyDown));
  onCleanup(() => document.removeEventListener('keydown', onDocKeyDown));

  return (
    <div class={`chat-msg ${isUser() ? 'user' : 'agent'}`} data-msg-index={props.domIndex}>
      {/* 文档完成卡片（keyed Show 避免 String()/非空断言；卡片与右键菜单归 DocCard） */}
      <Show when={msg().docCard} keyed>
        {(doc) => <DocCard doc={doc} />}
      </Show>

      {/* 生图结果卡 / 视频结果内联预览卡（拖拽/下载/lightbox 均在各自 Card 内） */}
      <Show when={msg().imageCard} keyed>{(card) => <ImageResultCard card={card} />}</Show>
      <Show when={msg().videoCard} keyed>{(card) => <VideoResultCard card={card} />}</Show>

      {/* 轮次账本卡 settled 相位（F2 阶段二渲染统一）：阶段完成卡 + 已回应标注 +
          过程时间线收敛为与流式块同一组件（TurnLedgerCard）的 settled 分支，
          相位翻转 DOM 同构；内容不进下次 LLM 上下文 */}
      <Show when={!isUser()}>
        <TurnLedgerCard
          phase="settled"
          ledger={settledLedger}
          message={msg}
          confirmState={props.affordance.confirmState}
          answeredValue={props.affordance.answeredValue}
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
        <GateWarnings message={msg()} isGateTarget={props.affordance.gateTarget} />
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
        {/* 建议动作按钮（读持久化 suggestedActions，刷新后不丢；
            重试=机械重发最近用户消息；继续=固定文本） */}
        <Show when={props.affordance.suggestedTarget && (msg().suggestedActions || []).length > 0}>
          <SuggestedActionBar actions={msg().suggestedActions || []} />
        </Show>
      </Show>

      {/* 系统动作行（如「本次放行」）：不占用户气泡形态，回看不误认为用户打过这句话 */}
      <Show when={isUser() && msg().kind === 'system_action'}>
        <div class="system-action-line">{msg().text}</div>
      </Show>

      {/* 用户气泡：编辑中原地变为编辑框（截断重答）；正常态按 parts 还原排版
          （排版还原细节归 UserBubble） */}
      <Show when={isUser() && msg().kind !== 'system_action'}>
        <UserBubble
          message={msg()}
          editing={editing}
          editable={props.affordance.editable}
          onSubmit={submitEdit}
          onCancel={() => setEditing(false)}
          onImageClick={setLightboxUrl}
        />
      </Show>

      {/* 悬停工具条（含 HH:MM 时间戳）：显隐归 CSS hover/focus-within */}
      <Show when={hasToolbar()}>
        <MessageHoverToolbar
          time={formatHHMM(msg().ts)}
          align={isUser() ? 'right' : 'left'}
          copyable={props.affordance.copyable}
          editable={props.affordance.editable && !editing()}
          branchable={props.affordance.branchable}
          regenerable={props.affordance.regenerable && !regenerating()}
          docSavable={props.affordance.docSavable && !savingDoc()}
          onCopy={() => void doCopy()}
          onEdit={() => setEditing(true)}
          onBranch={doBranch}
          onRegenerate={() => void doRegenerate()}
          onSaveDoc={() => void doSaveDoc()}
        />
      </Show>

      {/* 内联媒体原图预览 lightbox（共享组件） */}
      <Lightbox url={lightboxUrl} onClose={() => setLightboxUrl('')} />

      {/* 元信息（轮次容器内已上提到组头，不重复渲染） */}
      <Show when={msg().meta && !props.hideChrome}>
        <div class="msg-meta">{msg().meta}</div>
      </Show>

      {/* 确认操作区（仅最后一条）：fields 非空时决策表单接管，否则回落确认卡 */}
      <Show when={props.affordance.confirmTarget && decisionFormFields(msg()).length > 0} fallback={<Show when={props.affordance.confirmTarget && (msg().confirm || msg().decisionForm)}><ConfirmActions message={msg()} /></Show>}>
        <DecisionFormCard message={msg()} />
      </Show>
    </div>
  );
}
