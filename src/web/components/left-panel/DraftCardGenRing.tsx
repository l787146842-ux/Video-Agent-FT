import { createEffect, createSignal, onCleanup, Show } from 'solid-js';
import { state } from '@/stores/studio';
import { GenProgress } from '@/components/middle-panel/GenProgress';
import type { Draft } from '@/types';

/**
 * 卡内生成读秒环（2026-10-26 用户裁决：左栏卡片与中间预览框一致）。
 * 与预览框同规则：生成中且该卡**无当前媒体**时覆层显示紧凑读秒环；
 * 已有媒体则让位给媒体本体（读秒不叠在图上）。
 */
export function DraftCardGenRing(props: { draft: Draft }) {
  const gen = () => state.activeGenerations[props.draft.id];
  /** 当前卡主媒体（与 MediaViewer.mediaUrl 同口径） */
  const mediaUrl = () => {
    const d = props.draft;
    if (d.mediaType === 'video') return d.videoUrl || '';
    if (d.mediaType === 'audio') return d.audioUrl || '';
    return d.imgUrl || '';
  };

  // 200ms 秒表（与中间预览框同源节拍；仅生成中挂表）
  const [elapsed, setElapsed] = createSignal(0);
  createEffect(() => {
    const g = gen();
    if (!g) return;
    setElapsed((Date.now() - g.start) / 1000);
    const timer = setInterval(() => setElapsed((Date.now() - g.start) / 1000), 200);
    onCleanup(() => clearInterval(timer));
  });

  return (
    <Show when={gen() && !mediaUrl()}>
      <div class="draft-card-gen-overlay">
        <GenProgress gen={gen()!} elapsed={elapsed()} compact />
      </div>
    </Show>
  );
}
