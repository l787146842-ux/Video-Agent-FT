import { createSignal, createMemo, createEffect, For } from 'solid-js';
import { FiClock } from 'solid-icons/fi';
import { getSnapshots, restoreSnapshot } from '@/api/project';
import { ApiError } from '@/api/client';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { applyProjectSnapshot } from '@/lib/project-apply';
import { disconnectAgentStream, resumeAgentTasks } from '@/hooks/use-sse';
import { showToast } from '@/stores/toast';
import { chatState } from '@/stores/chat';
import { state } from '@/stores/studio';
import type { SnapshotItem } from '@/types/api.generated';

interface SnapshotEntry { id: string; ts: string; label: string }

/** ISO 时间 → 本地短格式（月-日 时:分） */
function formatTs(ts: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/**
 * E1 故事板版本列表：快照指针清单（后端每轮结算打一版），
 * 每行「回退到此」= 二次确认 → 回档（生成中后端 409 拒收）→ 重载。
 */
export function SnapshotHistoryBar() {
  const [entries, setEntries] = createSignal<SnapshotEntry[]>([]);

  const refresh = async () => {
    try {
      const res = await getSnapshots();
      // 生成类型 ts/label 为可选：归一到本地必填形态（缺省空串）
      const items: SnapshotEntry[] = (res?.snapshots || []).map((s: SnapshotItem) => ({
        id: s.id,
        ts: s.ts ?? '',
        label: s.label ?? '',
      }));
      setEntries(items.reverse());
    } catch {
      /* 版本列表为辅助面：拉取失败静默，不打断主流程 */
    }
  };
  // 快照指针随 done 帧 live 落账到消息（snapshotId）：计数变化 or 项目切换即失效刷新
  // （替代旧的仅 onMount 一次性拉取——生成中新增的版本能实时进列表）
  const snapshotCount = createMemo(() => chatState.messages.filter((m) => m.snapshotId).length);
  createEffect(() => {
    snapshotCount();
    state.projectId;
    void refresh();
  });

  const doRestore = async (entry: SnapshotEntry) => {
    const ok = await confirmDialog({
      title: `回退到「${formatTs(entry.ts)} ${entry.label || '快照'}」？`,
      message: '之后的改动将被覆盖（可经撤销/重做复核）。',
      confirmText: '回退',
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await restoreSnapshot(entry.id);
      // 免刷新：断开旧订阅 → 整板重置 → 重订阅（回档同项目，projectId effect 不触发）
      disconnectAgentStream();
      applyProjectSnapshot(res.state);
      await resumeAgentTasks(state.projectId);
      showToast('已回退到所选版本', 'success');
    } catch (e) {
      showToast(e instanceof ApiError ? e.payload.message : '回退失败（生成中禁止回退）', 'warning');
    }
  };

  return (
    <details class="snapshot-history-bar">
      <summary>
        <FiClock size={13} />
        <span>版本历史</span>
      </summary>
      <div class="snapshot-history-list">
        <For each={entries()} fallback={<div class="snapshot-history-empty">暂无历史版本</div>}>
          {(entry) => (
            <div class="snapshot-history-row">
              <span class="snapshot-history-ts">{formatTs(entry.ts)}</span>
              <span class="snapshot-history-label">{entry.label || '快照'}</span>
              <button type="button" class="gate-override-btn" onClick={() => void doRestore(entry)}>
                回退到此
              </button>
            </div>
          )}
        </For>
      </div>
    </details>
  );
}
