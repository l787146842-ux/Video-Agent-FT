/**
 * 全局设置 store：后端运行时设置（全局生成默认 + 开关）的前端缓存。
 * 顶栏入口 / 全局设置页 / 参数栏自动填充 共用；热更新即时生效。
 */
import { createSignal } from 'solid-js';
import { getRuntimeSettings, setRuntimeSettings, type RuntimeSettings } from '@/api/agent';
import { showToast } from '@/stores/toast';

const [globalSettings, setGlobalSettings] = createSignal<RuntimeSettings | null>(null);
let loadPromise: Promise<RuntimeSettings | null> | null = null;

export { globalSettings };

/** 幂等加载：已加载/加载中直接复用，失败静默返回 null（UI 降级） */
export function ensureGlobalSettings(): Promise<RuntimeSettings | null> {
  const cur = globalSettings();
  if (cur) return Promise.resolve(cur);
  if (!loadPromise) {
    loadPromise = getRuntimeSettings()
      .then((s) => { setGlobalSettings(s); return s; })
      .catch(() => null);
  }
  return loadPromise;
}

/** 热更新（乐观更新 + 失败回滚）；返回最新服务端值 */
export async function updateGlobalSettings(patch: Partial<RuntimeSettings>): Promise<void> {
  const prev = globalSettings();
  if (!prev) return;
  setGlobalSettings({ ...prev, ...patch });
  try {
    const next = await setRuntimeSettings(patch);
    setGlobalSettings(next);
  } catch (e) {
    setGlobalSettings(prev);
    showToast(`全局设置保存失败：${(e as Error).message}`, 'error');
  }
}
