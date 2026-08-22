import { createSignal, createEffect, onCleanup, Show } from 'solid-js';
import { FiRefreshCw, FiGrid, FiTrash2, FiNavigation } from 'solid-icons/fi';
import { state, findDraftRecord, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { uploadFiles } from '@/api/upload';
import { safeUrl } from '@/lib/utils';
import type { AllCanvasImageItem } from '@/api/canvas';
import { CanvasImagePickerModal } from './CanvasImagePickerModal';
import { GenTypeTabs } from './GenTypeTabs';
import { PreviewEmpty } from './PreviewEmpty';
import { GenProgress } from './GenProgress';
import { MediaContent } from './MediaContent';
import { PreviewLightbox } from './PreviewLightbox';

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
        <PreviewLightbox url={lightboxUrl()} onClose={() => setLightboxUrl('')} />
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
