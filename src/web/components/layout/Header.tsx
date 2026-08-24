import { A, useLocation } from '@solidjs/router';
import { Show } from 'solid-js';
import {
  FiChevronUp, FiCornerUpLeft, FiCornerUpRight, FiFeather, FiList, FiMoon, FiSettings, FiSun,
} from 'solid-icons/fi';
import { useTheme } from '@/hooks/use-theme';
import { ProjectSwitcher } from './ProjectSwitcher';
import {
  historyState, performRedo, performUndo,
} from '@/stores/history';
import { toggleGenLog, genLogUnread } from '@/stores/generation-log';

/**
 * 顶栏「全局设置」入口（替代旧自动切换按钮）：
 * 全局模型选择设置页（出图/出视频模型、分辨率、分镜最大时长、聊天出图开关、自动切换开关）。
 */
function FallbackToggleEntry() {
  return (
    <A
      href="/global-settings"
      class="fallback-toggle"
      title="全局模型选择设置（出图/出视频模型、分辨率、分镜最大时长、自动切换）"
      aria-label="全局模型选择设置"
    >
      <FiSettings size={12} />
      <span class="fallback-toggle-label">全局设置</span>
    </A>
  );
}

/**
 * 全局 Header：品牌 Logo + 模式导航（URL 路由）+ 主题切换 + 项目切换
 * 画布 / API 配置 是 SPA 路由入口（带下拉/切换语义），影视工作台是主页面（无下拉）
 *
 * Header 内部底部居中位置有一个收放箭头，仅在画布 / API 配置模式可见。
 * - header 显示时：箭头绝对定位"骑"在 header 底部边缘下方（导航栏中下方）
 * - header 隐藏时：箭头由 LayoutShell 单独渲染一个 fixed 版本（Header 不渲染）
 */
export function Header(props: {
  /** 覆盖层模式（画布 / API 配置）才显示收放箭头 */
  overlayMode: boolean;
  /** 切换导航栏显隐（箭头点击回调） */
  onToggleHeader: () => void;
}) {
  const { theme, toggle } = useTheme();
  const location = useLocation();

  /** 导航项样式：/ 精确匹配，其余前缀匹配 */
  function navClass(path: string, exact = false): string {
    const active = exact
      ? location.pathname === path
      : location.pathname.startsWith(path);
    return active ? 'mode-btn active' : 'mode-btn';
  }

  return (
    <header class="studio-header">
      {/* 品牌 */}
      <div class="studio-brand">
        <svg class="brand-star" width="22" height="22" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 2l2.9 6.26L21.5 9.27l-4.75 4.28L18.18 20 12 16.77 5.82 20l1.43-6.45L2.5 9.27l6.6-1.01L12 2z"
            fill="url(#brandStarGrad)"
            style={{ stroke: 'var(--color-brand-gold-deep)' }}
            stroke-width="0.5"
          />
          <defs>
            <linearGradient id="brandStarGrad" x1="2" y1="2" x2="22" y2="22">
              <stop offset="0%" style={{ 'stop-color': 'var(--color-brand-gold)' }} />
              <stop offset="100%" style={{ 'stop-color': 'var(--color-brand-flame)' }} />
            </linearGradient>
          </defs>
        </svg>
        <span class="brand-name brand-art">飞天</span>
      </div>

      {/* 模式导航（URL 路由，支持前进/后退/深链接）。三个按钮样式统一，无下拉。 */}
      <nav class="studio-nav-links">
        <A href="/" class={navClass('/', true)}>影视工作台</A>
        <A href="/canvas" class={navClass('/canvas')}>画布</A>
        <A href="/settings" class={navClass('/settings')}>API 配置</A>
      </nav>

      {/* 右侧操作区 */}
      <div class="studio-header-actions">
        {/* Skill 工作台入口：创建/编辑/加入 Skill（三栏页面） */}
        <A
          href="/skills"
          class={`theme-toggle-btn ${location.pathname.startsWith('/skills') ? 'active' : ''}`}
          title="Skill 工作台"
          aria-label="Skill 工作台"
        >
          <FiFeather size={16} />
        </A>
        {/* 生成日志入口：图/视频/音频每次生成的成败记录（照搬画布日志） */}
        <button
          type="button"
          class="theme-toggle-btn genlog-entry"
          title="生成日志"
          aria-label="生成日志"
          onClick={() => toggleGenLog()}
        >
          <FiList size={16} />
          <Show when={genLogUnread() > 0}>
            <span class="genlog-unread">{genLogUnread() > 99 ? '99+' : genLogUnread()}</span>
          </Show>
        </button>
        <button
          type="button"
          class="theme-toggle-btn"
          title="撤销 (Ctrl+Z)"
          aria-label="撤销"
          disabled={!historyState.canUndo}
          onClick={() => void performUndo()}
        >
          <FiCornerUpLeft size={16} />
        </button>
        <button
          type="button"
          class="theme-toggle-btn"
          title="重做 (Ctrl+Y)"
          aria-label="重做"
          disabled={!historyState.canRedo}
          onClick={() => void performRedo()}
        >
          <FiCornerUpRight size={16} />
        </button>
        <button
          type="button"
          class="theme-toggle-btn"
          title="切换主题"
          onClick={toggle}
        >
          {theme() === 'dark' ? <FiMoon size={16} /> : <FiSun size={16} />}
        </button>
        <FallbackToggleEntry />
        <ProjectSwitcher />
      </div>

      {/* 导航栏中下方的收放箭头：仅覆盖层模式可见
         绝对定位"骑"在 header 底部边缘下方（视觉上是导航栏中下方居中） */}
      <Show when={props.overlayMode}>
        <button
          type="button"
          class="nav-toggle-arrow"
          title="收放导航栏"
          onClick={() => props.onToggleHeader()}
        >
          <FiChevronUp size={14} />
        </button>
      </Show>
    </header>
  );
}
