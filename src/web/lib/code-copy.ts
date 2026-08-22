/**
 * 代码块复制：事件委托式复制按钮。
 *
 * 流式气泡每 120ms 重刷 innerHTML，直接绑定的监听器会随节点销毁丢失，
 * 因此复制交互走容器级事件委托（onClick={handleCodeBlockClick}），
 * 节点怎么重建都能响应。反馈用按钮内联文案（不打扰：不弹成功 toast），
 * 失败才走 toast 提示手动复制。
 */
import { t } from '@/lib/locale';
import { showToast } from '@/stores/toast';

/** 写剪贴板：优先 Clipboard API，不可用时回落 execCommand（旧浏览器/非安全上下文） */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* 落入 execCommand 回落 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** 取代码块纯文本（textContent 天然还原 html:false 转义前的源码） */
function codeTextOf(btn: HTMLElement): string {
  const code = btn.closest('.md-codeblock')?.querySelector('pre code');
  return code?.textContent ?? '';
}

/**
 * 容器级点击委托：命中 .md-codeblock-copy 才动作。
 * 返回 Promise 便于测试 await；组件侧直接作为 onClick 使用。
 */
export async function handleCodeBlockClick(e: MouseEvent): Promise<void> {
  const target = e.target as HTMLElement | null;
  const btn = target?.closest?.('.md-codeblock-copy') as HTMLButtonElement | null;
  if (!btn) return;
  const ok = await copyText(codeTextOf(btn));
  if (!ok) {
    showToast(t('rp.code.copyFailed'), 'warning');
    return;
  }
  // 内联反馈：文案切换 + 成功色，1.6s 后还原；重复点击重置计时
  const label = t('rp.code.copied');
  const restore = t('rp.code.copy');
  btn.textContent = label;
  btn.classList.add('is-done');
  if (btn.dataset.copyTimer) clearTimeout(Number(btn.dataset.copyTimer));
  btn.dataset.copyTimer = String(setTimeout(() => {
    btn.textContent = restore;
    btn.classList.remove('is-done');
    delete btn.dataset.copyTimer;
  }, 1600));
}
