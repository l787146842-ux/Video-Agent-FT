import { createSignal, For, onMount } from 'solid-js';
import { FiClock } from 'solid-icons/fi';
import { getSnapshots, restoreSnapshot } from '@/api/project';
import { showToast } from '@/stores/toast';
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
  onMount(() => void refresh());

  const doRestore = async (entry: SnapshotEntry) => {
    if (!window.confirm(`回退到「${formatTs(entry.ts)} ${entry.label || '快照'}」？之后的改动将被覆盖（可经撤销/重做复核）。`)) return;
    try {
      await restoreSnapshot(entry.id);
      showToast('已回退到所选版本', 'success');
      location.reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : '回退失败（生成中禁止回退）', 'warning');
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
