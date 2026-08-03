import { onCleanup } from 'solid-js';
import { useSplitter } from '@/hooks/use-splitter';
import { Splitter } from './Splitter';
import LeftPanel from '@/components/left-panel/LeftPanel';
import MiddlePanel from '@/components/middle-panel/MiddlePanel';
import RightPanel from '@/components/right-panel/RightPanel';
import { persistBoard } from '@/stores/studio';

/**
 * Agent 模式三栏布局（路由 /）
 * 三栏宽度由 Splitter 拖拽控制。
 */
export default function AgentLayout() {
  // 左栏：240-600px（对齐旧约束）
  const leftSplit = useSplitter(320, { min: 240, max: 600, storageKey: 'splitLeft' });
  // 右栏：280-650px，向左拖拽变宽（invert）
  const rightSplit = useSplitter(360, { min: 280, max: 650, invert: true, storageKey: 'splitRight' });

  // 离开页面时立即冲刷防抖中的故事板保存，避免切路由丢编辑
  onCleanup(() => persistBoard.flush());

  return (
    <div class="agent-page">
      <div class="studio-container">
        <aside class="studio-col col-left" style={{ width: `${leftSplit.size()}px` }}>
          <LeftPanel />
        </aside>

        <Splitter split={leftSplit} />

        <section class="studio-col col-middle">
          <MiddlePanel />
        </section>

        <Splitter split={rightSplit} />

        <aside class="studio-col col-right" style={{ width: `${rightSplit.size()}px` }}>
          <RightPanel />
        </aside>
      </div>
    </div>
  );
}
