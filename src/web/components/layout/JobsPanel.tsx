/**
 * Job 面板 — 视频批量生成任务管理（列表/详情/resume/cancel）。
 * 入口在顶栏 Header，模态浮窗风格对齐生成日志面板。
 */
import { For, Show, createSignal } from 'solid-js';
import {
  FiX, FiPlay, FiSlash, FiChevronLeft, FiRefreshCw, FiClock,
} from 'solid-icons/fi';
import {
  jobsOpen, jobs, jobsLoading, selectedJob, detailLoading,
  closeJobs, refreshJobs, viewJobDetail, backToList, resumeJob, cancelJob,
} from '@/stores/jobs';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { useFocusTrap } from '@/lib/focus-trap';
import type { BatchSummary } from '@/api/jobs';

type StatusFilter = 'all' | 'running' | 'done' | 'failed';

function statusLabel(s: string): string {
  switch (s) {
    case 'running': return '执行中';
    case 'done': return '已完成';
    case 'partial': return '部分失败';
    case 'failed': return '失败';
    case 'cancelled': return '已取消';
    case 'interrupted': return '已中断';
    default: return s;
  }
}

function statusClass(s: string): string {
  if (s === 'done') return 'jobs-badge--ok';
  if (s === 'running') return 'jobs-badge--running';
  if (s === 'failed' || s === 'partial') return 'jobs-badge--failed';
  if (s === 'cancelled' || s === 'interrupted') return 'jobs-badge--muted';
  return '';
}

function formatTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function BatchRow(props: { batch: BatchSummary }) {
  const b = () => props.batch;
  return (
    <div
      class="jobs-item"
      classList={{ 'jobs-item--clickable': true }}
      role="button"
      tabIndex={0}
      onClick={() => void viewJobDetail(b().batch_id)}
      onKeyDown={(e) => { if (e.key === 'Enter') void viewJobDetail(b().batch_id); }}
    >
      <div class="jobs-item-main">
        <div class="jobs-row1">
          <span class={`jobs-badge ${statusClass(b().status)}`}>{statusLabel(b().status)}</span>
          <span class="jobs-progress">{b().done}/{b().total} 镜</span>
          <Show when={b().failed > 0}>
            <span class="jobs-failed-count">{b().failed} 失败</span>
          </Show>
          <span class="jobs-time"><FiClock size={10} /> {formatTime(b().created_at)}</span>
        </div>
        <div class="jobs-row2">
          批次 {b().batch_id}
        </div>
      </div>
      <div class="jobs-item-actions">
        <Show when={b().status === 'interrupted' || b().status === 'partial' || b().status === 'failed'}>
          <button
            type="button"
            class="jobs-action-btn jobs-action-btn--resume"
            title="断点续跑"
            onClick={(e) => { e.stopPropagation(); void resumeJob(b().batch_id); }}
          >
            <FiPlay size={12} />
          </button>
        </Show>
        <Show when={b().status === 'running'}>
          <button
            type="button"
            class="jobs-action-btn jobs-action-btn--cancel"
            title="取消批次"
            onClick={async (e) => {
              e.stopPropagation();
              const ok = await confirmDialog({
                title: '取消批量任务',
                message: '取消后不再提交新镜头，已提交的生成任务仍会继续。',
                confirmText: '取消任务',
                danger: true,
              });
              if (ok) void cancelJob(b().batch_id);
            }}
          >
            <FiSlash size={12} />
          </button>
        </Show>
      </div>
    </div>
  );
}

