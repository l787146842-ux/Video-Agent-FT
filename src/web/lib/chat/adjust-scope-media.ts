/**
 * 微调子对话浮窗素材摄取（二期子对话批 3）：一期只开图片/视频/音频，
 * 文档类型在入口直接拒绝（后端白名单 + 口径沿用 /api/ai/upload）。
 * 上传经 uploadFiles 复用主链路；产出引用条目暂存线程 pendingRefs，
 * 随 sendAdjust 携带后端绑线程（不进全局 assets，主对话零污染）。
 */
import { uploadFiles } from '@/api/upload';
import { showToast } from '@/stores/toast';
import { uid } from '../utils';
import { t } from '../locale';
import type { ScopeRef } from '@/stores/adjust-scope-events';

/** 入口类型闸：仅图片/视频/音频（文档类前端即拒，不打上传接口） */
function isMediaFile(f: File): boolean {
  return f.type.startsWith('image/') || f.type.startsWith('video/') || f.type.startsWith('audio/');
}

/** 批量上传 → 引用条目（非媒体类当场拒并提示；单项失败不阻塞其余） */
export async function uploadScopeRefs(files: File[]): Promise<ScopeRef[]> {
  const accepted = files.filter((f) => {
    if (isMediaFile(f)) return true;
    showToast(t('rp.adjust.docRejected'), 'warning');
    return false;
  });
  if (!accepted.length) return [];
  try {
    const uploaded = await uploadFiles(accepted);
    return uploaded
      .filter((u) => u.url && (u.kind === 'image' || u.kind === 'video' || u.kind === 'audio'))
      .map((u) => ({ id: uid('sref'), name: u.name || u.url, kind: u.kind, url: u.url }));
  } catch (e) {
    showToast((e as Error).message || t('rp.adjust.uploadFailed'), 'error');
    return [];
  }
}

/** 输入框粘贴图片 → 引用条目（仅直接图片项；复用剪贴板 File 口径） */
export async function pasteScopeRefs(e: ClipboardEvent): Promise<ScopeRef[]> {
  const items = e.clipboardData?.items;
  if (!items) return [];
  const files: File[] = [];
  for (let i = 0; i < items.length; i++) {
    if (!items[i].type.startsWith('image/')) continue;
    const f = items[i].getAsFile();
    if (f) files.push(f);
  }
  if (!files.length) return [];
  e.preventDefault();
  return uploadScopeRefs(files);
}
