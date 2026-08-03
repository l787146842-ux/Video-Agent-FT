import { Show } from 'solid-js';
import { FiFolder, FiGrid } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { StoryboardView } from './StoryboardView';
import { UncategorizedView } from './UncategorizedView';
import type { LeftTab } from '@/types';

const TABS: Array<{ key: LeftTab; label: string; icon: typeof FiGrid }> = [
  { key: 'storyboard', label: '故事板', icon: FiGrid },
  { key: 'uncategorized', label: '未归类素材', icon: FiFolder },
];

/**
 * 左侧面板容器：LeftTab 切换（故事板 / 未归类素材）
 */
export default function LeftPanel() {
  return (
    <div class="panel-column">
      {/* 顶部 Tab（旧版 left-tabs：左对齐 + 蓝色下划线激活） */}
      <div class="left-tabs">
        {TABS.map((tab) => (
          <button
            type="button"
            class={`left-tab-btn ${state.leftTab === tab.key ? 'active' : ''}`}
            onClick={() => studioActions.setLeftTab(tab.key)}
          >
            <tab.icon size={14} />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div class="left-content">
        <Show when={state.leftTab === 'storyboard'} fallback={<UncategorizedView />}>
          <StoryboardView />
        </Show>
      </div>
    </div>
  );
}
