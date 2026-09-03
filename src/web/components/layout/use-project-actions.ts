/**
 * 项目切换/新建/删除动作 hook——自 ProjectSwitcher 切出。
 * 承载列表/选中/新建表单状态、统一前置动作（停流 + 冲刷保存）与快照应用；
 * 下拉开合状态留在组件内，经 close 注入。
 */
import { createSignal } from 'solid-js';
import {
  getProjects, switchProject, deleteProject, createProject,
} from '@/api/project';
import { persistBoard } from '@/stores/studio';
import { stopAgentStream } from '@/hooks/use-sse';
import { showToast } from '@/stores/toast';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { applyProjectSnapshot } from '@/lib/project-apply';
import type { Project } from '@/types';

export function useProjectActions(close: () => void) {
  const [projects, setProjects] = createSignal<Project[]>([]);
  const [activeId, setActiveId] = createSignal('');
  const [creating, setCreating] = createSignal(false);
  const [newName, setNewName] = createSignal('');
  const [loading, setLoading] = createSignal(false);

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
      close();
      return;
    }
    try {
      await beforeProjectMutation();
      const data = await switchProject(id);
      if (!data.ok) throw new Error(data.message || '切换失败');
      applyProjectSnapshot(data.state);
      close();
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
      applyProjectSnapshot(data.state);
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
      applyProjectSnapshot(data.state);
      setCreating(false);
      setNewName('');
      close();
      showToast(`已创建新项目：${name}`, 'success');
    } catch (e) {
      showToast(`新建项目失败：${(e as Error).message}`, 'error');
    }
  }

  return {
    projects, activeId, creating, setCreating, newName, setNewName,
    loading, load, doSwitch, doDelete, doCreate,
  };
}
