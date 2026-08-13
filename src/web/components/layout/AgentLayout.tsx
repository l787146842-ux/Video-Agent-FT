import { createSignal, onCleanup, onMount, Show } from 'solid-js';
import { FiChevronRight } from 'solid-icons/fi';
import { useSplitter } from '@/hooks/use-splitter';
import { Splitter } from './Splitter';
import LeftPanel from '@/components/left-panel/LeftPanel';
import MiddlePanel from '@/components/middle-panel/MiddlePanel';
import RightPanel from '@/components/right-panel/RightPanel';
import { persistBoard } from '@/stores/studio';

/**
 * Agent 模式三栏布局（路由 /）
 * 三栏宽度由 Splitter 拖拽控制。
 *
 * 响应式断点（3.3c）：≤1100px 默认收起左栏、≤860px 再收起中间预览栏，
 * 窄窗口下保证聊天栏可用；收起后以窄条按钮手动展开。
 * 仅在窗口变窄时自动收起，变宽不自动展开（尊重用户手动展开意图）。
 */
export default function AgentLayout() {
  // 左栏：240-600px（对齐旧约束）
  const leftSplit = useSplitter(320, { min: 240, max: 600, storageKey: 'splitLeft' });
  // 右栏：280-650px，向左拖拽变宽（invert）
  const rightSplit = useSplitter(360, { min: 280, max: 650, invert: true, storageKey: 'splitRight' });

  const [leftCollapsed, setLeftCollapsed] = createSignal(false);
  const [middleCollapsed, setMiddleCollapsed] = createSignal(false);

  onMount(() => {
    const mqLeft = window.matchMedia('(max-width: 1100px)');
    const mqMid = window.matchMedia('(max-width: 860px)');
    setLeftCollapsed(mqLeft.matches);
    setMiddleCollapsed(mqMid.matches);
    const onLeft = (e: MediaQueryListEvent) => { if (e.matches) setLeftCollapsed(true); };
    const onMid = (e: MediaQueryListEvent) => { if (e.matches) setMiddleCollapsed(true); };
    mqLeft.addEventListener('change', onLeft);
    mqMid.addEventListener('change', onMid);
    onCleanup(() => {
      mqLeft.removeEventListener('change', onLeft);
      mqMid.removeEventListener('change', onMid);
    });
  });

  // 离开页面时立即冲刷防抖中的故事板保存，避免切路由丢编辑
  onCleanup(() => persistBoard.flush());

  return (
    <div class="agent-page">
      <div class="studio-container">
        <Show when={leftCollapsed()}>
          <button
            type="button"
            class="panel-reopen-col"
            title="展开故事板"
            onClick={() => setLeftCollapsed(false)}
          >
            <FiChevronRight size={14} />
          </button>
        </Show>
        <Show when={!leftCollapsed()}>
          <aside class="studio-col col-left" style={{ width: `${leftSplit.size()}px` }}>
            <LeftPanel />
          </aside>
          <Splitter split={leftSplit} />
        </Show>

        <Show when={middleCollapsed()}>
          <button
            type="button"
            class="panel-reopen-col"
            title="展开预览"
            onClick={() => setMiddleCollapsed(false)}
          >
            <FiChevronRight size={14} />
          </button>
        </Show>
        <Show when={!middleCollapsed()}>
          <section class="studio-col col-middle">
            <MiddlePanel />
          </section>
          <Splitter split={rightSplit} />
        </Show>

        <aside class="studio-col col-right" style={{ width: `${rightSplit.size()}px` }}>
          <RightPanel />
        </aside>
      </div>
    </div>
  );
}
