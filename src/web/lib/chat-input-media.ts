/**
 * 聊天输入框的媒体摄取逻辑：粘贴 / 拖拽 / 上传。
 * 统一把图片·视频·音频转为内联缩略块（经 insertMedia 回调插入光标处），
 * 文档类走附件 chip。从 ChatInput 拆出以保持主组件精简。
 */
import { uploadFiles } from '@/api/upload';
import { studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { uid } from './utils';
import type { InlineMedia } from '@/types';

export type InsertMedia = (media: InlineMedia) => void;

/** URL → 图片内联媒体对象 */
export function imageMediaFromUrl(url: string, name?: string): InlineMedia {
  const fname = name || url.split('/').pop()?.split('?')[0] || 'clipboard-image.png';
  return { id: uid('im'), name: fname, url, kind: 'image', thumb: url };
}

/** 上传文件：媒体 → 内联缩略块（insertMedia）；文档 → 附件 chip */
export async function uploadAndInsert(file: File, insertMedia: InsertMedia): Promise<void> {
  try {
    showToast(`正在上传：${file.name}`, 'info');
    const files = await uploadFiles([file]);
    const uploaded = files[0];
    if (!uploaded?.url) throw new Error('上传接口没有返回素材地址');
    const kind = uploaded.kind || 'doc';
    const name = uploaded.name || file.name;
    if (kind === 'image' || kind === 'video' || kind === 'audio') {
      insertMedia({ id: uid('im'), name, url: uploaded.url, kind, thumb: uploaded.url });
    } else {
      studioActions.addPendingAttachment({ id: uid('ast'), name, type: kind, url: uploaded.url });
    }
    // 发送前只是放进输入框，随下一条消息发送才真正附加给 Agent，文案不能误导为「已添加」
    showToast(`已放入输入框：${name}，发送消息时一并附加`, 'success');
  } catch (e) {
    showToast((e as Error).message || '素材上传失败', 'error');
  }
}

/** 解析粘贴内容中的图片（剪贴板 File 或 HTML <img>）并插入 */
export async function handlePasteImages(e: ClipboardEvent, insertMedia: InsertMedia): Promise<void> {
  const items = e.clipboardData?.items;
  if (!items) return;
  const imageItems: DataTransferItem[] = [];
  const htmlItems: DataTransferItem[] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.type.startsWith('image/')) imageItems.push(item);
    else if (item.type === 'text/html') htmlItems.push(item);
  }
  if (imageItems.length > 0) {
    e.preventDefault();
    for (const item of imageItems) {
      const file = item.getAsFile();
      if (file) await uploadAndInsert(file, insertMedia);
    }
    return;
  }
  // 没有直接图片，但可能有 HTML 中的 <img>（比如从浏览器复制图片）
  if (htmlItems.length > 0) {
    const htmlResults: string[] = [];
    for (const item of htmlItems) {
      await new Promise<void>((resolve) => {
        item.getAsString((html) => { htmlResults.push(html); resolve(); });
      });
    }
    const imgSrcRe = /<img[^>]+src=["']([^"']+)["']/gi;
    const urls: string[] = [];
    let m;
    while ((m = imgSrcRe.exec(htmlResults.join(''))) !== null) {
      if (m[1] && !m[1].startsWith('data:')) urls.push(m[1]);
    }
    if (urls.length > 0) {
      e.preventDefault();
      urls.forEach((url) => insertMedia(imageMediaFromUrl(url)));
      showToast(`已放入输入框 ${urls.length} 张图片，发送消息时一并附加`, 'success');
    }
  }
}

/** 解析拖入的图片链接（text/uri-list、text/html、图片地址文本）→ 插入；返回是否已处理 */
export function handleUrlDrop(dt: DataTransfer, insertMedia: InsertMedia): boolean {
  const urls: string[] = [];
  const uriList = dt.getData('text/uri-list');
  if (uriList) {
    uriList.split('\n').forEach((line) => {
      const u = line.trim();
      if (u && !u.startsWith('#') && /^https?:\/\//i.test(u)) urls.push(u);
    });
  }
  if (urls.length === 0) {
    const html = dt.getData('text/html');
    if (html) {
      const imgSrcRe = /<img[^>]+src=["']([^"']+)["']/gi;
      let m;
      while ((m = imgSrcRe.exec(html)) !== null) {
        if (m[1] && !m[1].startsWith('data:')) urls.push(m[1]);
      }
    }
  }
  if (urls.length === 0) {
    const text = dt.getData('text/plain').trim();
    if (/^https?:\/\/.+\.(png|jpe?g|webp|gif|bmp)(\?.*)?$/i.test(text)) urls.push(text);
  }
  if (urls.length === 0) return false;
  urls.slice(0, 8).forEach((url) => insertMedia(imageMediaFromUrl(url)));
  showToast(`已放入输入框 ${urls.length} 张图片，发送消息时一并附加`, 'success');
  return true;
}
