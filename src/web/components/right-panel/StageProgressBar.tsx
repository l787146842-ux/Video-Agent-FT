import { createMemo, For, Show } from 'solid-js';
import { state } from '@/stores/studio';
import { t, type LocaleKey } from '@/lib/locale';
import {
  deriveBoardProgress, type BoardProgress,
} from '@/lib/storyboard-progress';

/** 板块标识 → 展示文案键（与故事板三区一一对应） */
const BOARD_LABEL_KEY: Record<BoardProgress['board'], LocaleKey> = {
  keyElements: 'rp.progress.ke',
  shots: 'rp.progress.shots',
  audioItems: 'rp.progress.audio',
};

/**
 * 长任务阶段进度条（流式中常驻消息流顶部）：
 * - 故事板客观进度：关键元素/分镜/音频三区「已有媒体草稿数/总数」，
 *   与 storyboard_progress 模板同口径（客观状态，非模型自报）。
 * （推理轮次段已随阶段规则去代码化批退役：不设步数上限，无「N/M」可比，
 *   2026-09-10。）
 */
export function StageProgressBar() {
  const boards = createMemo(() => deriveBoardProgress({
    keyElements: state.keyElements,
    shots: state.shots,
    audioItems: state.audioItems,
  }));
  /** 无任何可展示进度（故事板全空）时整体不渲染 */
  const visible = createMemo(() => boards().some((b) => b.total > 0));

  return (
    <Show when={visible()}>
      <div class="stage-progress" role="status" aria-label={t('rp.progress.title')}>
        <div class="stage-progress-boards">
          <For each={boards()}>
            {(b) => (
              <Show when={b.total > 0}>
                <span
                  class={`stage-progress-board${b.done >= b.total ? ' done' : ''}`}
                  title={`${t(BOARD_LABEL_KEY[b.board])} ${b.done}/${b.total}`}
                >
                  <span class="stage-progress-board-name">{t(BOARD_LABEL_KEY[b.board])}</span>
                  <span class="stage-progress-board-count">{b.done}/{b.total}</span>
                </span>
              </Show>
            )}
          </For>
        </div>
      </div>
    </Show>
  );
}
