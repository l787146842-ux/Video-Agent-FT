/**
 * 供应商/模型配置 API
 * 严格对齐后端 routes/providers.py + routes/config.py 契约
 */
import { apiFetch } from './client';
import type { ApiProvider } from '@/types';

export interface ProvidersResponse {
  providers: ApiProvider[];
  canvas_online: boolean;
}

export interface AppConfig {
  chat_models: string[];
  image_models: string[];
  video_models: string[];
  canvas_url: string;
}

/** 全部供应商配置（脱敏）+ 画布在线状态 */
export function getProviders() {
  return apiFetch<ProvidersResponse>('/api/providers');
}

/** 全局配置：默认模型列表 + 画布 URL（loadCanvasApiConfig 数据源） */
export function getAppConfig() {
  return apiFetch<AppConfig>('/api/config');
}

/** 统一素材选择器代理端点（对齐旧版 asset-modal 的 3 个 tab） */
export interface AssetPickerItem {
  id: string;
  name: string;
  url: string;
  thumb?: string;
  category?: string;
  size?: number;
  mtime?: string;
  source?: string;
}
export interface AssetPickerResponse {
  items: AssetPickerItem[];
  canvas_online: boolean;
  error?: string;
}
export function fetchAssetPicker(type: 'image' | 'canvas' | 'local') {
  return apiFetch<AssetPickerResponse>(`/api/asset-picker?type=${type}`);
}
