/** 计划清单面板（计划清单细案批 2）：plan_write 产出的只读进度视图。
 * 写通道唯一 = 模型工具调用（用户侧无编辑入口，与后端整板 PUT 不碰 plan 键
 * 的口径一致）；数据源 = studio state.plan（board-sync 键在场即同步）。 */
import { For, Show, createMemo } from 'solid-js';
import { state } from '@/stores/studio';
import type { PlanItem } from '@/types';

const STATUS_LABEL: Record<PlanItem['status'], string> = {
  pending: '待办',
  in_progress: '进行中',
  completed: '已完成',
};

/** 排序：进行中置顶 → 待办 → 已完成沉底（组内保持模型给的顺序） */
function groupOrder(items: PlanItem[]): PlanItem[] {
  const rank = (s: PlanItem['status']) =>
    s === 'in_progress' ? 0 : s === 'pending' ? 1 : 2;
  return [...items].sort((a, b) => rank(a.status) - rank(b.status));
}

export default function PlanView() {
  const items = createMemo(() => groupOrder(state.plan?.items ?? []));
  const done = createMemo(() => items().filter((i) => i.status === 'completed').length);
  const total = createMemo(() => items().length);
  const pct = createMemo(() =>
    total() ? Math.round((done() / total()) * 100) : 0);

  return (
    <div class="plan-view">
      <Show when={total() > 0} fallback={
        <div class="empty-state centered">
          Agent 还没有建计划清单。多步任务开工时它会把步骤列在这里，你可以随时看到进度。
        </div>
      }>
        {/* 进度条（dsh TodoPanel 同款：完成数/总数 + 百分比） */}
        <div class="plan-progress">
          <div class="plan-progress-bar">
            <div class="plan-progress-fill" style={{ width: `${pct()}%` }} />
          </div>
          <span class="plan-progress-text">{done()}/{total()}（{pct()}%）</span>
        </div>
        <div class="plan-list">
          <For each={items()}>
            {(item) => (
              <div class={`plan-item plan-item--${item.status}`}>
                <span class="plan-item-dot" aria-label={STATUS_LABEL[item.status]} />
                <span class="plan-item-content">{item.content}</span>
                <Show when={item.status === 'in_progress'}>
                  <span class="plan-item-tag">{STATUS_LABEL[item.status]}</span>
                </Show>
              </div>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
}
