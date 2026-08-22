/** 预览区空态：图标 + 主提示 + 操作提示 */
export function PreviewEmpty(props: { hint?: string }) {
  return (
    <div class="preview-empty">
      <p class="preview-empty-icon">🎬</p>
      <p>{props.hint || '暂无媒体预览'}</p>
      <p class="preview-empty-hint">双击或拖拽上传，右键可替换媒体</p>
    </div>
  );
}
