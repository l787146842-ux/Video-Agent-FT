/**
 * 供应商/模型选择工具（从旧 core/provider-utils.ts 迁移）
 * 仅依赖 studio store，供面板组件与批量生成使用。
 */
import { state, setState } from '@/stores/studio';
import { putProviders } from '@/api/providers';
import { showToast } from '@/stores/toast';
import type { ApiProvider, AudioCapability, ChatModelMeta } from '@/types';

export type ProviderKind = 'image' | 'video' | 'chat' | 'audio';

const MODEL_FIELD: Record<ProviderKind, 'image_models' | 'video_models' | 'chat_models' | 'audio_models'> = {
  image: 'image_models',
  video: 'video_models',
  chat: 'chat_models',
  audio: 'audio_models',
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

/** 指定供应商在音频通道下可选的模型。
 *  能力清单由后端推导（audio_models_meta），前端只过滤不重算；
 *  旧响应无 meta 时回退全部音频模型（后端仍会校验通道/模型组合）。 */
export function audioModelsFor(providerId: string, channel: string): string[] {
  const p = state.apiProviders.find((x) => x.id === providerId);
  if (!p) return [];
  const meta = p.audio_models_meta || [];
  if (meta.length) {
    // 有 meta 就只认该通道的模型；通道下无可用模型时返回空（不拿别的通道凑数）
    return meta
      .filter((m) => (m.capabilities || []).includes(channel as AudioCapability))
      .map((m) => m.model);
  }
  return p.audio_models || [];
}

/** 指定音频通道下**真正可用**的供应商（已接适配器 + 该通道有模型）。
 *
 *  未接适配器的厂商一律不进下拉、不参与兜底选择：列出来只会让用户选中后
 *  在提交时收到「尚未接入音频适配器」（与 API 设置页一样，能配置≠能用）。 */
export function audioProvidersFor(channel: string): ApiProvider[] {
  return state.apiProviders.filter(
    (p) => p.enabled !== false && !!p.audio_adapter
      && audioModelsFor(p.id, channel).length > 0,
  );
}

/** 首选供应商（对齐旧版偏好顺序） */
export function preferredProviderIdForKind(
  kind: ProviderKind,
  providers: ApiProvider[] = apiProvidersFor(kind),
): string {
  const preferences =
    kind === 'video'
      ? ['volcengine', 'jimeng', 'apimart']
      : kind === 'audio' ? ['custom-api-8']
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
  // Solid store 禁止对 find() 元素直接赋值新属性——set trap 静默丢弃,
  // PUT 发出去的 body 始终没有 meta（9-08 上线起保存从未生效,实证见
  // providers-meta-save.test）。必须走 setState 函数式替换整条记录。
  setState('apiProviders', (prev) => prev.map(
    (x) => (x.id === providerId ? { ...x, chat_models_meta: list } : x),
  ));
  try {
    await putProviders(state.apiProviders);
  } catch (err) {
    console.error('[providers] chat_models_meta 保存失败', err);
    showToast(`模型配置保存失败：${(err as Error).message}`, 'error');
  }
}
