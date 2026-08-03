import {
  FiArrowUp, FiBookOpen, FiCpu, FiFolder, FiGlobe, FiPaperclip, FiSquare,
} from 'solid-icons/fi';
import {
  agentProvider, setAgentProvider, agentModel, setAgentModel,
} from '@/stores/agent-prefs';
import { createSignal } from 'solid-js';
import { apiProvidersFor, providerModels } from '@/lib/providers';
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
          title="上传参考素材或文档"
          onClick={() => props.onUpload()}
        >
          <FiPaperclip size={13} />
        </button>
        <PillDropdown
          icon={FiGlobe}
          value={agentProvider()}
          options={providerOptions()}
          title="API 平台选择"
          onSelect={setAgentProvider}
        />
        <PillDropdown
          icon={FiCpu}
          value={agentModel()}
          options={modelOptions()}
          title="Agent 模型选择"
          onSelect={setAgentModel}
        />
        <SkillPicker />
        <button
          type="button"
          class="toolbar-pill-btn"
          title="素材库：从故事板/未归类素材中选取媒体发送到对话框"
          onClick={() => setAssetPickerOpen(true)}
        >
          <FiFolder size={11} />
          <span class="pill-option-label">素材库</span>
        </button>
        <StudioAssetPickerModal
          open={assetPickerOpen()}
          onClose={() => setAssetPickerOpen(false)}
          onOpenCanvas={props.onOpenCanvas}
        />
        <button
          type="button"
          class="toolbar-pill-btn"
          title="查看/编辑当前 Skill 流程文档"
          onClick={() => props.onViewSkillDoc()}
        >
          <FiBookOpen size={13} />
        </button>
      </div>
      <div class="toolbar-right">
        <button
          type="button"
          class={`send-btn ${props.busy ? 'send-btn-busy' : ''}`}
          title={props.busy ? '停止生成' : '发送'}
          onClick={() => (props.busy ? props.onStop() : props.onSend())}
        >
          {props.busy ? <FiSquare size={13} /> : <FiArrowUp size={15} />}
        </button>
      </div>
    </div>
  );
}
