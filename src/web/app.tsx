import { render } from 'solid-js/web';
import { MetaProvider } from '@solidjs/meta';
import './styles/app.css';
import { AppRouter } from './router';
import { AppErrorBoundary } from './components/shared/ErrorBoundary';
import { HealthBanner } from './components/shared/HealthBanner';

declare const __BUILD_ID__: string;
// 启动即打印构建时间：用户反馈前端异常时，先核对浏览器跑的是否最新构建
// eslint-disable-next-line no-console -- 诊断用途（核对部署版本），非常规日志
console.info(`[FTDYB] build: ${__BUILD_ID__}`);

function App() {
  return (
    <MetaProvider>
      {/* 全局断连横幅：路由层之外，页面任何状态下都可见 */}
      <HealthBanner />
      <AppErrorBoundary>
        <AppRouter />
      </AppErrorBoundary>
    </MetaProvider>
  );
}

const rootEl = document.getElementById('root');
if (rootEl) {
  render(() => <App />, rootEl);
}
