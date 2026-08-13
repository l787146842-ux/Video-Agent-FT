/**
 * 提示词框媒体粘贴/拖入 hook（从 PromptEditor.tsx 拆出）：
 * 粘贴或拖入媒体文件（图片/视频/音频）时逐个上传进参考素材栏，
 * 不插入提示词文本；拖入期间提供高亮态。
 */
import { createSignal } from 'solid-js';
import { showToast } from '@/stores/toast';
import { uploadRefFile } from '@/lib/ref-upload';
import type { DraftRecord } from '@/types';

/** 是否可放入参考栏的媒体文件（图片/视频/音频；type 缺失时按扩展名兜底） */
export function isMediaFile(f: File): boolean {
  if (/^(image|video|audio)\//.test(f.type)) return true;
  return /\.(png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v|mp3|wav|ogg|m4a|flac|aac)$/i.test(f.name);
}

export function usePromptMediaDrop(opts: {
  rec: () => DraftRecord | undefined;
  maxRefs: () => number;
}) {
  /** 拖入媒体文件时的高亮态 */
  const [dragOver, setDragOver] = createSignal(false);

  /** 逐个上传进参考素材栏（上限/去重由 uploadRefFile 校验） */
  async function addFiles(files: File[]) {
    for (const f of files) {
      try {
        await uploadRefFile(opts.rec(), opts.maxRefs(), f);
      } catch (e) {
        showToast((e as Error).message || '参考素材上传失败', 'error');
      }
    }
  }

  /** paste 事件提取媒体文件（命中时阻止默认，返回待上传列表） */
  function handlePaste(e: ClipboardEvent): File[] {
    const files = Array.from(e.clipboardData?.files || []).filter(isMediaFile);
    if (files.length) e.preventDefault();
    return files;
  }

  function onDragOver(e: DragEvent) {
    if (Array.from(e.dataTransfer?.types || []).includes('Files')) {
      e.preventDefault();
      setDragOver(true);
    }
  }

  function onDragLeave() {
    setDragOver(false);
  }

  /** drop 事件提取媒体文件（命中时阻止默认并取消高亮） */
  function onDrop(e: DragEvent): File[] {
    const files = Array.from(e.dataTransfer?.files || []).filter(isMediaFile);
    if (!files.length) return [];
    e.preventDefault();
    setDragOver(false);
    return files;
  }

  return { dragOver, addFiles, handlePaste, onDragOver, onDragLeave, onDrop };
}
