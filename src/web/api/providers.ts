/**
 * 供应商/模型配置 API
 * 严格对齐后端 routes/providers.py + routes/config.py 契约
 */
import { apiFetch } from './client';
import type { ApiProvider } from '@/types';
import type {
  InfiniteCanvasEmbedConfig, AppConfigResponse,
  AssetPickerItemModel, AssetPickerResponseModel,
} from '@/types/api.generated';

export interface ProvidersResponse {
  providers: ApiProvider[];
  canvas_online: boolean;
}

/** 画布嵌入引导参数（画布站点 / canvas-agent / token）：生成物 re-export（契约 phase1） */
export type { InfiniteCanvasEmbedConfig };

/** 全局配置读形态：以后端 AppConfigResponse 生成物为唯一来源（契约 phase1） */
export type AppConfig = AppConfigResponse;

/** 全部供应商配置（脱敏）+ 画布在线状态 */
export function getProviders() {
  return apiFetch<ProvidersResponse>('/api/providers');
}

/** 全局配置：默认模型列表 + 画布 URL（loadCanvasApiConfig 数据源） */
export function getAppConfig() {
  return apiFetch<AppConfig>('/api/config');
}

/** 统一素材选择器（对齐旧版 asset-modal 的 3 个 tab）：生成物别名（契约 phase1；
 * 原手抄 error? 字段后端从不返回，随替换删除，消费处同步改固定文案） */
export type AssetPickerItem = AssetPickerItemModel;
export type AssetPickerResponse = AssetPickerResponseModel;

/** 素材网格卡片消费的最小视图态（id/name/url/thumb）：
 * AssetPickerItemModel 与画布 tab 的 AllCanvasImageItem 的公共子集，
 * 网格/选中/onPick 仅依赖这些字段（视图态收窄，非 API 边界类型） */
export interface AssetGridItem {
  id: string;
  name: string;
  url: string;
  thumb?: string;
}
export function fetchAssetPicker(type: 'image' | 'canvas' | 'local') {
  return apiFetch<AssetPickerResponse>(`/api/asset-picker?type=${type}`);
}
