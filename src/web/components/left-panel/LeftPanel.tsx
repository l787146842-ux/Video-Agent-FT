import { Show } from 'solid-js';
import { FiFolder, FiGrid, FiList } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { StoryboardView } from './StoryboardView';
import { UncategorizedView } from './UncategorizedView';
import PlanView from './PlanView';
import { SnapshotHistoryBar } from './SnapshotHistoryBar';
import { BoardConflictPanel } from './BoardConflictPanel';
import type { LeftTab } from '@/types';

const TABS: Array<{ key: LeftTab; label: string; icon: typeof FiGrid }> = [
  { key: 'storyboard', label: '故事板', icon: FiGrid },
  { key: 'uncategorized', label: '未归类素材', icon: FiFolder },
  { key: 'plan', label: '计划', icon: FiList },
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
        {/* 故事板保存状态（D1）：保存中 / 已保存 / 保存失败 */}
        <span class={`board-save-status ${state.boardSaveStatus}`}>
          {state.boardSaveStatus === 'saving' ? '保存中…'
            : state.boardSaveStatus === 'error' ? '保存失败'
              : '已保存'}
        </span>
      </div>

      {/* 内容区（计划面板只读：写通道唯一 = 模型 plan_write 工具） */}
      <div class="left-content">
        <Show when={state.leftTab === 'storyboard'}
          fallback={state.leftTab === 'plan' ? <PlanView /> : <UncategorizedView />}>
          <StoryboardView />
        </Show>
      </div>

      {/* E1 故事板版本列表（快照指针清单；回退经二次确认 + 后端生成中禁回退） */}
      <SnapshotHistoryBar />

      {/* G1 故事板冲突面板（与 Agent 写入同改一处时逐项定夺；固定遮罩全屏层） */}
      <BoardConflictPanel />
    </div>
  );
}
