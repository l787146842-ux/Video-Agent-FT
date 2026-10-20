/**
 * 文档 API（Skill 文档；项目文档复用 api/project.ts 的 saveProjectDocument）
 * 对齐后端 routes/plugins.py 契约
 */
import { apiFetch, apiPut, apiPost, apiDelete } from './client';
import type {
  SkillDoc, SkillDocHistoryResponse, SkillDocsResponse, SkillDocSave, SkillDocVersion,
  SkillFormatRequest, SkillAssistantRequest, ActiveSkillRequest,
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

/** 项目态 Skill 显式绑定：slug 空 = **清除显式偏好**（不是「关闭技能」——
 * 2026-10-16 用户裁决：文档区 Skill 是唯一权威，空值由前端 agentSkillId /
 * 后端 fallback_skill_from_state 回落 usedSkills 继续生效）。
 * 界面已无任何入口写空值；本形参保留仅为向后兼容存量调用方。 */
export function setActiveSkillApi(
  slug: string, source: 'user' | 'suggested' = 'user',
): Promise<{ ok: boolean; active_skill?: { slug: string; source: string } | null }> {
  const body: ActiveSkillRequest = { slug, source };
  return apiPost('/api/skills/active', body);
}

/** Skill 草稿自检结果（创作模式后端机械校验；issues 为空 = 通过） */
export interface SkillAssistantChecks {
  passed: boolean;
  issues: string[];
}

/** Skill 优化/创作助手（非流式）：返回 reply + 解析出的更新后全文
 * （content 为 null 时前端只展示回复、不覆盖预览；checks 为自检结果）。
 * mode=create：新建 Skill 的创作模式（六章节契约 + 一键自检/自修复）。 */
export function assistantSkillChat(body: {
  content: string;
  messages: { role: string; content: string }[];
  provider?: string;
  model?: string;
  mode?: 'create' | 'optimize';
}): Promise<{
  reply: string;
  content: string | null;
  checks?: SkillAssistantChecks | null;
}> {
  return apiPost<{
    reply: string;
    content: string | null;
    checks?: SkillAssistantChecks | null;
  }>('/api/skills/assistant', body as SkillAssistantRequest);
}
