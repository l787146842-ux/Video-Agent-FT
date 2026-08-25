import { createSignal, onCleanup, For, Show } from 'solid-js';
import {
  FiCheck, FiChevronDown, FiFolder, FiFolderPlus, FiTrash2, FiX,
} from 'solid-icons/fi';
import { state as studioState } from '@/stores/studio';
import type { Project } from '@/types';
import { useProjectActions } from './use-project-actions';

/**
 * 项目切换器：Header 右侧下拉
 * 切换/新建/删除项目 → 后端返回完整状态快照 → 重置前端 store
 * ：列表加载/切换/删除/新建动作与快照应用切至 use-project-actions，
 * 本组件只留下拉开合与视图，行为零变更。
 */
export function ProjectSwitcher() {
  const [open, setOpen] = createSignal(false);

  let containerRef: HTMLDivElement | undefined;

  const pa = useProjectActions(() => setOpen(false));

  function toggle() {
    const next = !open();
    setOpen(next);
    if (next) void pa.load();
    else pa.setCreating(false);
  }

  // 点击外部关闭菜单（用 pointerdown 而非 click，避免 SolidJS 同步 DOM 更新后 contains 失效）
  function onDocPointerDown(e: PointerEvent) {
    if (containerRef && !containerRef.contains(e.target as Node)) {
      setOpen(false);
      pa.setCreating(false);
    }
  }
  document.addEventListener('pointerdown', onDocPointerDown);
  onCleanup(() => document.removeEventListener('pointerdown', onDocPointerDown));

  function formatTime(p: Project): string {
    if (!p.updated_at) return '';
    const d = new Date(p.updated_at);
    if (Number.isNaN(d.getTime())) return p.updated_at.replace('T', ' ').slice(5, 16);
    const pad = (n: number) => String(n).padStart(2, '0');
    // 后端存 UTC（Z 结尾），这里转本地时区显示，避免差 8 小时（现场）
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  return (
    <div class="project-switcher" ref={containerRef}>
      <button type="button" class="project-switcher-btn" onClick={toggle}>
        <FiFolder size={14} class="opacity-70" />
        <span class="project-switcher-name">
          {studioState.projectName || '未命名项目'}
        </span>
        <FiChevronDown size={13} class="opacity-50" />
      </button>

      <Show when={open()}>
        <div class="project-dropdown">
          <div class="project-dropdown-list">
            <For each={pa.projects()}>
              {(p) => {
                const isActive = () => p.id === pa.activeId();
                return (
                  <div
                    role="button"
                    tabIndex={0}
                    class={`project-option ${isActive() ? 'active' : ''}`}
                    onClick={() => void pa.doSwitch(p.id)}
                    onKeyDown={(e) => e.key === 'Enter' && void pa.doSwitch(p.id)}
                  >
                    {isActive() ? (
                      <FiCheck size={14} class="option-check" />
                    ) : (
                      <FiFolder size={14} class="option-folder" />
                    )}
                    <span class="project-option-name">{p.name}</span>
                    <span class="project-option-time">{formatTime(p)}</span>
                    <Show when={pa.projects().length > 1}>
                      <span
                        role="button"
                        tabIndex={0}
                        class="project-option-delete"
                        title="删除项目"
                        onClick={(e) => {
                          e.stopPropagation();
                          void pa.doDelete(p.id, p.name);
                        }}
                        onKeyDown={(e) => e.stopPropagation()}
                      >
                        <FiTrash2 size={13} />
                      </span>
                    </Show>
                  </div>
              );
            }}
            </For>
            <Show when={pa.loading() && !pa.projects().length}>
              <div class="project-skeleton">
                <span class="skeleton-bar" style={{ width: '70%' }} />
                <span class="skeleton-bar" style={{ width: '55%' }} />
                <span class="skeleton-bar" style={{ width: '65%' }} />
              </div>
            </Show>
            <Show when={!pa.loading() && !pa.projects().length}>
              <div class="empty-state">暂无项目</div>
            </Show>
          </div>

          <div class="project-dropdown-divider" />

          <Show
            when={pa.creating()}
            fallback={
              <button
                type="button"
                class="project-create-btn"
                onClick={(e) => { e.stopPropagation(); pa.setCreating(true); }}
              >
                <FiFolderPlus size={14} />
                <span>新建项目</span>
              </button>
            }
          >
            <div class="project-create-row">
              <input
                type="text"
                class="project-create-input"
                placeholder="新项目名称"
                value={pa.newName()}
                onInput={(e) => pa.setNewName(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void pa.doCreate();
                  if (e.key === 'Escape') pa.setCreating(false);
                }}
                ref={(el) => setTimeout(() => el.focus())}
              />
              <button
                type="button"
                class="project-create-action text-accent-emerald"
                title="确认创建"
                onClick={() => void pa.doCreate()}
              >
                <FiCheck size={13} />
              </button>
              <button
                type="button"
                class="project-create-action text-text-dim"
                title="取消"
                onClick={() => pa.setCreating(false)}
              >
                <FiX size={13} />
              </button>
            </div>
          </Show>
        </div>
      </Show>
    </div>
  );
}
