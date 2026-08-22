import { createEffect, onCleanup } from 'solid-js';

/**
 * 共享焦点圈闭（无障碍：弹层焦点管理）：
 * Modal/Picker 弹层统一接入——打开时圈闭焦点（Tab 循环不外逃）、
 * Esc 触发关闭回调、关闭后焦点还原到打开前的元素。
 *
 * 用法（组件内）：
 *   const [panelEl, setPanelEl] = createSignal<HTMLElement>();
 *   // 注意：<Show> 卸载后 ref 信号残留旧元素，容器须随 open 状态置空
 *   useFocusTrap(() => (props.open ? panelEl() : undefined), { onEscape: () => props.onClose() });
 *   <div ref={setPanelEl} role="dialog" aria-modal="true" aria-label="…">…</div>
 *
 * 嵌套弹层（如 Picker 之上再开确认框）走内部栈：只有栈顶圈闭
 * 拦截 Tab/Esc 与焦点回拉，底层圈闭不抢焦点。
 */

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** 活动中的圈闭栈（后打开的在栈顶；只有栈顶负责拦截） */
const trapStack: HTMLElement[] = [];

/** 取容器内可聚焦元素（隐藏控件按 tabindex=-1 约定排除，不做几何测量） */
export function getFocusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((el) => el.getAttribute('aria-hidden') !== 'true');
}

export interface FocusTrapOptions {
  /** Esc 关闭回调；未提供则不拦截 Esc */
  onEscape?: () => void;
  /** 关闭时是否把焦点还给打开前的元素（默认 true） */
  restoreFocus?: boolean;
  /** 打开时优先聚焦的元素；缺省取第一个可聚焦元素 */
  initialFocus?: () => HTMLElement | undefined;
}

/**
 * 在组件作用域内启用焦点圈闭：container() 非空时激活，
 * 元素卸载（<Show> 关闭）时自动清理并还原焦点。
 */
export function useFocusTrap(
  container: () => HTMLElement | undefined,
  opts: FocusTrapOptions = {},
): void {
  let prevFocused: HTMLElement | null = null;

  createEffect(() => {
    const maybeRoot = container();
    if (!maybeRoot) return;
    const root: HTMLElement = maybeRoot; // 显式常量：嵌套回调内窄化不丢失
    prevFocused = (document.activeElement as HTMLElement) || null;
    trapStack.push(root);

    // 移入焦点：优先指定元素 → 第一个可聚焦 → 容器自身
    const first = opts.initialFocus?.() || getFocusable(root)[0];
    if (first) {
      first.focus();
    } else {
      root.setAttribute('tabindex', '-1');
      root.focus();
    }

    function isTop(): boolean {
      return trapStack[trapStack.length - 1] === root;
    }

    function onKeyDown(e: KeyboardEvent) {
      if (!isTop()) return;
      if (e.key === 'Escape') {
        if (opts.onEscape) {
          e.preventDefault();
          e.stopPropagation();
          opts.onEscape();
        }
        return;
      }
      if (e.key !== 'Tab') return;
      const items = getFocusable(root);
      if (!items.length) { e.preventDefault(); return; }
      const active = document.activeElement as HTMLElement | null;
      const idx = active ? items.indexOf(active) : -1;
      if (e.shiftKey) {
        if (idx <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
      } else if (idx === items.length - 1 || idx < 0) {
        e.preventDefault();
        items[0].focus();
      }
    }

    // 焦点逃到圈闭外（Tab 到浏览器 UI 再回来等）时拉回首项
    function onFocusIn(e: FocusEvent) {
      if (!isTop()) return;
      const target = e.target as Node | null;
      if (target && !root.contains(target)) {
        const items = getFocusable(root);
        (items[0] || root).focus();
      }
    }

    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('focusin', onFocusIn);
    onCleanup(() => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('focusin', onFocusIn);
      const at = trapStack.indexOf(root);
      if (at >= 0) trapStack.splice(at, 1);
      if ((opts.restoreFocus ?? true) && prevFocused?.focus) {
        prevFocused.focus();
      }
    });
  });
}
