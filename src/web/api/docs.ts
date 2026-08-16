/**
 * 文档 API（Skill 文档；项目文档复用 api/project.ts 的 saveProjectDocument）
 * 对齐后端 routes/plugins.py 契约
 */
import { apiFetch, apiPut, apiPost, apiDelete } from './client';
import type { SkillDocSave, SkillFormatRequest } from '@/types/api.generated';

export interface SkillDoc {
  slug: string;
  name: string;
  content?: string;
}

/** Skill 文档历史版本（后端保存前自动备份，保留最近 10 版） */
export interface SkillDocVersion {
  version: string;
  content: string;
}

/** Skill 文档历史版本列表（新→旧，含全文） */
export async function getSkillDocHistory(slug: string): Promise<SkillDocVersion[]> {
  const data = await apiFetch<{ versions?: SkillDocVersion[] }>(
    `/api/skills/docs/${encodeURIComponent(slug)}/history`,
  );
  return Array.isArray(data.versions) ? data.versions : [];
}

/** Skill 文档列表（含全文） */
export async function getSkillDocs(): Promise<SkillDoc[]> {
  const data = await apiFetch<{ docs?: SkillDoc[] }>('/api/skills/docs');
  return Array.isArray(data.docs) ? data.docs : [];
}

/** 保存 Skill 文档（新建或覆盖） */
export function saveSkillDoc(slug: string, content: string) {
  const body: SkillDocSave = { content };
  return apiPut<{ ok: boolean; doc: SkillDoc; lint?: { warnings?: string[] } }>(
    `/api/skills/docs/${encodeURIComponent(slug)}`,
    body,
  );
}

/** 用 LLM 将任意文本整理为标准 Skill markdown 格式 */
export function formatSkillContent(content: string): Promise<{ content: string }> {
  const body: SkillFormatRequest = { content };
  return apiPost<{ content: string }>('/api/skills/format', body);
}

/** 删除 Skill 文档 */
export function deleteSkillDoc(slug: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/skills/docs/${encodeURIComponent(slug)}`);
}