export function JobsPanel() {
  const [filter, setFilter] = createSignal<StatusFilter>('all');
  const [panelEl, setPanelEl] = createSignal<HTMLElement>();
  useFocusTrap(() => (jobsOpen() ? panelEl() : undefined), { onEscape: () => closeJobs() });

  const filtered = () => {
    const all = jobs();
    const f = filter();
    if (f === 'all') return all;
    if (f === 'running') return all.filter((b) => b.status === 'running');
    if (f === 'done') return all.filter((b) => b.status === 'done');
    if (f === 'failed') return all.filter((b) => ['failed', 'partial', 'interrupted'].includes(b.status));
    return all;
  };

  return (
    <Show when={jobsOpen()}>
      <div class="jobs-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeJobs(); }}>
        <div class="jobs-panel" ref={setPanelEl} role="dialog" aria-label="批量生成任务">
          {/* 头部 */}
          <div class="jobs-header">
            <Show when={selectedJob()} fallback={
              <span class="jobs-title">批量生成任务</span>
            }>
              <button type="button" class="jobs-back-btn" onClick={backToList} title="返回列表">
                <FiChevronLeft size={14} />
              </button>
              <span class="jobs-title">批次详情</span>
            </Show>
            <Show when={!selectedJob()}>
              <div class="jobs-filters">
                <For each={['all', 'running', 'done', 'failed'] as StatusFilter[]}>
                  {(f) => (
                    <button
                      type="button"
                      class="jobs-filter"
                      classList={{ active: filter() === f }}
                      onClick={() => setFilter(f)}
                    >
                      {f === 'all' ? '全部' : f === 'running' ? '执行中' : f === 'done' ? '已完成' : '异常'}
                    </button>
                  )}
                </For>
              </div>
            </Show>
            <div class="jobs-header-right">
              <Show when={!selectedJob()}>
                <button
                  type="button"
                  class="jobs-refresh-btn"
                  title="刷新"
                  onClick={() => void refreshJobs()}
                  disabled={jobsLoading()}
                >
                  <FiRefreshCw size={13} classList={{ 'spin-anim': jobsLoading() }} />
                </button>
              </Show>
              <button type="button" class="jobs-close" title="关闭" onClick={closeJobs}>
                <FiX size={16} />
              </button>
            </div>
          </div>

          {/* 列表视图 */}
          <Show when={!selectedJob()}>
            <div class="jobs-list">
              <Show when={jobsLoading() && jobs().length === 0}>
                <div class="jobs-empty">加载中…</div>
              </Show>
              <Show when={!jobsLoading() && filtered().length === 0}>
                <div class="jobs-empty">暂无批量生成任务</div>
              </Show>
              <For each={filtered()}>
                {(batch) => <BatchRow batch={batch} />}
              </For>
            </div>
          </Show>

          {/* 详情视图 */}
          <Show when={selectedJob()}>
            {(detail) => (
              <div class="jobs-detail">
                <Show when={detailLoading()}>
                  <div class="jobs-empty">加载中…</div>
                </Show>
                <div class="jobs-detail-meta">
                  <span class={`jobs-badge ${statusClass(detail().status)}`}>{statusLabel(detail().status)}</span>
                  <span>模型：{detail().model || '—'}</span>
                  <span>分辨率：{detail().resolution || '—'}</span>
                  <span>时长：{detail().duration || '—'}s</span>
                  <span>进度：{detail().done}/{detail().total}</span>
                </div>
                <div class="jobs-detail-actions">
                  <Show when={['interrupted', 'partial', 'failed'].includes(detail().status)}>
                    <button
                      type="button"
                      class="jobs-btn jobs-btn--resume"
                      onClick={() => void resumeJob(detail().batch_id)}
                    >
                      <FiPlay size={12} /> 断点续跑
                    </button>
                  </Show>
                  <Show when={detail().status === 'running'}>
                    <button
                      type="button"
                      class="jobs-btn jobs-btn--cancel"
                      onClick={async () => {
                        const ok = await confirmDialog({
                          title: '取消批量任务',
                          message: '取消后不再提交新镜头，已提交的生成任务仍会继续。',
                          confirmText: '取消任务',
                          danger: true,
                        });
                        if (ok) void cancelJob(detail().batch_id);
                      }}
                    >
                      <FiSlash size={12} /> 取消批次
                    </button>
                  </Show>
                </div>
                {/* 逐镜清单 */}
                <div class="jobs-shots">
                  <For each={detail().shots}>
                    {(shot) => (
                      <div class="jobs-shot-row" classList={{ 'jobs-shot-row--failed': shot.status === 'failed' }}>
                        <span class={`jobs-badge ${statusClass(shot.status)}`}>
                          {shot.status === 'succeeded' ? '成功' : shot.status === 'failed' ? '失败' : shot.status === 'running' ? '生成中' : '待处理'}
                        </span>
                        <span class="jobs-shot-title">{shot.title || shot.draft_id}</span>
                        <Show when={shot.error}>
                          <span class="jobs-shot-error">{shot.error}</span>
                        </Show>
                      </div>
                    )}
                  </For>
                </div>
              </div>
            )}
          </Show>
        </div>
      </div>
    </Show>
  );
}
