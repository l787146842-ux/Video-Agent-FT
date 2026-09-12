/**
 * 供应商/模型选择工具（从旧 core/provider-utils.ts 迁移）
 * 仅依赖 studio store，供面板组件与批量生成使用。
 */
import { state } from '@/stores/studio';
import { putProviders } from '@/api/providers';
import { showToast } from '@/stores/toast';
import type { ApiProvider, ChatModelMeta } from '@/types';

export type ProviderKind = 'image' | 'video' | 'chat';

const MODEL_FIELD: Record<ProviderKind, 'image_models' | 'video_models' | 'chat_models'> = {
  image: 'image_models',
  video: 'video_models',
  chat: 'chat_models',
};

/** 拥有指定类型模型列表的启用供应商 */
export function apiProvidersFor(kind: ProviderKind): ApiProvider[] {
  const field = MODEL_FIELD[kind];
  return state.apiProviders.filter(
    (p) => Array.isArray(p[field]) && (p[field]?.length ?? 0) > 0,
  );
}

/** 指定供应商的模型列表 */
export function providerModels(providerId: string, kind: ProviderKind): string[] {
  const p = state.apiProviders.find((x) => x.id === providerId);
  if (!p) return [];
  return p[MODEL_FIELD[kind]] || [];
}

/** 首选供应商（对齐旧版偏好顺序） */
export function preferredProviderIdForKind(
  kind: ProviderKind,
  providers: ApiProvider[] = apiProvidersFor(kind),
): string {
  const preferences =
    kind === 'video'
      ? ['volcengine', 'jimeng', 'apimart']
      : ['custom-api', 'gemini-cli', 'custom-api-6'];
  for (const id of preferences) {
    if (providers.some((p) => p.id === id)) return id;
  }
  return providers[0]?.id || '';
}

/** 供应商首个可用模型 */
export function defaultModelFor(providerId: string, kind: ProviderKind): string {
  return providerModels(providerId, kind)[0] || '';
}

/** 模型编辑面板：读单模型配置（无配置返回 undefined = 走平台默认） */
export function chatModelMeta(
  providerId: string, model: string,
): ChatModelMeta | undefined {
  const p = state.apiProviders.find((x) => x.id === providerId);
  return p?.chat_models_meta?.find((m) => m.model === model);
}

/** 模型编辑面板：写单模型配置（更新 store + 全量 PUT 保存；后端透传未知字段）
 * 保存失败不再静默（2026-09-12 修复：1M 挡选了没生效却无任何提示） */
export async function saveChatModelMeta(
  providerId: string, model: string, patch: Partial<ChatModelMeta>,
): Promise<void> {
  const p = state.apiProviders.find((x) => x.id === providerId);
  if (!p) {
    showToast(`模型配置保存失败：找不到供应商 ${providerId}`, 'error');
    return;
  }
  const list = [...(p.chat_models_meta || [])];
  const idx = list.findIndex((m) => m.model === model);
  const merged: ChatModelMeta = { ...(idx >= 0 ? list[idx] : { model }), ...patch, model };
  if (idx >= 0) list[idx] = merged;
  else list.push(merged);
  p.chat_models_meta = list;
  try {
    await putProviders(state.apiProviders);
  } catch (err) {
    console.error('[providers] chat_models_meta 保存失败', err);
    showToast(`模型配置保存失败：${(err as Error).message}`, 'error');
  }
}
