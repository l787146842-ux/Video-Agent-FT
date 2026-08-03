import {
  FiArrowUp, FiBookOpen, FiCpu, FiFolder, FiGlobe, FiPaperclip, FiSquare,
} from 'solid-icons/fi';
import {
  agentProvider, setAgentProvider, agentModel, setAgentModel,
} from '@/stores/agent-prefs';
import { createSignal } from 'solid-js';
import { apiProvidersFor, providerModels } from '@/lib/providers';
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
        <button
          type="button"
          class={`send-btn ${props.busy ? 'send-btn-busy' : ''}`}
          title={props.busy ? t('rp.toolbar.stop') : t('rp.toolbar.send')}
          onClick={() => (props.busy ? props.onStop() : props.onSend())}
        >
          {props.busy ? <FiSquare size={13} /> : <FiArrowUp size={15} />}
        </button>
      </div>
    </div>
  );
}
