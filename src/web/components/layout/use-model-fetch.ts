/**
 * 拉取模型域状态与动作 hook——七轮 S1/T23 自 SettingsView 切出。
 * 承载 fetched/savedCats 状态与「拉取/应用」动作；弹窗 UI 在 settings/FetchModelsModal。
 */
import { createSignal } from 'solid-js';
import { apiPost } from '@/api/client';
import type { ProviderProbeRequest } from '@/types/api.generated';
import { showToast } from '@/stores/toast';
import type { EditableProvider, FetchedModels } from './settings-meta';
import type { ModelPicked } from './settings/FetchModelsModal';

export function useModelFetch(
  current: () => EditableProvider | undefined,
  keyInput: () => string,
  patch: (field: string, value: unknown) => void,
) {
  const [fetched, setFetched] = createSignal<FetchedModels | null>(null);
  // 已配置模型分类集合（画布同款：类别以已配置优先，默认勾选=已在配置里）
  const [savedCats, setSavedCats] = createSignal<{ image: Set<string>; chat: Set<string>; video: Set<string> }>(
    { image: new Set(), chat: new Set(), video: new Set() },
  );

  async function fetchModels() {
    const p = current();
    if (!p) return;
    try {
      const body: ProviderProbeRequest = {
        base_url: p.base_url, api_key: keyInput() || '', provider_id: p.id, protocol: p.protocol,
      };
      const data = await apiPost<FetchedModels & { error?: string }>(
        '/api/providers/fetch-models',
        body,
      );
      if (data.error || !(data.all || []).length) {
        showToast(`拉取模型失败：${data.error || '上游未返回模型'}`, 'error');
        return;
      }
      // 画布同款：清单 = 上游 ∪ 已配置（字典序），默认勾选 = 已在配置里的
      const saved = {
        image: new Set((p.image_models || []).map((s) => s.trim()).filter(Boolean)),
        chat: new Set((p.chat_models || []).map((s) => s.trim()).filter(Boolean)),
        video: new Set((p.video_models || []).map((s) => s.trim()).filter(Boolean)),
      };
      setSavedCats(saved);
      const all = Array.from(new Set([
        ...(data.all || []), ...saved.image, ...saved.chat, ...saved.video,
      ])).sort();
      setFetched({ ...data, all, total: all.length });
    } catch (e) {
      showToast(`拉取模型失败：${(e as Error).message}`, 'error');
    }
  }

  /** 弹窗「应用到模型列表」：勾选结果写回当前平台并关闭 */
  function applyFetched(picked: ModelPicked) {
    patch('image_models', picked.image);
    patch('chat_models', picked.chat);
    patch('video_models', picked.video);
    setFetched(null);
    showToast(`已应用到模型列表（生图 ${picked.image.length} / LLM ${picked.chat.length} / 视频 ${picked.video.length}）`, 'success');
  }

  return { fetched, savedCats, fetchModels, applyFetched, closeFetched: () => setFetched(null) };
}
