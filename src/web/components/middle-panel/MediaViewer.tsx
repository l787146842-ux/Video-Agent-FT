import {
  createSignal, createEffect, onCleanup, Show, Switch, Match,
} from 'solid-js';
import { FiRefreshCw, FiGrid, FiX, FiZoomIn } from 'solid-icons/fi';
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
          <video src={props.url} controls />
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

  function onContextMenu(e: MouseEvent) {
    showContextMenu(e, [
      { label: '替换媒体文件', icon: FiRefreshCw, onClick: triggerUpload },
      { label: '导入画布内的图片', icon: FiGrid, onClick: () => setPickerOpen(true) },
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
        {/* 生成中优先显示进度环（不改动已有媒体）；否则显示已有媒体或空态 */}
        <Show when={genRec()} fallback={
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

      {/* 图片放大查看 lightbox（支持滚轮缩放） */}
      <Show when={lightboxUrl()}>
        {(() => {
          const [zoom, setZoom] = createSignal(1);
          return (
            <div
              class="preview-lightbox"
              onClick={() => { setLightboxUrl(''); setZoom(1); }}
              onWheel={(e) => {
                e.preventDefault();
                setZoom((z) => Math.min(5, Math.max(0.2, z - e.deltaY * 0.001)));
              }}
            >
              <img
                src={lightboxUrl()}
                alt="放大预览"
                class="preview-lightbox-img"
                style={{ transform: `scale(${zoom()})` }}
                onClick={(e) => e.stopPropagation()}
              />
              <span class="preview-lightbox-zoom">{Math.round(zoom() * 100)}%</span>
              <button
                type="button"
                class="preview-lightbox-close"
                onClick={() => { setLightboxUrl(''); setZoom(1); }}
                title="关闭 (Esc)"
              >
                <FiX size={20} />
              </button>
            </div>
          );
        })()}
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
