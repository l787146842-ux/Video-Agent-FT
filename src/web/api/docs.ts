/**
 * 文档 API（Skill 文档；项目文档复用 api/project.ts 的 saveProjectDocument）
 * 对齐后端 routes/plugins.py 契约
 */
import { apiFetch, apiPut, apiPost, apiDelete } from './client';
import type {
  SkillDoc, SkillDocHistoryResponse, SkillDocsResponse, SkillDocSave, SkillDocVersion,
  SkillFormatRequest, SkillAssistantRequest, ActiveSkillRequest, ActiveStyleLayersRequest,
} from '@/types/api.generated';

/** Skill 文档/历史版本：以后端生成物为唯一来源（豁免清单已清偿） */
export type { SkillDoc, SkillDocVersion };

/** Skill 文档历史版本列表（新→旧，含全文） */
export async function getSkillDocHistory(slug: string): Promise<SkillDocVersion[]> {
  const data = await apiFetch<SkillDocHistoryResponse>(
    `/api/skills/docs/${encodeURIComponent(slug)}/history`,
  );
  return Array.isArray(data.versions) ? data.versions : [];
}

/** Skill 文档列表（含全文） */
export async function getSkillDocs(): Promise<SkillDoc[]> {
  const data = await apiFetch<SkillDocsResponse>('/api/skills/docs');
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

/** 项目态 Skill 激活/摘除（批 C）：slug 空 = 摘除回到自由对话；
 * 激活事实写项目态（随快照下发），全局 KEY_SKILL 仅作建议值 */
export function setActiveSkillApi(
  slug: string, source: 'user' | 'suggested' = 'user',
): Promise<{ ok: boolean; active_skill?: { slug: string; source: string } | null }> {
  const body: ActiveSkillRequest = { slug, source };
  return apiPost('/api/skills/active', body);
}

/** 风格层组合激活（任务 #11：1 pipeline 可选 + N style 层）：
 * slugs = 全量替换式清单（传当前勾选全集；空清单 = 摘除全部风格层）。
 * 后端校验仅放行 kind=style 的 Skill，非风格型报 400（前端 toast 回显） */
export function setActiveStyleLayersApi(
  body: ActiveStyleLayersRequest,
): Promise<{ ok: boolean; style_skills: string[] }> {
  return apiPost('/api/skills/active-styles', body);
}

/** Skill 优化助手（非流式）：返回 reply + 解析出的更新后全文
 * （content 为 null 时前端只展示回复、不覆盖预览） */
export function assistantSkillChat(body: {
  content: string;
  messages: { role: string; content: string }[];
  provider?: string;
  model?: string;
}): Promise<{ reply: string; content: string | null }> {
  return apiPost<{ reply: string; content: string | null }>(
    '/api/skills/assistant', body as SkillAssistantRequest,
  );
}
