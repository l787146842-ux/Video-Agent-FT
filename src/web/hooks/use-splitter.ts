import { createSignal, onCleanup } from 'solid-js';

export interface SplitterOptions {
  /** 拖拽轴向：x=左右拖拽调宽度，y=上下拖拽调高度 */
  axis?: 'x' | 'y';
  min?: number;
  max?: number;
  /** true 时拖拽方向取反（右侧面板向左拖变宽 / 底部面板向上拖变高） */
  invert?: boolean;
  /** 返回 true 时禁用拖拽（如 prompt 折叠态禁用水平分割） */
  disabled?: () => boolean;
  /** localStorage 持久化 key，传入后拖拽结束会自动保存，刷新/切路由后恢复 */
  storageKey?: string;
}

/**
 * 拖拽分割线 Hook
 * 返回尺寸信号 + mousedown 处理器，配合 <Splitter /> 组件使用。
 * 支持通过 storageKey 将尺寸持久化到 localStorage。
 */
export function useSplitter(initialSize: number, options: SplitterOptions = {}) {
  const { axis = 'x', min = 200, max = 600, invert = false, disabled, storageKey } = options;

  // 从 localStorage 恢复（ clamp 到合法范围）
  const restored = storageKey ? Number(localStorage.getItem(storageKey)) : NaN;
  const init = Number.isFinite(restored) ? Math.min(max, Math.max(min, restored)) : initialSize;

  const [size, setSize] = createSignal(init);
  const [dragging, setDragging] = createSignal(false);

  let startPos = 0;
  let startSize = 0;
  let prevUserSelect = '';

  function persist() {
    if (storageKey) localStorage.setItem(storageKey, String(size()));
  }

  function onMouseDown(e: MouseEvent) {
    if (disabled?.()) return;
    e.preventDefault();
    startPos = axis === 'x' ? e.clientX : e.clientY;
    startSize = size();
    setDragging(true);
    // 拖拽期间禁止文本选择
    prevUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  function onMouseMove(e: MouseEvent) {
    const pos = axis === 'x' ? e.clientX : e.clientY;
    let delta = pos - startPos;
    if (invert) delta = -delta;
    setSize(Math.min(max, Math.max(min, startSize + delta)));
  }

  function onMouseUp() {
    setDragging(false);
    document.body.style.userSelect = prevUserSelect;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    persist();
  }

  onCleanup(() => {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    if (dragging()) {
      document.body.style.userSelect = prevUserSelect;
      persist();
    }
  });

  return { size, setSize, dragging, onMouseDown };
}
