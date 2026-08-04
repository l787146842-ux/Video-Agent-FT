/* eslint-disable max-lines -- 新增删除媒体后超行，待后续拆分；新增代码仍受规则约束 */
import {
  createSignal, createEffect, onCleanup, Show, Switch, Match,
} from 'solid-js';
import { FiRefreshCw, FiGrid, FiX, FiTrash2, FiNavigation } from 'solid-icons/fi';
import { state, findDraftRecord, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { uploadFiles } from '@/api/upload';
import { safeUrl } from '@/lib/utils';
import type { Draft, ActiveGeneration } from '@/types';
import type { AllCanvasImageItem } from '@/api/canvas';
import { CanvasImagePickerModal } from './CanvasImagePickerModal';
import { GenTypeTabs } from './GenTypeTabs';

/* ===== 子组件：空态 ===== */
function PreviewEmpty(props: { hint?: string }) {
  return (
    <div class="preview-empty">
      <p class="preview-empty-icon">🎬</p>
      <p>{props.hint || '暂无媒体预览'}</p>
      <p class="preview-empty-hint">双击或拖拽上传，右键可替换媒体</p>
    </div>
  );
}

/* ===== 子组件：生成进度环 ===== */
function GenProgress(props: { gen: ActiveGeneration; elapsed: number }) {
  const ringOffset = () => 251.2 * (1 - (props.elapsed % 60) / 60);
  return (
    <div class="gen-progress">
      <div class="gen-progress-ring">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" stroke="#2b3149" stroke-width="8" />
          <circle
            cx="50" cy="50" r="40" fill="none" stroke="#3b82f6" stroke-width="8"
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

/* ===== 子组件：媒体内容（按类型切换） ===== */
function MediaContent(props: { draft: Draft; url: string; onImageClick?: () => void }) {
  return (
    <div class="preview-media-viewer">
      <Switch fallback={
        <img
          src={props.url}
          alt={props.draft.label}
          class="preview-img-clickable"
          onClick={props.onImageClick}
          title="点击放大查看"
        />
      }>
        <Match when={props.draft.mediaType === 'video'}>
          {/* preload=metadata：切卡片时只加载首帧/元数据，避免每次点卡片
              都后台全量下载视频（大文件时会明显卡顿）；点击播放时照常加载 */}
          <video src={props.url} controls preload="metadata" />
        </Match>
        <Match when={props.draft.mediaType === 'audio'}>
          <div class="preview-audio-wrap">
            <p class="preview-audio-name">{props.draft.label}</p>
            <audio src={props.url} controls />
          </div>
        </Match>
      </Switch>
    </div>
  );
}

/**
 * 预览媒体区：图片 / 视频 / 音频 / 空态 / 生成中进度环
 * 交互：双击或拖拽上传替换媒体；右键弹出替换菜单。
 */
export function MediaViewer() {
  const [dragOver, setDragOver] = createSignal(false);
  const [elapsed, setElapsed] = createSignal(0);
  const [pickerOpen, setPickerOpen] = createSignal(false);
  const [lightboxUrl, setLightboxUrl] = createSignal('');

  const rec = () => findDraftRecord(state.selectedDraftId, state.selectedType);
  const draft = () => rec()?.draft;
  const genRec = () => state.activeGenerations[state.selectedDraftId];

  // 生成中秒表（200ms 刷新）
  createEffect(() => {
    const gen = genRec();
    if (!gen) return;
    setElapsed((Date.now() - gen.start) / 1000);
    const timer = setInterval(
      () => setElapsed((Date.now() - gen.start) / 1000),
      200,
    );
    onCleanup(() => clearInterval(timer));
  });

  const mediaUrl = () => {
    const d = draft();
    if (!d) return '';
    if (d.mediaType === 'video') return safeUrl(d.videoUrl || '');
    if (d.mediaType === 'audio') return safeUrl(d.audioUrl || '');
    return safeUrl(d.imgUrl || '');
  };

  // 空态提示文案：按当前存储的媒体类型（mediaType）区分
  const emptyHint = () => {
    const mt = draft()?.mediaType;
    if (mt === 'video') return '暂无视频预览';
    if (mt === 'audio') return '暂无音频预览';
    if (state.selectedType === 'shot') return '暂无视频预览';
    return '暂无媒体预览';
  };

  // ===== 上传替换 =====
  async function handleUpload(file: File) {
    if (!state.selectedDraftId) {
      showToast('请先在左侧选择一个草稿卡片', 'warning');
      return;
    }
    try {
      showToast(`正在上传：${file.name}`, 'info');
      const files = await uploadFiles([file]);
      const uploaded = files[0];
      const current = rec();
      if (!uploaded?.url || !current) throw new Error('上传接口没有返回媒体地址');
      const { draft: d, type } = current;
      const kind = uploaded.kind || 'image';
      // 一张卡片只存一个媒体：覆盖同类型 URL 并清空其他类型，同步生成标签
      const patch = kind === 'video'
        ? { mediaType: 'video' as const, genType: 'video' as const, videoUrl: uploaded.url, imgUrl: '', audioUrl: '', tag: '已上传' }
        : kind === 'audio'
          ? { mediaType: 'audio' as const, genType: 'audio' as const, audioUrl: uploaded.url, imgUrl: '', videoUrl: '', tag: '已上传' }
          : { mediaType: 'image' as const, genType: 'image' as const, imgUrl: uploaded.url, videoUrl: '', audioUrl: '', tag: '已上传' };
      studioActions.updateDraftLocal(type, d.id, patch);
      showToast(`已替换媒体：${uploaded.name || file.name}`, 'success');
    } catch (e) {
      showToast((e as Error).message || '媒体上传失败', 'error');
    }
  }

  function triggerUpload() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*,video/*,audio/*';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (file) await handleUpload(file);
    };
    input.click();
  }

  /** 删除当前预览媒体（清空图片/视频/音频地址，保留提示词与参数） */
  function deleteMedia() {
    const current = rec();
    if (!current) {
      showToast('请先在左侧选择一个草稿卡片', 'warning');
      return;
    }
    const { draft: d, type } = current;
    if (!d.imgUrl && !d.videoUrl && !d.audioUrl) {
      showToast('当前草稿没有可删除的媒体', 'warning');
      return;
    }
    studioActions.updateDraftLocal(type, d.id, { imgUrl: '', videoUrl: '', audioUrl: '' });
    showToast(`已删除「${d.label || '草稿'}」的媒体（Ctrl+Z 可撤销）`, 'success');
  }

  function onContextMenu(e: MouseEvent) {
    showContextMenu(e, [
      { label: '替换媒体文件', icon: FiRefreshCw, onClick: triggerUpload },
      { label: '导入画布内的图片', icon: FiGrid, onClick: () => setPickerOpen(true) },
      { label: '删除媒体', icon: FiTrash2, danger: true, onClick: deleteMedia },
    ]);
  }

  /** 从画布导入图片到当前预览 */
  function handleCanvasPick(item: AllCanvasImageItem) {
    const current = rec();
    if (!current) {
      showToast('请先在左侧选择一个草稿卡片', 'warning');
      return;
    }
    const { draft: d, type } = current;
    studioActions.updateDraftLocal(type, d.id, {
      mediaType: 'image',
      genType: 'image',
      imgUrl: item.url,
      videoUrl: '',
      audioUrl: '',
      tag: '画布导入',
    });
    showToast(`已导入：${item.name}`, 'success');
  }

  return (
    <div
      class={`preview-top ${dragOver() ? 'preview-dragover' : ''}`}
      onDblClick={triggerUpload}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer?.files?.[0];
        if (file) void handleUpload(file);
      }}
      onContextMenu={onContextMenu}
    >
      {/* 关键元素面板：图片/视频/音频 生成类型切换标签 */}
      <Show when={state.selectedType === 'keyElement' && draft()}>
        <GenTypeTabs />
      </Show>
      <Show when={draft()} fallback={
        <div class="preview-empty">
          <p class="preview-empty-icon">🎬</p>
          <p>选择左侧草稿卡片开始创作</p>
        </div>
      }>
        {/* 生成中且尚未出图：显示进度环；已出图（含刷新恢复/写回先于收尾）：优先显示媒体 */}
        <Show when={genRec() && !mediaUrl()} fallback={
          <Show when={mediaUrl()} fallback={
            <PreviewEmpty hint={emptyHint()} />
          }>
            <MediaContent
              draft={draft()!}
              url={mediaUrl()}
              onImageClick={() => setLightboxUrl(mediaUrl())}
            />
          </Show>
        }>
          <GenProgress gen={genRec()!} elapsed={elapsed()} />
        </Show>
      </Show>

      {/* 图片放大查看 lightbox（支持滚轮缩放 + 鼠标按住拖拽平移） */}
      <Show when={lightboxUrl()}>
        {(() => {
          const [zoom, setZoom] = createSignal(1);
          const [pan, setPan] = createSignal({ x: 0, y: 0 });
          const [dragging, setDragging] = createSignal(false);
          let startX = 0;
          let startY = 0;
          let baseX = 0;
          let baseY = 0;

          const closeLightbox = () => {
            setLightboxUrl('');
            setZoom(1);
            setPan({ x: 0, y: 0 });
          };

          /** 按住图片拖动：上下左右平移（window 级监听，拖出图片不丢手势） */
          function onImgMouseDown(e: MouseEvent) {
            e.preventDefault();
            e.stopPropagation();
            setDragging(true);
            startX = e.clientX;
            startY = e.clientY;
            baseX = pan().x;
            baseY = pan().y;
            const onMove = (ev: MouseEvent) => {
              setPan({ x: baseX + (ev.clientX - startX), y: baseY + (ev.clientY - startY) });
            };
            const onUp = () => {
              setDragging(false);
              window.removeEventListener('mousemove', onMove);
              window.removeEventListener('mouseup', onUp);
            };
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
          }

          return (
            <div
              class="preview-lightbox"
              onClick={() => closeLightbox()}
              onWheel={(e) => {
                e.preventDefault();
                setZoom((z) => Math.min(5, Math.max(0.2, z - e.deltaY * 0.001)));
              }}
            >
              <img
                src={lightboxUrl()}
                alt="放大预览"
                class={`preview-lightbox-img ${dragging() ? 'preview-lightbox-img-dragging' : ''}`}
                style={{ transform: `translate(${pan().x}px, ${pan().y}px) scale(${zoom()})` }}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={onImgMouseDown}
                title="按住拖动移动，滚轮缩放"
              />
              <span class="preview-lightbox-zoom">{Math.round(zoom() * 100)}%</span>
              <button
                type="button"
                class="preview-lightbox-close"
                onClick={() => closeLightbox()}
                title="关闭 (Esc)"
              >
                <FiX size={20} />
              </button>
            </div>
          );
        })()}
      </Show>

      {/* 导航定位按钮（右下角）：左面板自动定位到当前预览对应的
          关键元素/分镜/音频页签及卡片（选中态 + 滚动高亮） */}
      <Show when={draft()}>
        <button
          type="button"
          class="preview-locate-btn"
          title="在左侧故事板中定位当前预览卡片"
          onClick={() => studioActions.locateSelectedInBoard()}
          onDblClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => e.stopPropagation()}
        >
          <FiNavigation size={15} />
        </button>
      </Show>

      {/* 画布图片导入弹窗 */}
      <CanvasImagePickerModal
        open={pickerOpen()}
        onClose={() => setPickerOpen(false)}
        onPick={handleCanvasPick}
      />
    </div>
  );
}
