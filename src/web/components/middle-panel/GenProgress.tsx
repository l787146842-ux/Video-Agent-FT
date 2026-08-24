import type { ActiveGeneration } from '@/types';

/** 预览区生成中进度环（200ms 秒表由父级驱动 elapsed） */
export function GenProgress(props: { gen: ActiveGeneration; elapsed: number }) {
  const ringOffset = () => 251.2 * (1 - (props.elapsed % 60) / 60);
  return (
    <div class="gen-progress">
      <div class="gen-progress-ring">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" style={{ stroke: 'var(--color-surface-track)' }} stroke-width="8" />
          <circle
            cx="50" cy="50" r="40" fill="none" style={{ stroke: 'var(--accent-blue)' }} stroke-width="8"
            stroke-linecap="round" stroke-dasharray="251.2"
            stroke-dashoffset={ringOffset()}
          />
        </svg>
        <span class="gen-progress-time">{props.elapsed.toFixed(1)}s</span>
      </div>
      <span class="gen-progress-label">
        {props.gen.kind === 'image' ? '图片生成中…' : '视频渲染中…'}
      </span>
    </div>
  );
}
