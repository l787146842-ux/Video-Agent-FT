import { For, Show, createSignal } from 'solid-js';
import { FiImage, FiVideo, FiMusic, FiChevronDown, FiChevronUp } from 'solid-icons/fi';
import { state, findDraftRecord, studioActions } from '@/stores/studio';
import type { MediaType } from '@/types';
import type { IconTypes } from 'solid-icons';

/** 生成类型标签全集：关键元素三选一、分镜仅图片/视频（分镜不生成音频） */
const TABS: Array<{ key: MediaType; label: string; Icon: IconTypes }> = [
  { key: 'image', label: '图片生成', Icon: FiImage },
  { key: 'video', label: '视频生成', Icon: FiVideo },
  { key: 'audio', label: '音频生成', Icon: FiMusic },
];

/** 分镜卡可选生成类型：分镜表格图（图片）与分镜视频（视频） */
const SHOT_TYPES: MediaType[] = ['image', 'video'];

/**
 * 生成类型切换标签（关键元素 / 分镜面板显示）。
 * 以 draft.genType（缺省回退 mediaType）为当前生成类型：切换仅联动底部参数栏，
 * 不清空已有预览媒体（一张卡片只存一个媒体，预览始终展示该媒体）。
 * 底部箭头可收缩/展开：收缩后预览框内容完整展示、无遮挡。
 */
export function GenTypeTabs() {
  const [collapsed, setCollapsed] = createSignal(false);
  const rec = () => findDraftRecord(state.selectedDraftId, state.selectedType);
  const active = () => {
    const d = rec()?.draft;
    return d?.genType || d?.mediaType || 'image';
  };

  /** 可选类型：分镜卡只给图片/视频（2026-10-20 用户裁决：分镜卡可出图与出视频） */
  const tabs = () => {
    const allowed = state.selectedType === 'shot' ? SHOT_TYPES : null;
    return allowed ? TABS.filter((t) => allowed.includes(t.key)) : TABS;
  };

  function select(key: MediaType) {
    const r = rec();
    if (!r || active() === key) return;
    // 仅切换生成类型，不改动已上传/已生成的媒体
    studioActions.updateDraftLocal(r.type, r.draft.id, { genType: key });
  }

  return (
    <div
      class="gen-type-tabs-wrap"
      onClick={(e) => e.stopPropagation()}
      onDblClick={(e) => e.stopPropagation()}
    >
      <Show when={!collapsed()}>
        <div class="gen-type-tabs">
          <For each={tabs()}>
            {(t) => (
              <button
                type="button"
                class={`gen-type-tab ${active() === t.key ? 'active' : ''}`}
                title={t.label}
                onClick={() => select(t.key)}
              >
                <t.Icon size={15} />
                <span>{t.label}</span>
              </button>
            )}
          </For>
        </div>
      </Show>
      <button
        type="button"
        class="gen-type-toggle"
        title={collapsed() ? '展开生成类型' : '收起生成类型'}
        onClick={() => setCollapsed((v) => !v)}
      >
        {collapsed() ? <FiChevronDown size={13} /> : <FiChevronUp size={13} />}
      </button>
    </div>
  );
}
