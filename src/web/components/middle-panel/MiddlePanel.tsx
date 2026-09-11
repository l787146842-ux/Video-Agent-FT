import { Show } from 'solid-js';
import { useSplitter } from '@/hooks/use-splitter';
import { state } from '@/stores/studio';
import { Splitter } from '@/components/layout/Splitter';
import { MediaViewer } from './MediaViewer';
import { PromptEditor } from './PromptEditor';
import { ParamControls } from './ParamControls';
import { SubagentRail } from './SubagentRail';

/**
 * 中间面板（双视图，由顶栏「子任务」入口切换 middleView）：
 * - preview（默认，对齐旧版布局）：预览区（flex-1）→ 水平分割线（拖动只调 Prompt 区高度）
 *   → Prompt 区（定高）→ 参数控制栏（固定在底部不动）
 *   收缩时：提示词输入区与底部参数栏一起折叠，仅保留展开按钮条。
 * - subagents：「子任务」面板（列表 → 点卡片看只读执行记录）；
 *   点左栏任意处切回 preview。
 */
export default function MiddlePanel() {
  // Prompt 区高度：100-600px，向上拖变高（invert），旧版默认 280px
  const promptSplit = useSplitter(280, {
    axis: 'y',
    min: 100,
    max: 600,
    invert: true,
    disabled: () => state.isPromptCollapsed,
    storageKey: 'splitPrompt',
  });

  return (
    <div class="panel-column">
      <Show
        when={state.middleView === 'subagents'}
        fallback={
          <>
            <MediaViewer />
            {/* 收缩后分割线与参数栏随提示词区一起折叠 */}
            <Show when={!state.isPromptCollapsed}>
              <Splitter split={promptSplit} direction="horizontal" />
            </Show>
            {/* 旧版 preview-bottom：统一 bg-secondary 底色的 Prompt 区 + 固定底部参数栏 */}
            <div class="preview-bottom-shell">
              <div
                class="prompt-split-area"
                style={{
                  height: state.isPromptCollapsed ? 'auto' : `${promptSplit.size()}px`,
                }}
              >
                <PromptEditor />
              </div>
              {/* 参数控制栏：固定底部，不随 Prompt 高度变化；收缩时一并隐藏 */}
              <Show when={!state.isPromptCollapsed}>
                <ParamControls />
              </Show>
            </div>
          </>
        }
      >
        {/* 子任务视图：占据整个中间面板，自带滚动与留白 */}
        <div class="subagent-center">
          <SubagentRail />
        </div>
      </Show>
    </div>
  );
}
