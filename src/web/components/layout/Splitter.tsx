import type { useSplitter } from '@/hooks/use-splitter';

/**
 * 可复用拖拽分割线（对齐旧版 .splitter-v / .splitter-h）
 * vertical   → 竖直分割线（左右拖拽调列宽），负边距覆盖不占位
 * horizontal → 水平分割线（上下拖拽调行高），默认显示边框色细线
 */
export function Splitter(props: {
  split: ReturnType<typeof useSplitter>;
  direction?: 'vertical' | 'horizontal';
}) {
  const vertical = () => props.direction !== 'horizontal';
  return (
    <div
      role="separator"
      aria-orientation={vertical() ? 'vertical' : 'horizontal'}
      class={`${vertical() ? 'splitter-v' : 'splitter-h'} shrink-0 ${
        props.split.dragging() ? 'dragging' : ''
      }`}
      onMouseDown={(e) => props.split.onMouseDown(e)}
    />
  );
}
