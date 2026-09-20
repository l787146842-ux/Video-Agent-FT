import { Show, createSignal, onMount, onCleanup } from 'solid-js';
import { FiLogOut, FiMessageSquare, FiTrash2, FiVideo, FiMusic } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { checkpointHistory, performUndo } from '@/stores/history';
import { requestInsertMedia, requestInsertText } from '@/lib/chat/chat-input-bridge';
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
  /** 悬停回调（分组级微调框定位用） */
  onHover?: (hovering: boolean) => void;
}) {
  // 选中判定必须同时匹配 id 与类型：防止跨 tab 同 id 卡双高亮
  const selected = () => state.selectedDraftId === props.draft.id && state.selectedType === props.type;
  const generating = () => !!state.activeGenerations[props.draft.id];

  // 视频缩略图懒加载：进入视口才设置 src，避免切 tab/列表重建时
  // 并发发起大量 metadata 请求撞浏览器每源 6 连接上限造成卡顿
  const [inView, setInView] = createSignal(false);
  let rootEl: HTMLDivElement | undefined;
  let observer: IntersectionObserver | undefined;
  onMount(() => {
    if (!rootEl || typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          observer?.disconnect();
        }
      },
      { rootMargin: '100px' },
    );
    observer.observe(rootEl);
  });
  onCleanup(() => observer?.disconnect());

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
      'background-color': props.type === 'shot' ? 'var(--color-surface-shot)' : 'var(--color-surface-placeholder)',
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

  /** 关键元素组内的角色音色卡（对齐 flova 小图标子卡）：半尺寸、卡面只留音频符号、
   *  不渲染名称/描述文字（内容经悬停 title 与中间预览框承载）；音频 tab 的 BGM/旁白卡不受影响 */
  const isVoiceCard = () => props.type === 'keyElement' && props.draft.mediaType === 'audio';

  /** 悬停 title：音色卡文字已隐藏，名称+描述都走 title 兜底；其余卡保持原 desc 兜底 */
  const cardTitle = () => {
    const desc = (props.draft.desc ?? '').trim();
    if (isVoiceCard()) return [props.draft.label, desc].filter(Boolean).join('　') || undefined;
    return desc || undefined;
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
      ref={rootEl}
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
      onMouseEnter={() => props.onHover?.(true)}
      onMouseLeave={() => props.onHover?.(false)}
    >
      <div
        role="button"
        tabIndex={0}
        class={`draft-card ${selected() ? 'active' : ''} ${generating() ? 'animate-pulse' : ''} ${props.dragOver ? 'drag-over' : ''} ${isVoiceCard() ? 'draft-card--voice' : ''}`}
        style={bgStyle()}
        title={cardTitle()}
        onClick={() => studioActions.selectDraft(props.draft.id, props.type)}
        onKeyDown={(e) => e.key === 'Enter' && studioActions.selectDraft(props.draft.id, props.type)}
        onContextMenu={onContextMenu}
      >
      {/* 视频媒体：首帧缩略图 + 类型角标 */}
        <Show when={props.draft.mediaType === 'video' && props.draft.videoUrl && inView()}>
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
        {/* 音频媒体：音符 + 波形标识（音色卡缩小图标） */}
        <Show when={props.draft.mediaType === 'audio'}>
          <div class="draft-card-audio-indicator" title="音频">
            <FiMusic size={isVoiceCard() ? 11 : 15} />
            <div class="draft-card-wave">
              <span /><span /><span /><span /><span />
            </div>
          </div>
        </Show>
        {/* 文字标识（状态标签 + 名称 + 描述）仅在空卡片时显示；有媒体后隐藏；音色卡恒隐藏 */}
        <Show when={!hasMedia() && !isVoiceCard()}>
          <Show when={props.draft.tag}>
            <span
              class="draft-card-tag"
              style={{
                background: props.type === 'shot'
                  ? 'color-mix(in srgb, var(--accent-purple) 85%, transparent)'
                  : 'color-mix(in srgb, var(--accent-blue) 85%, transparent)',
              }}
            >
              {props.draft.tag}
            </span>
          </Show>
          <span class="draft-card-label">
            {props.draft.label}
          </span>
          <Show when={(props.draft.desc ?? '').trim()}>
            <span class="draft-card-desc">{props.draft.desc}</span>
          </Show>
        </Show>
      </div>
      {/* 小标编号：组号-卡序号（拖动排序后自动重排，Agent 可按此定位） */}
      <Show when={props.cardCode}>
        <span class="draft-card-code" title="卡片编号（组号-卡序号），可拖动排序">{props.cardCode}</span>
      </Show>
    </div>
  );
}
