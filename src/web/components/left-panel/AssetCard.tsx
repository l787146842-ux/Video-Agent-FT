import { For, Show, createSignal } from 'solid-js';
import { FiMessageSquare, FiRotateCcw, FiTrash2, FiVideo, FiMusic, FiX } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { checkpointHistory, performUndo } from '@/stores/history';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { safeUrl, uid } from '@/lib/utils';
import type { Asset, AnyGroup, DraftType } from '@/types';

/** 故事板三个分区（还原目标分组选择弹窗用） */
const RESTORE_SECTIONS: Array<{
  type: DraftType;
  field: 'keyElements' | 'shots' | 'audioItems';
  label: string;
}> = [
  { type: 'keyElement', field: 'keyElements', label: '关键元素' },
  { type: 'shot', field: 'shots', label: '分镜' },
  { type: 'audio', field: 'audioItems', label: '音频' },
];

/**
 * 未归类素材卡片：与故事板草稿卡片同尺寸（复用 .draft-card 样式）。
 * 点击 → 在中间预览区展示媒体（findDraftRecord 资产回退合成只读草稿）；
 * 右键菜单：添加到对话、还原到原分组（有来源信息时）、删除素材。
 */
export function AssetCard(props: { asset: Asset }) {
  /** 还原目标分组选择弹窗（无来源快照的旧素材右键还原时打开） */
  const [pickerOpen, setPickerOpen] = createSignal(false);

  // 选中判定匹配 id + 映射类型（selectAsset 会按素材媒体类型设置 selectedType）
  const selected = () => {
    const t = props.asset.type === 'video' ? 'shot' : props.asset.type === 'audio' ? 'audio' : 'keyElement';
    return state.selectedDraftId === props.asset.id && state.selectedType === t;
  };
  const url = () => safeUrl(props.asset.url);

  const bgStyle = () =>
    props.asset.type === 'image' && url()
      ? { 'background-image': `url('${url()}')` }
      : { 'background-color': 'var(--color-surface-placeholder)' };

  /** 视频首帧缩略图地址（追加 #t=0.1 强制浏览器渲染第一帧） */
  const videoThumbUrl = () => {
    const u = url();
    return u && !u.includes('#') ? `${u}#t=0.1` : u;
  };

  function addToChat() {
    studioActions.selectAsset(props.asset.id);
    if (!props.asset.url) return;
    requestInsertMedia({
      id: uid('im'),
      kind: props.asset.type,
      url: props.asset.url,
      name: props.asset.name,
    });
    showToast(`已将「${props.asset.name}」添加到对话`, 'success');
  }

  async function handleDelete() {
    const ok = await confirmDialog({
      title: `删除素材「${props.asset.name}」？`,
      message: '删除后可通过 Ctrl+Z 或 Header 撤销按钮恢复。',
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    await checkpointHistory();
    studioActions.removeAssetLocal(props.asset.id);
    showToast(`素材「${props.asset.name}」已删除（Ctrl+Z 可撤销）`, 'warning', 5000, {
      label: '撤销',
      onClick: () => void performUndo(),
    });
  }

  /** 还原：有来源快照且原分组还在 → 直接还原；否则弹目标分组选择（旧素材无来源记录） */
  async function handleRestore() {
    const a = props.asset;
    if (a.sourceType && a.sourceGroupId && a.sourceDraft) {
      await checkpointHistory();
      if (studioActions.restoreAssetToSource(a.id)) return;
    }
    setPickerOpen(true);
  }

  /** 选择目标分组还原（以素材信息合成草稿放入） */
  async function pickRestore(type: DraftType, groupId: string) {
    setPickerOpen(false);
    await checkpointHistory();
    if (!studioActions.restoreAssetToGroup(props.asset.id, type, groupId)) {
      showToast('目标分组不存在，无法还原', 'warning');
    }
  }

  function onContextMenu(e: MouseEvent) {
    showContextMenu(e, [
      { label: '添加到对话', icon: FiMessageSquare, onClick: addToChat },
      { label: '还原', icon: FiRotateCcw, onClick: () => void handleRestore() },
      { label: '删除素材', icon: FiTrash2, danger: true, onClick: handleDelete },
    ]);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      class={`draft-card ${selected() ? 'active' : ''}`}
      style={bgStyle()}
      onClick={() => studioActions.selectAsset(props.asset.id)}
      onKeyDown={(e) => e.key === 'Enter' && studioActions.selectAsset(props.asset.id)}
      onContextMenu={onContextMenu}
      title={props.asset.name}
    >
      {/* 视频媒体：首帧缩略图 + 类型角标 */}
      <Show when={props.asset.type === 'video' && url()}>
        <video
          class="draft-card-thumb-video"
          src={videoThumbUrl()}
          muted
          playsinline
          preload="metadata"
        />
      </Show>
      <Show when={props.asset.type === 'video'}>
        <span class="draft-card-media-badge" title="视频">
          <FiVideo size={11} />
        </span>
      </Show>
      {/* 音频媒体：音符 + 波形标识 */}
      <Show when={props.asset.type === 'audio'}>
        <div class="draft-card-audio-indicator" title="音频">
          <FiMusic size={15} />
          <div class="draft-card-wave">
            <span /><span /><span /><span /><span />
          </div>
        </div>
      </Show>
      {/* 名称常显（未归类素材没有分组上下文，隐藏名称将无法辨认卡片） */}
      <span class="draft-card-label">{props.asset.name}</span>

      {/* 还原目标分组选择弹窗：按 关键元素/分镜/音频 分区列出分组 */}
      <Show when={pickerOpen()}>
        <div class="asset-modal restore-picker-modal">
          <div class="asset-modal-backdrop" onClick={() => setPickerOpen(false)} />
          <div class="asset-modal-panel restore-picker-panel">
            <div class="asset-modal-header">
              <div class="canvas-picker-title">
                <FiRotateCcw size={15} />
                <span>选择还原到的分组</span>
              </div>
              <button class="asset-modal-close" onClick={() => setPickerOpen(false)} title="关闭">
                <FiX size={16} />
              </button>
            </div>
            <div class="restore-picker-body">
              <For each={RESTORE_SECTIONS}>
                {(sec) => (
                  <Show when={(state[sec.field] as AnyGroup[]).length > 0}>
                    <div class="restore-picker-label">{sec.label}</div>
                    <div class="restore-picker-groups">
                      <For each={state[sec.field] as AnyGroup[]}>
                        {(g) => (
                          <button
                            type="button"
                            class="restore-picker-group"
                            title={g.title}
                            onClick={() => void pickRestore(sec.type, g.id)}
                          >
                            {g.title}
                          </button>
                        )}
                      </For>
                    </div>
                  </Show>
                )}
              </For>
            </div>
          </div>
        </div>
      </Show>
    </div>
  );
}
