/**
 * 参考素材上传工具：上传一个媒体文件并加入草稿参考素材栏（去重 + 上限校验）。
 * 参考栏自身上传与提示词框粘贴/拖入共用。
 */
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { uploadFiles } from '@/api/upload';
import type { DraftRecord } from '@/types';

export async function uploadRefFile(
  rec: DraftRecord | undefined,
  maxRefs: number,
  file: File,
): Promise<void> {
  if (!rec) return;
  const refs = rec.draft.refAssets || [];
  if (refs.length >= maxRefs) {
    showToast(`参考素材最多 ${maxRefs} 个，请先删除再添加`, 'warning');
    return;
  }
  showToast(`正在上传：${file.name}`, 'info');
  const files = await uploadFiles([file]);
  const url = files[0]?.url;
  if (!url) throw new Error('上传接口没有返回素材地址');
  if (refs.includes(url)) {
    showToast('该素材已在参考列表中', 'warning');
    return;
  }
  studioActions.updateDraftLocal(rec.type, rec.draft.id, { refAssets: [...refs, url] });
  showToast(`已添加参考素材：${file.name}`, 'success');
}
