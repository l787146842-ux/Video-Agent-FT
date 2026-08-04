import { Show } from 'solid-js';
import { FiLogOut, FiMessageSquare, FiTrash2, FiVideo, FiMusic } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { checkpointHistory, performUndo } from '@/stores/history';
import { requestInsertMedia, requestInsertText } from '@/lib/chat-input-bridge';
import { draftToInlineMedia } from '@/lib/rich-input';
import { safeUrl } from '@/lib/utils';
import type { Draft, DraftType } from '@/types';

/**
 * 单张草稿卡片：缩略图背景 / 标签 / 选中态 / 生成中动画
 * 卡片下方显示小标编号（组号-卡序号，如 1-2，与 Agent 上下文对齐）；
 * 卡片可拖动排序（拖放事件由 GroupCard 协调），排序后编号自动重排。
 * 右键菜单：添加到对话、删除、移除到未归类
 */
export function DraftCard(props: {
  draft: Draft;
  type: DraftType;
  groupId: string;
  /** 小标编号（如 1-2） */
  cardCode?: string;
  dragOver?: boolean;
  onDragStart?: (e: DragEvent) => void;
  onDragOver?: (e: DragEvent) => void;
  onDragLeave?: () => void;
  onDrop?: (e: DragEvent) => void;
  onDragEnd?: () => void;
}) {
  const selected = () => state.selectedDraftId === props.draft.id;
  const generating = () => !!state.activeGenerations[props.draft.id];

  const bgStyle = () => {
    const d = props.draft;
    const imgUrl = safeUrl(d.imgUrl || '');
    // 图片媒体用图片背景；视频尚无 videoUrl 时用首帧图片占位
    const showImgBg = imgUrl && (d.mediaType === 'image' || (d.mediaType === 'video' && !d.videoUrl));
    if (showImgBg) {
      return { 'background-image': `url('${imgUrl}')` };
    }
    // 分镜紫灰 / 其他深蓝（对齐旧版配色）
    return {
      'background-color': props.type === 'shot' ? '#2e3346' : '#1e293b',
    };
  };

  /** 视频首帧缩略图地址（追加 #t=0.1 强制浏览器渲染第一帧） */
  const videoThumbUrl = () => {
    const u = safeUrl(props.draft.videoUrl || '');
    if (!u) return '';
    return u.includes('#') ? u : `${u}#t=0.1`;
  };

  /** 是否已有媒体文件（上传/生成后）：有则隐藏所有文字标识 */
  const hasMedia = () => {
    const d = props.draft;
    if (d.mediaType === 'video') return !!d.videoUrl;
    if (d.mediaType === 'audio') return !!d.audioUrl;
    return !!d.imgUrl;
  };

  function addToChat() {
    studioActions.selectDraft(props.draft.id, props.type);
    const label = props.draft.label || props.draft.id;
    // 有媒体文件（图片/视频/音频）→ 以内联缩略块插入到对话输入框光标处，
    // 让大模型能真正「看到」媒体并识别它与文字的对应关系。
    const media = draftToInlineMedia(props.draft);
    if (media) {
      requestInsertMedia(media);
      const kindLabel = media.kind === 'image' ? '图片' : media.kind === 'video' ? '视频' : '音频';
      showToast(`已将「${label}」的${kindLabel}添加到对话`, 'success');
    } else {
      // 空卡片（尚未生成媒体）→ 回退为文本引用，插入光标处
      requestInsertText(`针对草稿「${label}」：`);
      showToast(`已引用草稿「${label}」`, 'success');
    }
  }

  async function handleDelete() {
    const label = props.draft.label || '未命名草稿';
    const ok = await confirmDialog({
      title: `删除草稿「${label}」？`,
      message: '删除后可通过 Ctrl+Z 或 Header 撤销按钮恢复。',
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    // 先压撤销检查点，再删除 —— 保证"整体 PUT"路径也能一次 undo 恢复
    await checkpointHistory();
    studioActions.removeDraftLocal(props.type, props.groupId, props.draft.id);
    showToast(`草稿「${label}」已删除（Ctrl+Z 可撤销）`, 'warning', 5000, {
      label: '撤销',
      onClick: () => void performUndo(),
    });
  }

  async function handleMoveOut() {
    await checkpointHistory();
    studioActions.moveDraftToAssets(props.type, props.groupId, props.draft.id);
  }

  function onContextMenu(e: MouseEvent) {
    showContextMenu(e, [
      { label: '添加到对话', icon: FiMessageSquare, onClick: addToChat },
      { label: '删除此草稿', icon: FiTrash2, danger: true, onClick: handleDelete },
      { label: '移除到未归类素材', icon: FiLogOut, onClick: handleMoveOut },
    ]);
  }

  return (
    <div
      class="draft-card-col"
      draggable={!!props.onDragStart}
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer!.setData('application/x-draft-id', props.draft.id);
        e.dataTransfer!.effectAllowed = 'move';
        props.onDragStart?.(e);
      }}
      onDragOver={(e) => props.onDragOver?.(e)}
      onDragLeave={() => props.onDragLeave?.()}
      onDrop={(e) => props.onDrop?.(e)}
      onDragEnd={() => props.onDragEnd?.()}
    >
      <div
        role="button"
        tabIndex={0}
        class={`draft-card ${selected() ? 'active' : ''} ${generating() ? 'animate-pulse' : ''} ${props.dragOver ? 'drag-over' : ''}`}
        style={bgStyle()}
        onClick={() => studioActions.selectDraft(props.draft.id, props.type)}
        onKeyDown={(e) => e.key === 'Enter' && studioActions.selectDraft(props.draft.id, props.type)}
        onContextMenu={onContextMenu}
      >
      {/* 视频媒体：首帧缩略图 + 类型角标 */}
        <Show when={props.draft.mediaType === 'video' && props.draft.videoUrl}>
          <video
            class="draft-card-thumb-video"
            src={videoThumbUrl()}
            muted
            playsinline
            preload="metadata"
          />
        </Show>
        <Show when={props.draft.mediaType === 'video'}>
          <span class="draft-card-media-badge" title="视频">
            <FiVideo size={11} />
          </span>
        </Show>
        {/* 音频媒体：音符 + 波形标识 */}
        <Show when={props.draft.mediaType === 'audio'}>
          <div class="draft-card-audio-indicator" title="音频">
            <FiMusic size={15} />
            <div class="draft-card-wave">
              <span /><span /><span /><span /><span />
            </div>
          </div>
        </Show>
        {/* 文字标识（状态标签 + 名称）仅在空卡片时显示；有媒体后隐藏 */}
        <Show when={!hasMedia()}>
          <Show when={props.draft.tag}>
            <span
              class="draft-card-tag"
              style={{
                background: props.type === 'shot'
                  ? 'rgba(139, 92, 246, 0.85)'
                  : 'rgba(59, 130, 246, 0.85)',
              }}
            >
              {props.draft.tag}
            </span>
          </Show>
          <span class="draft-card-label">
            {props.draft.label}
          </span>
        </Show>
      </div>
      {/* 小标编号：组号-卡序号（拖动排序后自动重排，Agent 可按此定位） */}
      <Show when={props.cardCode}>
        <span class="draft-card-code" title="卡片编号（组号-卡序号），可拖动排序">{props.cardCode}</span>
      </Show>
    </div>
  );
}
