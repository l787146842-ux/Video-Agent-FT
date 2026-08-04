/**
 * 生成日志面板（顶部导航入口）— 照搬画布「生成日志」样式：
 * 每条记录含状态徽标（成功/失败/进行中）、供应商+模型标签、耗时+时间戳、
 * 请求规格、提示词描述、右侧缩略图。图/视频/音频无论成败均有记录。
 */
import { For, Show, createSignal } from 'solid-js';
import { FiX, FiImage, FiVideo, FiMusic } from 'solid-icons/fi';
import { genLogs, genLogOpen, closeGenLog } from '@/stores/generation-log';
import { safeUrl } from '@/lib/utils';

type FilterKind = 'all' | 'image' | 'video' | 'audio';

function StatusBadge(props: { status: string }) {
  return (
    <Show
      when={props.status === 'succeeded'}
      fallback={
        <Show
          when={props.status === 'failed'}
          fallback={<span class="genlog-badge genlog-badge--running">进行中</span>}
        >
          <span class="genlog-badge genlog-badge--failed">失败</span>
        </Show>
      }
    >
      <span class="genlog-badge genlog-badge--ok">成功</span>
    </Show>
  );
}

function KindIcon(props: { kind: string }) {
  return (
    <Show when={props.kind === 'video'} fallback={
      <Show when={props.kind === 'audio'} fallback={<FiImage size={13} />}>
        <FiMusic size={13} />
      </Show>
    }>
      <FiVideo size={13} />
    </Show>
  );
}

export function GenerationLogPanel() {
  const [filter, setFilter] = createSignal<FilterKind>('all');

  const logs = () => {
    const all = genLogs();
    const f = filter();
    return f === 'all' ? all : all.filter((l) => l.media_type === f);
  };

  const filterBtn = (kind: FilterKind, label: string) => (
    <button
      type="button"
      class={filter() === kind ? 'genlog-filter active' : 'genlog-filter'}
      onClick={() => setFilter(kind)}
    >
      {label}
    </button>
  );

  return (
    <Show when={genLogOpen()}>
      <div class="genlog-overlay">
        <div class="genlog-panel" role="dialog" aria-label="生成日志">
          <div class="genlog-header">
            <span class="genlog-title">生成日志</span>
            <div class="genlog-filters">
              {filterBtn('all', '全部')}
              {filterBtn('image', '图片')}
              {filterBtn('video', '视频')}
              {filterBtn('audio', '音频')}
            </div>
            <button type="button" class="genlog-close" title="关闭" onClick={() => closeGenLog()}>
              <FiX size={16} />
            </button>
          </div>

          <div class="genlog-list">
            <Show when={logs().length === 0}>
              <div class="genlog-empty">暂无生成记录</div>
            </Show>
            <For each={logs()}>
              {(log) => (
                <div class={log.status === 'failed' ? 'genlog-item genlog-item--failed' : 'genlog-item'}>
                  <div class="genlog-item-main">
                    <div class="genlog-row1">
                      <StatusBadge status={log.status} />
                      <span class="genlog-provider"><KindIcon kind={log.media_type} /> {log.provider_name || log.provider || '未知供应商'}</span>
                      <Show when={log.model}>
                        <span class="genlog-model">{log.model}</span>
                      </Show>
                      <span class="genlog-time">
                        {log.status === 'started' ? '' : `${log.elapsed}s · `}{log.ts}
                      </span>
                    </div>
                    <Show when={log.requested_size}>
                      <div class="genlog-row2">请求 {log.requested_size}</div>
                    </Show>
                    <Show when={log.prompt}>
                      <div class="genlog-desc" title={log.prompt}>{log.prompt}</div>
                    </Show>
                    <Show when={log.status === 'failed' && log.error}>
                      <div class="genlog-error">{log.error}</div>
                    </Show>
                  </div>
                  <Show when={log.result_url && log.media_type !== 'audio'}>
                    <div class="genlog-thumb-wrap">
                      <Show when={log.media_type === 'video'} fallback={
                        <img class="genlog-thumb" src={safeUrl(log.result_url)} alt="生成结果" loading="lazy" />
                      }>
                        <video class="genlog-thumb" src={safeUrl(log.result_url)} muted preload="metadata" />
                      </Show>
                    </div>
                  </Show>
                </div>
              )}
            </For>
          </div>
        </div>
      </div>
    </Show>
  );
}
