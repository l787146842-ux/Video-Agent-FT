/**
 * 项目管理 API
 * 严格对齐后端 routes/project.py 契约
 */
import { apiFetch, apiPost, apiPut } from './client';
import type { ServerStateSnapshot, DocRecord } from '@/types';
import type {
  BoardMergeResponse, DeleteProjectRequest, DocumentDelete, DocumentSave, NewProjectRequest, OkResponse, ProjectListResponse, SnapshotActionRequest, SnapshotListResponse, SwitchProjectRequest, UndoStatusResponse,
} from '@/types/api.generated';

export interface OkWithStateResponse {
  ok: boolean;
  state?: ServerStateSnapshot | null;
  project_id?: string;
  message?: string;
}

export function getProjects() {
  return apiFetch<ProjectListResponse>('/api/project/list');
}

/** 当前项目完整状态快照（前端初始化加载） */
export function getProjectState() {
  return apiFetch<ServerStateSnapshot>('/api/project/state');
}

export function createProject(name: string) {
  const body: NewProjectRequest = { name };
  return apiPost<OkWithStateResponse>('/api/project/new', body);
}

export function switchProject(projectId: string) {
  const body: SwitchProjectRequest = { project_id: projectId };
  return apiPost<OkWithStateResponse>('/api/project/switch', body);
}

export function deleteProject(projectId: string) {
  const body: DeleteProjectRequest = { project_id: projectId };
  return apiPost<OkWithStateResponse>('/api/project/delete', body);
}

/** 文档面板编辑保存（upsert 到 state.documents） */
export function saveProjectDocument(name: string, content: string) {
  const body: DocumentSave = { name, content };
  return apiPut<{ ok: boolean; documents: DocRecord[] }>(
    '/api/project/document',
    body,
  );
}

export function deleteProjectDocument(name: string) {
  const body: DocumentDelete = { name };
  return apiPost<{ ok: boolean; documents: DocRecord[] }>(
    '/api/project/document/delete',
    body,
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
  return apiPut<OkResponse>('/api/project/state', patch);
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

// ---------- G1 并行局部修改（三向合并 + 冲突面板） ----------

/** 陈旧整板提交改走三向合并：单方改动自动采纳，双方同改回冲突清单交面板定夺 */
export function mergeProjectState(
  patch: Partial<
    Pick<
      ServerStateSnapshot,
      'project_id' | 'keyElements' | 'shots' | 'audioItems' | 'assets'
    >
  > & { base_version?: number },
) {
  return apiPost<BoardMergeResponse>('/api/project/state/merge', patch);
}

// ---------- E1 回档三件套（消息级快照指针化 + 版本列表 + 分叉） ----------

/** 故事板版本列表（快照指针清单） */
export function getSnapshots() {
  return apiFetch<SnapshotListResponse>('/api/project/snapshots');
}

/** 回档到快照时刻（生成中 409 拒收；回档本身可 redo） */
export function restoreSnapshot(snapshotId: string) {
  const body: SnapshotActionRequest = { snapshot_id: snapshotId };
  return apiPost<OkWithStateResponse>('/api/project/restore', body);
}

/** 从快照时刻新开项目（分叉；原项目不动） */
export function forkSnapshot(snapshotId: string, name = '') {
  const body: SnapshotActionRequest = { snapshot_id: snapshotId, name };
  return apiPost<OkWithStateResponse & { projects?: ProjectListResponse }>('/api/project/fork', body);
}
