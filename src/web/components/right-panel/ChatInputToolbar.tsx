import {
  FiArrowUp, FiBookOpen, FiFolder, FiGlobe, FiPaperclip, FiSquare,
} from 'solid-icons/fi';
import {
  agentProvider, setAgentProvider, agentModel,
} from '@/stores/agent-prefs';
import { createSignal, createEffect, onMount, onCleanup, Show, For } from 'solid-js';
import { apiProvidersFor } from '@/lib/providers';
import { getContextUsage, type ContextUsage } from '@/api/agent';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { formatTokens } from '@/lib/utils';
import { PillDropdown } from './PillDropdown';
import { ModelThinkingPill } from './ModelThinkingPill';
import { SkillPicker } from './SkillPicker';
import { StudioAssetPickerModal } from './StudioAssetPickerModal';

/**
 * 聊天输入框底部工具栏：上传 + API/模型/Skill/素材库/文档 胶囊 + 圆形发送键。
 * 从 ChatInput 拆出，保持主组件精简（架构铁律 10.1：单文件 ≤ 250 行）。
 */
export function ChatInputToolbar(props: {
  busy: boolean;
  onUpload: () => void;
  onSend: () => void;
  onStop: () => void;
  onOpenCanvas: () => void;
  onViewSkillDoc: () => void;
}) {
  const providerOptions = () =>
    apiProvidersFor('chat').map((p) => ({
      value: p.id,
      label: p.name || p.id,
      hint: p.protocol,
    }));
  /** 「素材库」选择弹窗开关 */
  const [assetPickerOpen, setAssetPickerOpen] = createSignal(false);

  /** 上下文用量（发送按钮旁小圆圈，悬停显示已用多少K） */
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  function refreshUsage() {
    void getContextUsage(agentModel(), agentProvider()).then(setUsage).catch(() => { /* 后端未就绪静默 */ });
  }
  onMount(refreshUsage);
  // 消息数量变化（发送/回复完成）后刷新用量
  createEffect(() => {
    void chatState.messages.length;
    refreshUsage();
  });
  // 推理中持续刷新：Agent 边执行边消耗上下文（每批操作落盘后用量都在变），
  // 由 tool_started/tool_finished 事件（本轮账本 turnLedger.items 变化）驱动，不再固定轮询
  createEffect(() => {
    if (!chatState.isStreaming) return;
    void chatState.turnLedger.items.length;
    refreshUsage();
  });
  // 推理中 15s 轮询兜底（反馈：长规划轮没有工具事件，用量几分钟不动；
  //  降频合并：事件驱动为主，轮询仅作低频兜底）。
  // 后端 live 度量在每次 LLM 调用前更新，轮询即可看到用量随步骤增长
  createEffect(() => {
    if (!chatState.isStreaming) return;
    const timer = setInterval(refreshUsage, 15000);
    onCleanup(() => clearInterval(timer));
  });
  const usageLabel = () => {
    const u = usage();
    if (!u) return '…';
    return formatTokens(u.est_tokens);
  };
  /** 圆环填充比 = 已用 / 窗口；未传模型时回退 0（纯数字展示） */
  const ratio = () => {
    const u = usage();
    if (!u || !u.window_tokens) return 0;
    return Math.min(1, u.est_tokens / u.window_tokens);
  };
  const ringClass = () => {
    const r = ratio();
    return r >= 0.85 ? 'hot' : r >= 0.6 ? 'warn' : 'ok';
  };
  // 第 5 批：悬停面板数据（参考 外部标杆 式上下文容量卡）
  const bd = () => usage()?.breakdown ?? null;
  const winTokens = () => usage()?.window_tokens || bd()?.budget || 0;
  const totalTokens = () => bd()?.total ?? usage()?.est_tokens ?? 0;
  const pctOfWindow = () => {
    const w = winTokens();
    return w ? Math.min(100, (totalTokens() / w) * 100) : 0;
  };
  const cacheHitLabel = () =>
    `${(((usage()?.cache_hit_rate) ?? 0) * 100).toFixed(1)}%`;
  const panelRows = () => {
    const b = bd();
    if (!b) return [];
    const total = b.total || 1;
    const mk = (label: string, val: number, muted = false) => ({
      label, pct: (Math.max(0, val) / total) * 100, muted,
    });
    return [
      mk(t('rp.ctx.msgs'), b.history),
      mk(t('rp.ctx.system'), b.system - b.skill),
      mk(t('rp.ctx.state'), b.state),
      mk(t('rp.ctx.skill'), b.skill),
      mk(t('rp.ctx.other'), b.tools, true),
    ];
  };

  return (
    <div class="chat-input-toolbar">
      <div class="toolbar-left">
        <button
          type="button"
          class="toolbar-pill-btn"
          title={t('rp.toolbar.upload')}
          onClick={() => props.onUpload()}
        >
          <FiPaperclip size={13} />
        </button>
        <PillDropdown
          icon={FiGlobe}
          value={agentProvider()}
          options={providerOptions()}
          title={t('rp.toolbar.providerTitle')}
          onSelect={setAgentProvider}
        />
        {/* 模型+推理等级组合胶囊（Codex 样式两节下拉） */}
        <ModelThinkingPill />
        <SkillPicker />
        <button
          type="button"
          class="toolbar-pill-btn"
          title={t('rp.toolbar.assetsTitle')}
          onClick={() => setAssetPickerOpen(true)}
        >
          <FiFolder size={11} />
          <span class="pill-option-label">{t('rp.toolbar.assets')}</span>
        </button>
        <StudioAssetPickerModal
          open={assetPickerOpen()}
          onClose={() => setAssetPickerOpen(false)}
          onOpenCanvas={props.onOpenCanvas}
        />
        <button
          type="button"
          class="toolbar-pill-btn"
          title={t('rp.toolbar.skillDoc')}
          onClick={() => props.onViewSkillDoc()}
        >
          <FiBookOpen size={13} />
        </button>
      </div>
      <div class="toolbar-right">
        {/* 上下文用量状态图标：悬停显示已用多少K上下文 */}
        <div class="context-usage-wrap">
          <button
            type="button"
            class="context-usage-btn"
            aria-label={t('rp.toolbar.contextUsage')}
            onClick={refreshUsage}
          >
            <svg class={`ctx-ring ${ringClass()}`} width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <circle class="ctx-ring-bg" cx="7" cy="7" r="5.5" />
              <circle class="ctx-ring-fg" cx="7" cy="7" r="5.5" />
            </svg>
            <span class="context-usage-value">{usageLabel()}</span>
          </button>
          <div class="context-usage-tip ctx-panel" role="tooltip">
            <Show when={usage()} fallback={<div class="ctx-loading">{t('rp.toolbar.contextLoading')}</div>}>
              <div class="ctx-head">
                <span>{t('rp.ctx.title')}</span>
                <span class="ctx-head-val">
                  {formatTokens(totalTokens())}/{winTokens() ? formatTokens(winTokens()) : '—'}
                  {' '}({pctOfWindow().toFixed(1)}%)
                </span>
              </div>
              <div class="ctx-bar">
                <div class="ctx-bar-fg" style={{ width: `${pctOfWindow().toFixed(1)}%` }} />
              </div>
              <For each={panelRows()}>
                {(r) => (
                  <div class="ctx-row">
                    <span class={`ctx-dot${r.muted ? ' muted' : ''}`} />
                    <span class="ctx-row-label">{r.label}</span>
                    <span class="ctx-row-pct">{r.pct.toFixed(1)}%</span>
                  </div>
                )}
              </For>
              <div class="ctx-foot">
                <span>{t('rp.ctx.cacheHit')}</span>
                <span>{cacheHitLabel()}</span>
              </div>
            </Show>
          </div>
        </div>
        {/* 推理中：停止键与发送键分离——发送继续可用（消息进排队引导区） */}
        <Show when={props.busy}>
          <button
            type="button"
            class="send-btn send-btn-stop"
            title={t('rp.toolbar.stop')}
            onClick={() => props.onStop()}
          >
            <FiSquare size={13} />
          </button>
        </Show>
        {/* Agent 运行时隐藏发送键（用户决策：只保留停止键） */}
        <Show when={!props.busy}>
          <button
            type="button"
            class="send-btn"
            title={t('rp.toolbar.send')}
            onClick={() => props.onSend()}
          >
            <FiArrowUp size={15} />
          </button>
        </Show>
      </div>
    </div>
  );
}
