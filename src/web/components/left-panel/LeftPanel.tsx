import { Switch, Match } from 'solid-js';
import { FiFolder, FiGrid } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { StoryboardView } from './StoryboardView';
import { UncategorizedView } from './UncategorizedView';
import { SnapshotHistoryBar } from './SnapshotHistoryBar';
import { BoardConflictPanel } from './BoardConflictPanel';
import type { LeftTab } from '@/types';

const TABS: Array<{ key: LeftTab; label: string; icon: typeof FiGrid }> = [
  { key: 'storyboard', label: '故事板', icon: FiGrid },
  { key: 'uncategorized', label: '未归类素材', icon: FiFolder },
];

/**
 * 左侧面板容器：LeftTab 切换（故事板 / 未归类素材）。
 * 子任务面板已迁至中间面板（顶栏入口切换 middleView），
 * 本面板任意点击 = 中间面板切回预览框。
 */
export default function LeftPanel() {
  return (
    <div
      class="panel-column"
      onClick={() => studioActions.setMiddleView('preview')}
    >
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

      {/* 内容区 */}
      <div class="left-content">
        <Switch>
          <Match when={state.leftTab === 'storyboard'}>
            <StoryboardView />
          </Match>
          <Match when={state.leftTab === 'uncategorized'}>
            <UncategorizedView />
          </Match>
        </Switch>
      </div>

      {/* E1 故事板版本列表（快照指针清单；回退经二次确认 + 后端生成中禁回退） */}
      <SnapshotHistoryBar />

      {/* G1 故事板冲突面板（与 Agent 写入同改一处时逐项定夺；固定遮罩全屏层） */}
      <BoardConflictPanel />
    </div>
  );
}
