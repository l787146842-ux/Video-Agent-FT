import { createSignal, onCleanup, For, Show } from 'solid-js';
import {
  FiCheck, FiChevronDown, FiFolder, FiFolderPlus, FiTrash2, FiX,
} from 'solid-icons/fi';
import {
  getProjects, switchProject, deleteProject, createProject,
} from '@/api/project';
import { studioActions, state as studioState, persistBoard } from '@/stores/studio';
import { chatActions } from '@/stores/chat';
import { convActions } from '@/stores/conversations';
import { stopAgentStream } from '@/hooks/use-sse';
import { showToast } from '@/stores/toast';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { refreshHistoryStatus } from '@/stores/history';
import type { Project, ServerStateSnapshot } from '@/types';

/**
 * 项目切换器：Header 右侧下拉
 * 切换/新建/删除项目 → 后端返回完整状态快照 → 重置前端 store
 */
export function ProjectSwitcher() {
  const [open, setOpen] = createSignal(false);
  const [projects, setProjects] = createSignal<Project[]>([]);
  const [activeId, setActiveId] = createSignal('');
  const [creating, setCreating] = createSignal(false);
  const [newName, setNewName] = createSignal('');
  const [loading, setLoading] = createSignal(false);

  let containerRef: HTMLDivElement | undefined;

  async function load() {
    setLoading(true);
    try {
      const data = await getProjects();
      setProjects(data.projects || []);
      setActiveId(data.active_project_id || '');
    } catch {
      showToast('项目列表加载失败', 'error');
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !open();
    setOpen(next);
    if (next) load();
    else setCreating(false);
  }

  /** 项目变更后整体重置前端状态 */
  function applySnapshot(snapshot?: ServerStateSnapshot | null) {
    if (!snapshot) return;
    studioActions.resetForProject(snapshot);
    chatActions.loadMessages(snapshot.chatMessages || []);
    // 项目切换后多对话标签栏随之重置
    convActions.loadFromSnapshot(snapshot);
    // 切换项目会清空后端 undo/redo 栈，同步指示位
    void refreshHistoryStatus();
  }

  /** 变更项目前的统一前置动作：
   * 1) 中止旧项目正在进行的 Agent 流（防止旧回复/旧快照串入新项目）；
   * 2) 冲刷当前项目挂起的防抖保存（确保旧项目最新修改先落盘，
   *    避免切换后残留 PUT 把旧数据写进新项目）。 */
  async function beforeProjectMutation() {
    stopAgentStream();
    try {
      await persistBoard.flush();
    } catch { /* 保存失败不阻断项目操作 */ }
  }

  async function doSwitch(id: string) {
    if (id === activeId()) {
      setOpen(false);
      return;
    }
    try {
      await beforeProjectMutation();
      const data = await switchProject(id);
      if (!data.ok) throw new Error(data.message || '切换失败');
      applySnapshot(data.state);
      setOpen(false);
      showToast(`已切换到项目：${data.state?.project_name || id}`, 'success');
    } catch (e) {
      showToast(`切换项目失败：${(e as Error).message}`, 'error');
    }
  }

  async function doDelete(id: string, name: string) {
    const ok = await confirmDialog({
      title: `删除项目「${name}」？`,
      message: '项目的全部故事板、素材与对话将被删除，此操作不可撤销。',
      confirmText: '删除项目',
      danger: true,
    });
    if (!ok) return;
    try {
      await beforeProjectMutation();
      const data = await deleteProject(id);
      if (!data.ok) throw new Error(data.message || '删除失败');
      applySnapshot(data.state);
      await load();
      showToast(`已删除项目：${name}`, 'success');
    } catch (e) {
      showToast(`删除失败：${(e as Error).message}`, 'error');
    }
  }

  async function doCreate() {
    const name = newName().trim();
    if (!name) return;
    try {
      await beforeProjectMutation();
      const data = await createProject(name);
      if (!data.ok) throw new Error(data.message || '新建项目失败');
      applySnapshot(data.state);
      setCreating(false);
      setNewName('');
      setOpen(false);
      showToast(`已创建新项目：${name}`, 'success');
    } catch (e) {
      showToast(`新建项目失败：${(e as Error).message}`, 'error');
    }
  }

  // 点击外部关闭菜单（用 pointerdown 而非 click，避免 SolidJS 同步 DOM 更新后 contains 失效）
  function onDocPointerDown(e: PointerEvent) {
    if (containerRef && !containerRef.contains(e.target as Node)) {
      setOpen(false);
      setCreating(false);
    }
  }
  document.addEventListener('pointerdown', onDocPointerDown);
  onCleanup(() => document.removeEventListener('pointerdown', onDocPointerDown));

  function formatTime(p: Project): string {
    if (!p.updated_at) return '';
    const d = new Date(p.updated_at);
    if (Number.isNaN(d.getTime())) return p.updated_at.replace('T', ' ').slice(5, 16);
    const pad = (n: number) => String(n).padStart(2, '0');
    // 后端存 UTC（Z 结尾），这里转本地时区显示，避免差 8 小时（7777 现场）
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
            <For each={projects()}>
              {(p) => {
                const isActive = () => p.id === activeId();
                return (
                  <div
                    role="button"
                    tabIndex={0}
                    class={`project-option ${isActive() ? 'active' : ''}`}
                    onClick={() => doSwitch(p.id)}
                    onKeyDown={(e) => e.key === 'Enter' && doSwitch(p.id)}
                  >
                    {isActive() ? (
                      <FiCheck size={14} class="option-check" />
                    ) : (
                      <FiFolder size={14} class="option-folder" />
                    )}
                    <span class="project-option-name">{p.name}</span>
                    <span class="project-option-time">{formatTime(p)}</span>
                    <Show when={projects().length > 1}>
                      <span
                        role="button"
                        tabIndex={0}
                        class="project-option-delete"
                        title="删除项目"
                        onClick={(e) => {
                          e.stopPropagation();
                          doDelete(p.id, p.name);
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
            <Show when={loading() && !projects().length}>
              <div class="project-skeleton">
                <span class="skeleton-bar" style={{ width: '70%' }} />
                <span class="skeleton-bar" style={{ width: '55%' }} />
                <span class="skeleton-bar" style={{ width: '65%' }} />
              </div>
            </Show>
            <Show when={!loading() && !projects().length}>
              <div class="empty-state">暂无项目</div>
            </Show>
          </div>

          <div class="project-dropdown-divider" />

          <Show
            when={creating()}
            fallback={
              <button
                type="button"
                class="project-create-btn"
                onClick={(e) => { e.stopPropagation(); setCreating(true); }}
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
                value={newName()}
                onInput={(e) => setNewName(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') doCreate();
                  if (e.key === 'Escape') setCreating(false);
                }}
                ref={(el) => setTimeout(() => el.focus())}
              />
              <button
                type="button"
                class="project-create-action text-accent-emerald"
                title="确认创建"
                onClick={doCreate}
              >
                <FiCheck size={13} />
              </button>
              <button
                type="button"
                class="project-create-action text-text-dim"
                title="取消"
                onClick={() => setCreating(false)}
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
