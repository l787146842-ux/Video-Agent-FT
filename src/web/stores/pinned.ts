import { createSignal } from 'solid-js';
import { showToast } from '@/stores/toast';

/**
 * Artifact 钉住 store（F3 钉住侧栏）。
 *
 * 职责划分（三者不合并）：
 * - middle-panel MediaViewer = 生成工作区预览（跟随故事板选中草稿）；
 * - Lightbox（统一预览灯箱） = 临时全屏查看（Esc 即走）；
 * - 本 store 驱动的 PinnedRail = 跨轮对照钉住（多产物并置比对，会话内常驻）。
 *
 * 轻量约束：上限 PINNED_MAX=3；doc 只持文档名元数据，正文由
 * PinnedRail 渲染时从 studio state.documents 现读（文档更新钉住预览同步新）；
 * 图/视持 url 元数据，非激活项由 PinnedRail 卸载 src 防内存膨胀。
 */

/** 钉住上限（计划书 F3：1-3 个） */
export const PINNED_MAX = 3;

// ===== kind 判别联合 =====
export interface PinnedImage {
  kind: 'image';
  id: string;
  url: string;
  name: string;
}
export interface PinnedVideo {
  kind: 'video';
  id: string;
  url: string;
  name: string;
  /** 首帧缩略（poster，可选） */
  thumb?: string;
}
export interface PinnedDoc {
  kind: 'doc';
  id: string;
  /** 项目文档名（内容渲染时从 studio state.documents 解析） */
  name: string;
}
export type PinnedArtifact = PinnedImage | PinnedVideo | PinnedDoc;

/** 钉住入参（无 id，由 kind+主键派生稳定 id） */
export type PinSpec =
  | { kind: 'image'; url: string; name: string }
  | { kind: 'video'; url: string; name: string; thumb?: string }
  | { kind: 'doc'; name: string };

/** 稳定 id：kind + 主键（图/视=url，doc=文档名） */
export function pinnedIdOf(spec: PinSpec): string {
  return spec.kind === 'doc' ? `doc:${spec.name}` : `${spec.kind}:${spec.url}`;
}

const [pinned, setPinned] = createSignal<PinnedArtifact[]>([]);
/** 激活项 id：仅激活项挂载媒体 src（非激活项只渲染元数据行） */
const [activeId, setActiveId] = createSignal('');

/** 钉住：重复钉同项 → 仅激活；满额 → toast 提示并拒绝（不静默挤掉旧项） */
export function pinArtifact(spec: PinSpec): boolean {
  const id = pinnedIdOf(spec);
  if (pinned().some((p) => p.id === id)) {
    setActiveId(id);
    return true;
  }
  if (pinned().length >= PINNED_MAX) {
    showToast(`钉住对照栏已满（最多 ${PINNED_MAX} 个），请先取消钉住一项`, 'warning');
    return false;
  }
  const item: PinnedArtifact = spec.kind === 'doc'
    ? { kind: 'doc', id, name: spec.name }
    : spec.kind === 'video'
      ? { kind: 'video', id, url: spec.url, name: spec.name, thumb: spec.thumb }
      : { kind: 'image', id, url: spec.url, name: spec.name };
  setPinned((prev) => [...prev, item]);
  setActiveId(id);
  showToast('已钉住到对照栏', 'success');
  return true;
}

/** 取消钉住：移除的若是激活项，激活权移交给剩余最后一项 */
export function unpinArtifact(id: string): boolean {
  const target = pinned().find((p) => p.id === id);
  if (!target) return false;
  const rest = pinned().filter((p) => p.id !== id);
  setPinned(rest);
  if (activeId() === id) setActiveId(rest[rest.length - 1]?.id || '');
  return true;
}

/** 钉住/取消钉住开关（卡片入口统一走此 API） */
export function togglePinArtifact(spec: PinSpec): void {
  const id = pinnedIdOf(spec);
  if (pinned().some((p) => p.id === id)) unpinArtifact(id);
  else pinArtifact(spec);
}

/** 是否已钉住（卡片按钮态回显） */
export function isPinnedId(id: string): boolean {
  return pinned().some((p) => p.id === id);
}

/** 激活某项（PinnedRail 列表点击） */
export function setActivePinned(id: string): void {
  setActiveId(id);
}

/** 清空全部（对照栏头部一键） */
export function clearAllPinned(): void {
  setPinned([]);
  setActiveId('');
}

export { pinned, activeId };
