/**
 * 故事板 API
 * 说明：故事板内容编辑统一走「本地 store + putProjectState 防抖整体保存」路径
 * （见 stores/studio.ts），此处仅保留拖拽排序的细粒度端点。
 */
/** 分组排序持久化（拖拽排序后调用；静默失败不阻塞 UI） */
export function reorderGroups(category: string, groupIds: string[]): void {
  fetch('/api/storyboard/reorder', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, group_ids: groupIds }),
  }).catch(() => {
    /* 排序已本地生效，后端同步失败忽略 */
  });
}
