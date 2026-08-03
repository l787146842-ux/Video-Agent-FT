import { createSignal, createEffect } from 'solid-js';

/**
 * 主题切换 Hook
 * 操作 html.dark / html.light class + localStorage 持久化。
 * 兼容旧版 studio.html 的 storage key，保证 iframe 内旧页面
 * （api-settings.html / 画布）通过 storage 事件同步主题。
 */
const STORAGE_KEY = 'ftdyb-theme';
const LEGACY_KEYS = ['studio_theme', 'canvas_theme'];

type Theme = 'dark' | 'light';

function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  for (const key of LEGACY_KEYS) {
    const legacy = localStorage.getItem(key);
    if (legacy === 'light' || legacy === 'dark') return legacy;
  }
  return 'dark'; // 默认暗色
}

const [theme, setTheme] = createSignal<Theme>(getInitialTheme());

createEffect(() => {
  const t = theme();
  const html = document.documentElement;
  html.classList.toggle('dark', t === 'dark');
  html.classList.toggle('light', t === 'light');
  localStorage.setItem(STORAGE_KEY, t);
  // 回写旧 key：同源 iframe 旧页面监听 storage 事件自动换肤
  LEGACY_KEYS.forEach((key) => localStorage.setItem(key, t));
});

export function useTheme() {
  function toggle() {
    // 启用主题过渡动画（250ms 后移除 class，避免影响其他动画）
    document.documentElement.classList.add('theme-transitioning');
    setTimeout(() => document.documentElement.classList.remove('theme-transitioning'), 300);
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }

  return { theme, setTheme, toggle };
}
