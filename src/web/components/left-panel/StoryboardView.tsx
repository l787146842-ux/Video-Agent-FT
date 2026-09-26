import { createSignal, createEffect, For, Show } from 'solid-js';
import { FiArrowDown, FiArrowUp, FiPlus, FiTrash2 } from 'solid-icons/fi';
import {
  state, studioActions, categoryForSubTab,
} from '@/stores/studio';
import { reorderGroups } from '@/api/storyboard';
import { checkpointHistory } from '@/stores/history';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { showToast } from '@/stores/toast';
import { BatchGenBar } from './BatchGenBar';
import { GroupCard } from './GroupCard';
import type { AnyGroup, DraftType, SubTab } from '@/types';

const SUB_TABS: Array<{ key: SubTab; label: string }> = [
  { key: 'keyElements', label: '关键元素' },
  { key: 'shots', label: '分镜' },
  { key: 'audio', label: '音频' },
];

/** 当前 subTab 对应的分组名称（右键菜单文案用） */
function groupKindLabel(subTab: SubTab): string {
  return subTab === 'keyElements' ? '关键元素' : subTab === 'shots' ? '分镜' : '音频';
}

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

  // ===== 列表右键菜单：向上/向下插入、删除 =====

  /** 删除分组（带二次确认） */
  async function deleteGroup(group: AnyGroup) {
    const ok = await confirmDialog({
      title: `删除「${group.title || '未命名分组'}」？`,
      message: '分组内的全部草稿将一并删除，删除后可通过 Ctrl+Z 撤销恢复。',
      confirmText: '删除',
      danger: true,
    });
    if (ok) {
      // 先压撤销检查点再删（同 DraftCard.handleDelete 口径，兑现弹窗文案的 Ctrl+Z 承诺）
      await checkpointHistory();
      studioActions.removeGroupLocal(state.subTab, group.id);
    }
  }

  /** 分组卡片右键：基于该分组位置插入 / 删除 */
  function onGroupContextMenu(e: MouseEvent, group: AnyGroup, idx: number) {
    const label = groupKindLabel(state.subTab);
    showContextMenu(e, [
      { label: `向上插入${label}`, icon: FiArrowUp, onClick: () => studioActions.insertGroupLocal(state.subTab, idx) },
      { label: `向下插入${label}`, icon: FiArrowDown, onClick: () => studioActions.insertGroupLocal(state.subTab, idx + 1) },
      { label: '删除', icon: FiTrash2, danger: true, onClick: () => void deleteGroup(group) },
    ]);
  }

  /** 列表空白处右键：末尾新增（卡片上的右键由 onGroupContextMenu 处理，已阻止冒泡） */
  function onListContextMenu(e: MouseEvent) {
    if (e.target !== e.currentTarget) return; // 只响应容器本身的空白区
    const label = groupKindLabel(state.subTab);
    showContextMenu(e, [
      { label: `新增${label}（末尾）`, icon: FiPlus, onClick: () => studioActions.addGroupLocal(state.subTab) },
    ]);
  }

  // ===== Agent 联动更新后的闪烁提示 =====
  let containerRef: HTMLDivElement | undefined;
  createEffect(() => {
    if (!state.lastAppliedAt || !containerRef) return;
    containerRef.classList.remove('board-flash');
    void containerRef.offsetWidth; // reflow 重启动画
    containerRef.classList.add('board-flash');
  });

  // ===== 预览框导航按钮 / 分镜引用跳转：滚动定位到目标卡片并闪烁高亮 =====
  createEffect(() => {
    const tick = state.locateTick;
    if (!tick) return;
    // 等 subTab 切换后的重渲染完成，再查找目标 DOM
    // 2026-09-25 修（跳转「毫无反应」根因）：DOUBLE_RETRY 帧内查不到目标时**不再
    // 静默 return**（旧实现 `if (!target) return;` 无任何反馈，用户看到点了没反应）；
    // 改为短重试一轮（DOM 尚未渲染完是常态），仍失败则如实提示。
    let tries = 0;
    const locate = () => {
      // 优先按分组定位（分镜 shotRefs 跳转：目标元素没有草稿卡时也能看到）
      const gid = state.locateGroupId;
      let target: HTMLElement | null = null;
      if (gid) {
        target = Array.from(containerRef?.querySelectorAll<HTMLElement>('.sb-group') || [])
          .find((g) => g.dataset.groupId === gid) || null;
      }
      if (!target) {
        target = containerRef?.querySelector('.draft-card.active') as HTMLElement | null;
      }
      if (!target) {
        if (tries++ < 3) {
          requestAnimationFrame(() => requestAnimationFrame(locate));
          return;
        }
        // 失败可见（原先静默）：左栏收起或未挂载在故事板页时命中此支
        showToast('已在故事板定位，请展开左侧面板查看', 'info');
        return;
      }
      const el = target;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.remove('locate-flash');
      void el.offsetWidth;
      el.classList.add('locate-flash');
      setTimeout(() => el.classList.remove('locate-flash'), 1500);
    };
    requestAnimationFrame(() => requestAnimationFrame(locate));
  });

  return (
    <div class="storyboard-section">
      {/* SubTab 导航（吸顶：列表滚动时始终固定在顶部） */}
      <div class="sub-nav-sticky">
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
      </div>

      <BatchGenBar />

      {/* 分组列表（空白处右键可在末尾新增） */}
      <div ref={containerRef} class="storyboard-list" onContextMenu={onListContextMenu}>
        <For each={groups()}>
          {(group, idx) => (
            <GroupCard
              group={group}
              type={draftType()}
              index={idx() + 1}
              dragOver={dragOverId() === group.id}
              onContextMenu={(e) => onGroupContextMenu(e, group, idx())}
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
