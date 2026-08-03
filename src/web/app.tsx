import { render } from 'solid-js/web';
import { MetaProvider } from '@solidjs/meta';
import './styles/app.css';
import { AppRouter } from './router';
import { AppErrorBoundary } from './components/shared/ErrorBoundary';

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
