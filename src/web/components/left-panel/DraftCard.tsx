import { Show, Switch, Match, createSignal, onMount, onCleanup } from 'solid-js';
import {
  FiCheck, FiCheckCircle, FiImage, FiLogOut, FiMessageSquare, FiMusic, FiTrash2, FiVideo,
  FiVolume2, FiXCircle,
} from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { confirmDialog } from '@/components/shared/ConfirmDialog';
import { checkpointHistory, performUndo } from '@/stores/history';
import { requestInsertMedia, requestInsertText } from '@/lib/chat/chat-input-bridge';
import { draftToInlineMedia } from '@/lib/rich-input';
import { safeUrl } from '@/lib/utils';
import { DraftCardGenRing } from './DraftCardGenRing';
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
  /** 所属分组是否含图片/视频卡（绑定音频「变小」的判定：图5 形态只在图文组内） */
  groupHasVisual?: boolean;
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

  /** 卡片底图地址：图片媒体用 imgUrl；视频尚无 videoUrl 时用 imgUrl 作首帧占位
   *  （与 bgStyle 同一判定，防「有底图又叠占位符号」两层打架） */
  const backdropUrl = () => {
    const d = props.draft;
    const imgUrl = safeUrl(d.imgUrl || '');
    if (!imgUrl) return '';
    if (d.mediaType === 'image') return imgUrl;
    if (d.mediaType === 'video' && !d.videoUrl) return imgUrl;
    return '';
  };

  /** 是否已有可展示的媒体本体（图片底图 / 视频首帧 / 音频文件）：
   *  决定占位符号是否退场与边框实线/虚线（两态分形的唯一判据） */
  const hasVisual = () => {
    const d = props.draft;
    if (d.mediaType === 'audio') return !!d.audioUrl;
    if (d.mediaType === 'video') return !!d.videoUrl || !!backdropUrl();
    return !!backdropUrl();
  };

  const bgStyle = () => {
    const url = backdropUrl();
    if (url) {
      return { 'background-image': `url('${url}')` };
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

  /** 生成失败态：卡面文字已摘除，状态改由非文字信号承载
   *  （危险色窄边 + 危险色占位符号），否则「失败」与「还没生成」视觉上无法区分
   *  ——真实数据里 `生成失败` 卡 11 张，是空卡上原本唯一的状态出口 */
  const failed = () => (props.draft.tag ?? '').trim() === '生成失败';

  /** 关键元素组内的角色音色卡（对齐 flova 小图标子卡）：半尺寸、卡面只留音频符号；
   *  2026-10-26 绑定批：图文组内「已绑定」的音频卡同样缩为小卡（图5 形态），
   *  纯音频组（音频页签）保持原尺寸（用户裁决：仅图文组内）。 */
  const isVoiceCard = () => props.draft.mediaType === 'audio' && (
    props.type === 'keyElement' || (!!props.draft.bound && !!props.groupHasVisual));
  /** 可绑定判定：卡上有任意媒体才允许绑定（空卡无可绑定对象） */
  const hasAnyMedia = () => !!(props.draft.imgUrl || props.draft.videoUrl || props.draft.audioUrl);

  /** 悬停 title：卡面文字已全部摘除，名称+描述都走 title 兜底（信息不丢只换载体）；
   *  生成失败态在 title 头部点明，补足「非文字信号」读不出的语义 */
  const cardTitle = () => {
    const label = (props.draft.label ?? '').trim();
    const desc = (props.draft.desc ?? '').trim();
    const head = failed() ? '生成失败' : '';
    return [head, label, desc].filter(Boolean).join('　') || undefined;
  };

  /** 未生成媒体的占位符号（图片/视频/音频各一，替代原卡面文字，一眼分类型） */
  const placeholderIcon = () => {
    const size = isVoiceCard() ? 11 : 15;
    switch (props.draft.mediaType) {
      case 'video': return <FiVideo size={size} />;
      case 'audio': return <FiVolume2 size={size} />;
      default: return <FiImage size={size} />;
    }
  };

  /** 可访问名称：卡面零文字后，按钮的可读名不能依赖卡面文本（读屏会读成空按钮）；
   *  title 只负责鼠标悬停，aria-label 负责读屏——两者同源不同通道 */
  const cardAriaLabel = () => {
    const label = (props.draft.label ?? '').trim() || '未命名草稿';
    const state = failed() ? '生成失败' : hasVisual() ? '已生成' : '未生成';
    return `${label}（${state}）`;
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

  function toggleBound() {
    const next = !props.draft.bound;
    studioActions.bindDraftLocal(props.type, props.groupId, props.draft.id, next);
    showToast(next ? '已绑定为分组媒体（后续生成只认它）' : '已取消绑定', 'success');
  }

  function onContextMenu(e: MouseEvent) {
    const bindItem = hasAnyMedia()
      ? [{
        label: props.draft.bound ? '取消绑定' : '绑定为分组媒体',
        icon: props.draft.bound ? FiXCircle : FiCheckCircle,
        onClick: toggleBound,
      }]
      : [];
    showContextMenu(e, [
      ...bindItem,
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
        aria-label={cardAriaLabel()}
        class={`draft-card ${selected() ? 'active' : ''} ${generating() ? 'animate-pulse' : ''} ${props.dragOver ? 'drag-over' : ''} ${isVoiceCard() ? 'draft-card--voice' : ''} ${hasVisual() ? 'draft-card--filled' : 'draft-card--empty'} ${failed() ? 'draft-card--failed' : ''}`}
        style={bgStyle()}
        title={cardTitle()}
        onClick={() => studioActions.selectDraftOnCard(props.draft.id, props.type)}
        onKeyDown={(e) => e.key === 'Enter' && studioActions.selectDraftOnCard(props.draft.id, props.type)}
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
        {/* 音频媒体：已生成 → 音符+波形；未生成 → 广播符号占位（图4 口径） */}
        <Show when={props.draft.mediaType === 'audio'}>
          <Switch>
            <Match when={props.draft.audioUrl}>
              <div class="draft-card-audio-indicator" title="音频">
                <FiMusic size={isVoiceCard() ? 11 : 15} />
                <div class="draft-card-wave">
                  <span /><span /><span /><span /><span />
                </div>
              </div>
            </Match>
            <Match when={!props.draft.audioUrl}>
              <div class="draft-card-audio-indicator is-empty" title="音频（未生成）">
                <FiVolume2 size={isVoiceCard() ? 12 : 17} />
              </div>
            </Match>
          </Switch>
        </Show>
        {/* 图片 / 视频未生成：卡面只留类型占位符号（不再渲染名称/描述/状态文字） */}
        <Show when={!hasVisual() && props.draft.mediaType !== 'audio'}>
          <div class="draft-card-placeholder-icon" title="尚未生成">
            {placeholderIcon()}
          </div>
        </Show>
        {/* 生成中读秒环（2026-10-26 用户裁决：左栏卡片与中间预览框同源同形态） */}
        <DraftCardGenRing draft={props.draft} />
        {/* 绑定绿勾（细黑边框保证可见）：该卡媒体为分组同类媒体的采用媒体 */}
        <Show when={props.draft.bound}>
          <span class="draft-card-bound-badge" title="已绑定为分组媒体（后续生成只认它）">
            <FiCheck size={9} />
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
