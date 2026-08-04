import { render } from 'solid-js/web';
import { MetaProvider } from '@solidjs/meta';
import './styles/app.css';
import { AppRouter } from './router';
import { AppErrorBoundary } from './components/shared/ErrorBoundary';

declare const __BUILD_ID__: string;
// 启动即打印构建时间：用户反馈前端异常时，先核对浏览器跑的是否最新构建
console.info(`[FTDYB] build: ${__BUILD_ID__}`);

function App() {
  return (
    <MetaProvider>
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
