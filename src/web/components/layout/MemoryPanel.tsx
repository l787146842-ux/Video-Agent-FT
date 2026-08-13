import { createEffect, createSignal, For, Show } from 'solid-js';
import { FiRefreshCw, FiStar, FiTrash2, FiX } from 'solid-icons/fi';
import { listMemory, deleteMemory, pinMemory, type MemoryRecordView } from '@/api/memory';
import { showToast } from '@/stores/toast';

/**
 * 记忆管理面板（4.7）：查看/删除 Agent 的长期记忆。
 * 入口在 Header 右侧（数据库图标）；与 DocsPanel 一样由 LayoutShell 全局挂载。
 */
const [open, setOpen] = createSignal(false);

export function toggleMemoryPanel() {
  setOpen((v) => !v);
}

function formatTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function MemoryPanel() {
  const [records, setRecords] = createSignal<MemoryRecordView[]>([]);
  const [backend, setBackend] = createSignal('');
  const [loading, setLoading] = createSignal(false);

  async function load() {
    setLoading(true);
    try {
      const data = await listMemory();
      setRecords(data.records || []);
      setBackend(data.backend || '');
    } catch (e) {
      showToast(`记忆列表加载失败：${(e as Error).message}`, 'error');
    } finally {
      setLoading(false);
    }
  }

  // 每次打开时刷新清单
  createEffect(() => {
    if (open()) void load();
  });

  async function remove(rec: MemoryRecordView) {
    try {
      await deleteMemory(rec.id);
      showToast('已删除该条记忆', 'success');
      void load();
    } catch (e) {
      showToast(`删除失败：${(e as Error).message}`, 'error');
    }
  }

  /** 置顶/取消置顶（M4）：置顶记忆永远排在最前，豁免将来的自动清理 */
  async function togglePin(rec: MemoryRecordView) {
    try {
      await pinMemory(rec.id, !rec.pinned);
      showToast(rec.pinned ? '已取消置顶' : '已置顶（永远排在最前）', 'success');
      void load();
    } catch (e) {
      showToast(`置顶操作失败：${(e as Error).message}`, 'error');
    }
  }

  return (
    <Show when={open()}>
      <div
        class="skill-modal-backdrop"
        onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
      >
        <div class="skill-modal memory-panel">
          <div class="skill-modal-header">
            <div class="skill-modal-title" style={{ padding: 0 }}>
              Agent 记忆
              <Show when={backend()}>
                <span class="memory-backend-badge">{backend()}</span>
              </Show>
            </div>
            <div class="memory-panel-tools">
              <button
                type="button"
                class="skill-modal-close"
                title="刷新"
                onClick={() => void load()}
              >
                <FiRefreshCw size={14} class={loading() ? 'spin' : ''} />
              </button>
              <button
                type="button"
                class="skill-modal-close"
                title="关闭"
                onClick={() => setOpen(false)}
              >
                <FiX size={16} />
              </button>
            </div>
          </div>

          <div class="memory-panel-body">
            <Show when={loading() && !records().length}>
              <div class="empty-state centered">加载中…</div>
            </Show>
            <Show when={!loading() && !records().length}>
              <div class="empty-state centered">暂无记忆（每 10 轮对话自动沉淀一次摘要）</div>
            </Show>
            <For each={records()}>
              {(rec) => (
                <div class="memory-item">
                  <div class="memory-item-content">{rec.content}</div>
                  <div class="memory-item-meta">
                    <span>{formatTime(rec.created_at)}</span>
                    <Show when={rec.source}>
                      <span class="memory-item-source">来源：{rec.source}</span>
                    </Show>
                    <button
                      type="button"
                      class={`memory-item-pin ${rec.pinned ? 'on' : ''}`}
                      title={rec.pinned ? '取消置顶' : '置顶（永远排在最前，豁免将来的自动清理）'}
                      onClick={() => void togglePin(rec)}
                    >
                      <FiStar size={13} />
                    </button>
                    <button
                      type="button"
                      class="memory-item-delete"
                      title="删除这条记忆"
                      onClick={() => void remove(rec)}
                    >
                      <FiTrash2 size={13} />
                    </button>
                  </div>
                </div>
              )}
            </For>
          </div>
        </div>
      </div>
    </Show>
  );
}
