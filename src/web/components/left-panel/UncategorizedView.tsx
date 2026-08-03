import { For, Show } from 'solid-js';
import { state, studioActions } from '@/stores/studio';
import { AssetCard } from './AssetCard';
import { DraftCard } from './DraftCard';
import type { AnyGroup, DraftType } from '@/types';

/** 故事板三个分区的元信息（「显示全部」时按区分组渲染） */
const BOARD_SECTIONS: Array<{
  type: DraftType;
  field: 'keyElements' | 'shots' | 'audioItems';
  label: string;
}> = [
  { type: 'keyElement', field: 'keyElements', label: '关键元素' },
  { type: 'shot', field: 'shots', label: '分镜' },
  { type: 'audio', field: 'audioItems', label: '音频' },
];

/**
 * 未归类素材视图：
 * - 未归类素材 = 从故事板移除的卡片（agent 不可调取），与故事板卡片同尺寸，
 *   点击即在中间预览区展示媒体；
 * - 「显示全部」= 未归类素材 + 故事板所有卡片（关键元素 / 分镜 / 音频）。
 */
export function UncategorizedView() {
  const boardHasDrafts = (field: (typeof BOARD_SECTIONS)[number]['field']) =>
    (state[field] as AnyGroup[]).some((g) => g.drafts?.length);

  return (
    <div class="uncategorized-view">
      {/* 头部：标题 + 开关 */}
      <div class="uncategorized-header">
        <span class="uncategorized-title">未归类素材</span>
        <button
          type="button"
          class="toggle-switch"
          aria-pressed={state.showAllAssets}
          onClick={() => studioActions.setShowAllAssets(!state.showAllAssets)}
        >
          <span>未归类</span>
          <span class={`switch-track ${state.showAllAssets ? 'active' : ''}`}>
            <span class="switch-thumb" />
          </span>
          <span>显示全部</span>
        </button>
      </div>

      {/* 未归类素材网格（卡片与故事板同尺寸） */}
      <div class="assets-grid">
        <For each={state.assets}>{(asset) => <AssetCard asset={asset} />}</For>
      </div>
      <Show when={!state.assets.length && !state.showAllAssets}>
        <div class="empty-state centered">暂无未归类素材</div>
      </Show>

      {/* 显示全部：追加故事板所有卡片（按 关键元素/分镜/音频 分区） */}
      <Show when={state.showAllAssets}>
        <For each={BOARD_SECTIONS}>
          {(sec) => (
            <Show when={boardHasDrafts(sec.field)}>
              <div class="uncategorized-section-label">{sec.label}</div>
              <div class="assets-grid">
                <For each={state[sec.field] as AnyGroup[]}>
                  {(group) => (
                    <For each={group.drafts || []}>
                      {(draft) => (
                        <DraftCard draft={draft} type={sec.type} groupId={group.id} />
                      )}
                    </For>
                  )}
                </For>
              </div>
            </Show>
          )}
        </For>
      </Show>
    </div>
  );
}
