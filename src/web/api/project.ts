/**
 * 项目管理 API
 * 严格对齐后端 routes/project.py 契约
 */
import { apiFetch, apiPost, apiPut } from './client';
import type { Project, ServerStateSnapshot, DocRecord } from '@/types';

export interface ProjectListResponse {
  projects: Project[];
  active_project_id: string;
}

export interface OkWithStateResponse {
  ok: boolean;
  state?: ServerStateSnapshot | null;
  project_id?: string;
  message?: string;
}

export interface UndoStatusResponse {
  can_undo: boolean;
  can_redo: boolean;
}

export function getProjects() {
  return apiFetch<ProjectListResponse>('/api/project/list');
}

/** 当前项目完整状态快照（前端初始化加载） */
export function getProjectState() {
  return apiFetch<ServerStateSnapshot>('/api/project/state');
}

export function createProject(name: string) {
  return apiPost<OkWithStateResponse>('/api/project/new', { name });
}

export function switchProject(projectId: string) {
  return apiPost<OkWithStateResponse>('/api/project/switch', { project_id: projectId });
}

export function deleteProject(projectId: string) {
  return apiPost<OkWithStateResponse>('/api/project/delete', { project_id: projectId });
}

/** 文档面板编辑保存（upsert 到 state.documents） */
export function saveProjectDocument(name: string, content: string) {
  return apiPut<{ ok: boolean; documents: DocRecord[] }>(
    '/api/project/document',
    { name, content },
  );
}

export function deleteProjectDocument(name: string) {
  return apiPost<{ ok: boolean; documents: DocRecord[] }>(
    '/api/project/document/delete',
    { name },
  );
}

/** 前端局部字段整体保存（project_id 供后端校验：与活跃项目不一致时返回 409，调用方丢弃该过期写入） */
export function putProjectState(
  patch: Partial<
    Pick<
      ServerStateSnapshot,
      'project_id' | 'keyElements' | 'shots' | 'audioItems' | 'assets' | 'chatMessages'
    >
  >,
) {
  return apiPut<{ ok: boolean }>('/api/project/state', patch);
}

export function undoAction() {
  return apiPost<OkWithStateResponse>('/api/project/undo', {});
}

export function redoAction() {
  return apiPost<OkWithStateResponse>('/api/project/redo', {});
}

export function getUndoStatus() {
  return apiFetch<UndoStatusResponse>('/api/project/undo-status');
}

/** 破坏性操作前压入撤销快照（保证删除草稿等"整体 PUT"路径可一次 undo 恢复） */
export function checkpointUndo() {
  return apiPost<{ ok: boolean } & UndoStatusResponse>('/api/project/undo-checkpoint', {});
}
