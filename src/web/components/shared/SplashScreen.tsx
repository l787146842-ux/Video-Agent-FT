/**
 * 首屏加载 Splash Screen
 * 在后端数据加载完成前显示，避免白屏。
 */
export function SplashScreen() {
  return (
    <div class="splash-screen">
      <div class="splash-logo">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 2l2.9 6.26L21.5 9.27l-4.75 4.28L18.18 20 12 16.77 5.82 20l1.43-6.45L2.5 9.27l6.6-1.01L12 2z"
            fill="url(#splashGrad)"
            stroke="#b8860b"
            stroke-width="0.5"
          />
          <defs>
            <linearGradient id="splashGrad" x1="2" y1="2" x2="22" y2="22">
              <stop offset="0%" stop-color="#ffd700" />
              <stop offset="100%" stop-color="#dc2626" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      <div class="splash-spinner" />
      <p class="splash-text">正在加载工作台…</p>
    </div>
  );
}
