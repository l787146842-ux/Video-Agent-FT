/**
 * 画布交互 API（对话栏图片拖入画布 + @ 菜单读取画布节点图片）
 */
import { apiPost, apiFetch } from './client';
import type {
  CanvasDropImageRequest, CanvasSelectNodesRequest, DropPoint, ViewSize,
  CanvasDropImageResponse, CanvasNodeImageItem,
  CanvasNodeImagesResponse, AllCanvasImageItem,
  AllCanvasImagesResponse, CanvasListItem,
  CanvasListResponse, CanvasSelectNodesResponse,
} from '@/types/api.generated';

/** 生成物 drop/view 为 unknown 粗型，精化为坐标/尺寸强类型（豁免清单登记） */
export type CanvasDropImagePayload = CanvasDropImageRequest & {
  drop?: DropPoint;
  view?: ViewSize;
};

/** 以下响应类型以后端生成物为唯一来源（契约 phase1，手抄定义已删） */
export type CanvasDropImageResult = CanvasDropImageResponse;
export type CanvasNodeImagesResult = CanvasNodeImagesResponse;
/* 同名条目型直接 re-export 生成物 */
export type { CanvasNodeImageItem, AllCanvasImageItem, CanvasListItem };

/** 把一张图片写入指定画布（或当前活跃画布），根据画布类型创建对应节点 */
export function dropImageToCanvas(payload: CanvasDropImagePayload): Promise<CanvasDropImageResult> {
  return apiPost<CanvasDropImageResult>('/api/canvas/drop-image', payload);
}

/** 获取当前活跃画布中所有节点内的图片（@ 菜单用，只读） */
export function fetchCanvasNodeImages(): Promise<CanvasNodeImagesResult> {
  return apiFetch<CanvasNodeImagesResult>('/api/canvas/node-images');
}

/** 所有画布节点图片（含画布归属信息）：生成物别名 */
export type AllCanvasImagesResult = AllCanvasImagesResponse;

/** 获取指定画布（或当前活跃画布）中节点内的图片（预览框右键导入用） */
export function fetchAllCanvasNodeImages(canvasId?: string): Promise<AllCanvasImagesResult> {
  const q = canvasId ? `?canvas_id=${encodeURIComponent(canvasId)}` : '';
  return apiFetch<AllCanvasImagesResult>(`/api/canvas/all-node-images${q}`);
}

/** 画布列表：生成物别名 */
export type CanvasListResult = CanvasListResponse;

/** 获取所有未删除画布列表（供手动画布选择器使用） */
export function fetchCanvasList(): Promise<CanvasListResult> {
  return apiFetch<CanvasListResult>('/api/canvas/list');
}

/** 画布选中节点（对端 compactNode 形状）：后端 /canvas/selection 未建模
 *（节点 metadata 为外部画布动态数据，严格建模需 Dict[str, Any] 粗型），
 * 保留手写镜像，豁免清单见 types/index.ts 头注 */
export interface CanvasSelectionNode {
  id: string;
  type?: string;
  title?: string;
  metadata?: Record<string, unknown>;
}

export interface CanvasSelectionResult {
  supported: boolean;
  nodes: CanvasSelectionNode[];
  canvas_online: boolean;
}

/** 读取当前画布选中节点（轮询订阅） */
export function fetchCanvasSelection(): Promise<CanvasSelectionResult> {
  return apiFetch<CanvasSelectionResult>('/api/canvas/selection');
}

/** 反向联动响应：生成物别名（原手抄 reason? 字段无消费方，随替换删除） */
export type CanvasSelectNodesResult = CanvasSelectNodesResponse;

/** 反向联动：把指定节点设为画布当前选中 */
export function selectCanvasNodes(nodeIds: string[]): Promise<CanvasSelectNodesResult> {
  const body: CanvasSelectNodesRequest = { node_ids: nodeIds };
  return apiPost<CanvasSelectNodesResult>('/api/canvas/select-nodes', body);
}
