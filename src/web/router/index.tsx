import { Router, Route } from '@solidjs/router';
import { lazy } from 'solid-js';
import { LayoutShell } from '@/components/layout/LayoutShell';

/**
 * 路由定义
 *  /         → Agent 模式（三栏布局）
 *  /canvas   → 画布模式（iframe 嵌入）
 *  /settings → API 配置（iframe 嵌入旧设置页，后期独立迁移）
 *
 * 页面组件懒加载：首屏仅下载 Agent 布局 chunk，其余按需。
 */
const AgentLayout = lazy(() => import('@/components/layout/AgentLayout'));
const CanvasView = lazy(() => import('@/components/layout/CanvasView'));
const SettingsView = lazy(() => import('@/components/layout/SettingsView'));

export function AppRouter() {
  return (
    <Router root={LayoutShell}>
      <Route path="/" component={AgentLayout} />
      <Route path="/canvas" component={CanvasView} />
      <Route path="/settings" component={SettingsView} />
      <Route path="*" component={AgentLayout} />
    </Router>
  );
}
