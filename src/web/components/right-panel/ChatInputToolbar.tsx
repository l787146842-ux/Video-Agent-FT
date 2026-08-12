import {
  FiArrowUp, FiBookOpen, FiCpu, FiFolder, FiGlobe, FiPaperclip, FiSquare,
} from 'solid-icons/fi';
import {
  agentProvider, setAgentProvider, agentModel, setAgentModel,
} from '@/stores/agent-prefs';
import { createSignal, createEffect, onMount, Show } from 'solid-js';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { getContextUsage, type ContextUsage } from '@/api/agent';
import { chatState } from '@/stores/chat';
import { t } from '@/lib/locale';
import { PillDropdown } from './PillDropdown';
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
  const modelOptions = () =>
    providerModels(agentProvider(), 'chat').map((m) => ({ value: m, label: m }));
  /** 「素材库」选择弹窗开关 */
  const [assetPickerOpen, setAssetPickerOpen] = createSignal(false);

  /** 上下文用量（发送按钮旁小圆圈，悬停显示已用多少K） */
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  function refreshUsage() {
    void getContextUsage(agentModel()).then(setUsage).catch(() => { /* 后端未就绪静默 */ });
  }
  onMount(refreshUsage);
  // 消息数量变化（发送/回复完成）后刷新用量
  createEffect(() => {
    void chatState.messages.length;
    refreshUsage();
  });
  // 推理中持续刷新：Agent 边执行边消耗上下文（每批操作落盘后用量都在变），
  // 由 tool_started/tool_finished 事件（streamingTools 变化）驱动，不再固定轮询
  createEffect(() => {
    if (!chatState.isStreaming) return;
    void chatState.streamingTools.length;
    refreshUsage();
  });
  const usageLabel = () => {
    const u = usage();
    if (!u) return '…';
    return `${(u.est_tokens / 1024).toFixed(1)}K`;
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
        <PillDropdown
          icon={FiCpu}
          value={agentModel()}
          options={modelOptions()}
          title={t('rp.toolbar.modelTitle')}
          onSelect={setAgentModel}
        />
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
            aria-label="上下文用量"
            onClick={refreshUsage}
          >
            <svg class={`ctx-ring ${ringClass()}`} width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <circle class="ctx-ring-bg" cx="7" cy="7" r="5.5" />
              <circle class="ctx-ring-fg" cx="7" cy="7" r="5.5" stroke-dasharray={`${(ratio() * 34.56).toFixed(1)} 34.56`} />
            </svg>
            <span class="context-usage-value">{usageLabel()}</span>
          </button>
          <div class="context-usage-tip" role="tooltip">
            {usage() ? `${(usage()!.est_tokens / 1024).toFixed(1)}K 上下文已使用` : '统计中…'}
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
        <button
          type="button"
          class={`send-btn ${props.busy ? 'busy' : ''}`}
          title={props.busy ? '发送（排队，完成后自动发出）' : t('rp.toolbar.send')}
          onClick={() => props.onSend()}
        >
          <FiArrowUp size={15} />
        </button>
      </div>
    </div>
  );
}
