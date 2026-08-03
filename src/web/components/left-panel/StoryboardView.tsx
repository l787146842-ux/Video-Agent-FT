import { createSignal, createEffect, For, Show } from 'solid-js';
import {
  state, studioActions, categoryForSubTab,
} from '@/stores/studio';
import { reorderGroups } from '@/api/storyboard';
import { BatchGenBar } from './BatchGenBar';
import { GroupCard } from './GroupCard';
import type { AnyGroup, DraftType, SubTab } from '@/types';

const SUB_TABS: Array<{ key: SubTab; label: string }> = [
  { key: 'keyElements', label: '关键元素' },
  { key: 'shots', label: '分镜' },
  { key: 'audio', label: '音频' },
];

/**
 * 故事板视图：SubTab 切换 + 批量生成 + 分组列表（<For> keyed diff）
 * 分组级 HTML5 拖拽排序 → 本地重排 + 后端持久化。
 */
export function StoryboardView() {
  const groups = (): AnyGroup[] => {
    switch (state.subTab) {
      case 'shots': return state.shots;
      case 'audio': return state.audioItems;
      default: return state.keyElements;
    }
  };

  const draftType = (): DraftType =>
    state.subTab === 'shots' ? 'shot' : state.subTab === 'audio' ? 'audio' : 'keyElement';

  // ===== 分组拖拽排序 =====
  const [dragSrcId, setDragSrcId] = createSignal<string | null>(null);
  const [dragOverId, setDragOverId] = createSignal<string | null>(null);

  function resetDrag() {
    setDragSrcId(null);
    setDragOverId(null);
  }

  function handleDrop(targetId: string) {
    const srcId = dragSrcId();
    if (srcId && srcId !== targetId) {
      studioActions.reorderGroupsLocal(state.subTab, srcId, targetId);
      reorderGroups(
        categoryForSubTab(state.subTab),
        groups().map((g) => g.id),
      );
    }
    resetDrag();
  }

  // ===== Agent 联动更新后的闪烁提示 =====
  let containerRef: HTMLDivElement | undefined;
  createEffect(() => {
    if (!state.lastAppliedAt || !containerRef) return;
    containerRef.classList.remove('board-flash');
    void containerRef.offsetWidth; // reflow 重启动画
    containerRef.classList.add('board-flash');
  });

  return (
    <div class="storyboard-section">
      {/* SubTab 导航 */}
      <div class="sub-nav">
        <For each={SUB_TABS}>
          {(tab) => (
            <button
              type="button"
              class={`sub-nav-btn ${state.subTab === tab.key ? 'active' : ''}`}
              onClick={() => studioActions.setSubTab(tab.key)}
            >
              {tab.label}
            </button>
          )}
        </For>
      </div>

      <BatchGenBar />

      {/* 分组列表 */}
      <div ref={containerRef} class="storyboard-list">
        <For each={groups()}>
          {(group, idx) => (
            <GroupCard
              group={group}
              type={draftType()}
              index={idx() + 1}
              dragOver={dragOverId() === group.id}
              onDragStart={(e) => {
                setDragSrcId(group.id);
                e.dataTransfer!.effectAllowed = 'move';
              }}
              onDragOver={(e) => {
                e.preventDefault();
                if (dragSrcId() && dragSrcId() !== group.id) {
                  setDragOverId(group.id);
                }
              }}
              onDragLeave={() => {
                if (dragOverId() === group.id) setDragOverId(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                handleDrop(group.id);
              }}
              onDragEnd={resetDrag}
            />
          )}
        </For>
        <Show when={!groups().length}>
          <div class="empty-state centered">
            暂无分组，点击下方 + 添加，或让 Agent 帮你创建
          </div>
        </Show>
      </div>

      {/* 底部添加分组按钮 */}
      <button
        type="button"
        class="add-group-btn"
        title="添加新分组"
        onClick={() => studioActions.addGroupLocal(state.subTab)}
      >
        + 添加{state.subTab === 'keyElements' ? '关键元素' : state.subTab === 'shots' ? '分镜' : '音频'}
      </button>
    </div>
  );
}
