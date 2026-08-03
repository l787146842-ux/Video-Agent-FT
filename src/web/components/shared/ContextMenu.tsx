import { createSignal, onCleanup, For, Show } from 'solid-js';
import { Dynamic, Portal } from 'solid-js/web';
import type { Component, JSX } from 'solid-js';

/** 右键菜单项 */
export interface ContextMenuItem {
  label: string;
  icon?: Component<{ size?: number | string }>;
  danger?: boolean;
  onClick: () => void;
}

interface MenuPosition {
  x: number;
  y: number;
  items: ContextMenuItem[];
}

const [menu, setMenu] = createSignal<MenuPosition | null>(null);

export function closeContextMenu() {
  setMenu(null);
}

/**
 * 在鼠标位置弹出右键菜单（自动避让视口边缘）
 * 任意组件 onContextMenu={(e) => showContextMenu(e, items)} 即可。
 */
export function showContextMenu(e: MouseEvent, items: ContextMenuItem[]) {
  e.preventDefault();
  e.stopPropagation();
  const menuWidth = 180;
  const menuHeight = items.length * 34 + 12;
  setMenu({
    x: Math.min(e.clientX, window.innerWidth - menuWidth - 8),
    y: Math.min(e.clientY, window.innerHeight - menuHeight - 8),
    items,
  });
}

/** 右键菜单宿主，挂载于 LayoutShell（Portal 渲染到 body） */
export function ContextMenuHost() {
  function onDocMouseDown(e: MouseEvent) {
    const target = e.target as HTMLElement;
    if (!target.closest('[data-context-menu]')) closeContextMenu();
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') closeContextMenu();
  }
  document.addEventListener('mousedown', onDocMouseDown);
  document.addEventListener('keydown', onKeyDown);
  window.addEventListener('blur', closeContextMenu);
  onCleanup(() => {
    document.removeEventListener('mousedown', onDocMouseDown);
    document.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('blur', closeContextMenu);
  });

  return (
    <Show when={menu()}>
      {(m) => (
        <Portal>
          <div
            data-context-menu
            class="context-menu"
            style={{ left: `${m().x}px`, top: `${m().y}px` } as JSX.CSSProperties}
          >
            <For each={m().items}>
              {(item) => (
                <button
                  type="button"
                  class={`context-menu-item ${item.danger ? 'danger' : ''}`}
                  onClick={() => {
                    closeContextMenu();
                    item.onClick();
                  }}
                >
                  <Show when={item.icon}>
                    <Dynamic component={item.icon} size={13} />
                  </Show>
                  <span>{item.label}</span>
                </button>
              )}
            </For>
          </div>
        </Portal>
      )}
    </Show>
  );
}
