/**
 * 供应商/模型选择工具（从旧 core/provider-utils.ts 迁移）
 * 仅依赖 studio store，供面板组件与批量生成使用。
 */
import { state } from '@/stores/studio';
import type { ApiProvider } from '@/types';

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
