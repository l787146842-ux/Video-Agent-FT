/**
 * 画布交互 API（对话栏图片拖入画布 + @ 菜单读取画布节点图片）
 */
import { apiPost, apiFetch } from './client';
import type { CanvasDropImageRequest, DropPoint, ViewSize } from '@/types/api.generated';

/** 生成物 drop/view 为 unknown 粗型，精化为坐标/尺寸强类型（豁免清单登记） */
export type CanvasDropImagePayload = CanvasDropImageRequest & {
  drop?: DropPoint;
  view?: ViewSize;
};

export interface CanvasDropImageResult {
  node_id: string;
  canvas_id: string;
  canvas_title: string;
  image_url: string;
}

export interface CanvasNodeImageItem {
  id: string;
  name: string;
  url: string;
  thumb: string;
  category: string;
}

export interface CanvasNodeImagesResult {
  items: CanvasNodeImageItem[];
  canvas_online: boolean;
  canvas_title?: string;
}

/** 把一张图片写入指定画布（或当前活跃画布），根据画布类型创建对应节点 */
export function dropImageToCanvas(payload: CanvasDropImagePayload): Promise<CanvasDropImageResult> {
  return apiPost<CanvasDropImageResult>('/api/canvas/drop-image', payload);
}

/** 获取当前活跃画布中所有节点内的图片（@ 菜单用，只读） */
export function fetchCanvasNodeImages(): Promise<CanvasNodeImagesResult> {
  return apiFetch<CanvasNodeImagesResult>('/api/canvas/node-images');
}

/** 所有画布节点图片项（含画布归属信息） */
export interface AllCanvasImageItem {
  id: string;
  name: string;
  url: string;
  thumb: string;
  canvas_title: string;
  canvas_kind: string;
}

export interface AllCanvasImagesResult {
  items: AllCanvasImageItem[];
  canvas_online: boolean;
  canvas_title?: string;
  canvas_kind?: string;
}

/** 获取指定画布（或当前活跃画布）中节点内的图片（预览框右键导入用） */
export function fetchAllCanvasNodeImages(canvasId?: string): Promise<AllCanvasImagesResult> {
  const q = canvasId ? `?canvas_id=${encodeURIComponent(canvasId)}` : '';
  return apiFetch<AllCanvasImagesResult>(`/api/canvas/all-node-images${q}`);
}

/** 画布列表项 */
export interface CanvasListItem {
  id: string;
  title: string;
  kind: string;
  updated_at: number;
}

export interface CanvasListResult {
  canvases: CanvasListItem[];
  canvas_online: boolean;
}

/** 获取所有未删除画布列表（供手动画布选择器使用） */
export function fetchCanvasList(): Promise<CanvasListResult> {
  return apiFetch<CanvasListResult>('/api/canvas/list');
}
