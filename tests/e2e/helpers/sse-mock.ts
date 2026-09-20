/**
 * E2E 共享 mock：测试进程内本地 SSE 服务器分帧推送（确定性对话流）。
 *
 * 自 chat-stream.spec.ts 的既有模式提取（该文件保持不动），
 * 供无障碍 / 视觉回归等新增 spec 复用同一确定性通路。
 *
 * 背景：route.fulfill 一次性交付会立即结束流（忙态随之复位），
 * 需要流保持打开的场景用本地 SSE 服务器承接事件订阅
 *（route.continue 重定向，服务端带 CORS 头），按需分帧推送、可长时间挂起。
 */
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';

/** 帧用 \n\n 分隔；done 缺省 = 流保持打开（前端忙态持续） */
export interface ScriptOpts {
  /** 事件订阅建立时立即推送的帧（不含 data: 前缀） */
  frames?: string[];
  /** 完成帧负载；省略则流保持打开。函数形式按任务次序返回不同负载 */
  done?: Record<string, unknown> | ((taskNo: number) => Record<string, unknown>);
  /** 收到引导登记（POST /guidance）时向打开的流追加的帧 */
  onGuidance?: string[] | ((body: Record<string, unknown>) => string[] | Promise<string[]>);
}

export interface ScriptHandle {
  base: string;
  close: () => Promise<void>;
}

export function startSseServer(opts: ScriptOpts): Promise<ScriptHandle> {
  /** 打开中的事件流响应（后续帧经 ServerResponse 写，保证 HTTP 分帧顺序） */
  const streams = new Set<http.ServerResponse>();
  let taskNo = 0;
  const write = (data: string) => {
    for (const res of streams) {
      try { res.write(data); } catch { /* 前端停止/导航断开 */ }
    }
  };
  const server = http.createServer((req, res) => {
    const url = req.url || '';
    if (req.method === 'GET' && url.startsWith('/sse')) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
      });
      streams.add(res);
      res.on('close', () => streams.delete(res));
      taskNo += 1;
      for (const f of opts.frames || []) res.write(`data: ${f}\n\n`);
      if (opts.done) {
        const payload = typeof opts.done === 'function' ? opts.done(taskNo) : opts.done;
        res.write(`data: ${JSON.stringify({ type: 'done', payload })}\n\n`);
      }
      return; // 未发 done：连接挂起
    }
    if (req.method === 'POST' && url.startsWith('/guidance')) {
      let raw = '';
      req.on('data', (c) => { raw += c; });
      req.on('end', async () => {
        let body: Record<string, unknown> = {};
        try { body = JSON.parse(raw || '{}'); } catch { /* 忽略 */ }
        const frames = typeof opts.onGuidance === 'function'
          ? await opts.onGuidance(body) : (opts.onGuidance || []);
        for (const f of frames) write(`data: ${f}\n\n`);
        res.writeHead(200, {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        });
        res.end('{"ok":true}');
      });
      return;
    }
    res.writeHead(404).end();
  });
  server.on('clientError', (_err, socket) => {
    socket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        base: `http://127.0.0.1:${port}`,
        // 挂开的 SSE 连接不会随 server.close() 断开，需先销毁，否则 close 永不返回
        close: () => new Promise<void>((r) => {
          for (const res of streams) {
            try { res.socket?.destroy(); } catch { /* 已断 */ }
          }
          streams.clear();
          server.close(() => r());
        }),
      });
    });
  });
}

/** 任务提交 mock + 事件订阅/引导登记重定向到本地 SSE 服务器。
 * 用正则而非 glob：glob 不匹配带查询串的列表请求，
 * 真实后端残留 running 任务会经 resume 泄漏进页面（误挂按钮/误占忙态）。 */
export async function wireAgentRoutes(
  page: import('@playwright/test').Page,
  handle: ScriptHandle,
  capturedBodies: Array<Record<string, unknown>>,
) {
  await page.route(/\/api\/agent\/tasks(\?.*)?$/, async (route) => {
    const req = route.request();
    if (req.method() === 'POST') {
      capturedBodies.push(req.postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 'e2e-task', project_id: 'e2e-p' }),
      });
    } else {
      // 任务列表强制为空：隔离后端历史 running 任务的 resume 订阅
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tasks: [] }),
      });
    }
  });
  await page.route(/\/api\/agent\/tasks\/[^/]+\/events/, (route) => {
    void route.continue({ url: `${handle.base}/sse` });
  });
  await page.route(/\/api\/agent\/tasks\/[^/]+\/guidance/, (route) => {
    void route.continue({ url: `${handle.base}/guidance` });
  });
}

/** 视觉/无障碍 spec 追加：会话端点也钉空——真实后端会话历史会泄漏进
 * chat-feed（E2E 默认不 mock 会话端点），对截图基线与 axe 扫描都是噪声源。 */
export async function wireEmptyConversations(page: import('@playwright/test').Page) {
  await page.route(/\/api\/conversations(\?.*)?$/, (route) => {
    if (route.request().method() === 'GET') {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ conversations: [], active_conversation_id: '' }),
      });
    } else {
      void route.continue();
    }
  });
  await page.route(/\/api\/conversations\/[^/]+\/messages$/, (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ conversation_id: 'c-e2e', messages: [] }),
    });
  });
}

/** 项目状态快照钉空：初始加载 GET /api/project/state 携带的 chatMessages
 * 会把后端工作区历史消息/时间线泄漏进 chat-feed（实测 6 条 .chat-msg 污染
 * 空态基线）。视觉 spec 需要完全确定的初始画面，此 mock 必挂。 */
export async function wireEmptyProjectState(page: import('@playwright/test').Page) {
  await page.route(/\/api\/project\/state(\?.*)?$/, (route) => {
    if (route.request().method() === 'GET') {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          project_id: 'e2e-p',
          chatMessages: [],
          conversations: [],
          activeConversationId: '',
        }),
      });
    } else {
      void route.continue();
    }
  });
}

export async function sendMessage(page: import('@playwright/test').Page, text: string) {
  const input = page.locator('#chatInputTextarea');
  await page.locator('#chatInputTextarea').waitFor({ state: 'visible' });
  await input.fill(text);
  await input.press('Enter');
}

/** 钉默认主题（dark）：双主题项目只保留一套基线，避免基线爆炸。
 * 缺省 localStorage 即 dark（use-theme.ts），显式写入防环境残留。 */
export async function pinDefaultTheme(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    localStorage.setItem('ftdyb-theme', 'dark');
  });
}

/** 断言当前确为默认（dark）主题——基线前置不变式 */
export async function expectDefaultTheme(page: import('@playwright/test').Page) {
  const { expect } = await import('@playwright/test');
  await expect(page.locator('html')).toHaveClass(/(^|\s)dark(\s|$)/);
}

// ===== 路由就绪信号（替代 Playwright 官方 DISCOURAGED 的 networkidle）=====
// 背景：本项目 SSE 长连接常驻，waitForLoadState('networkidle') 要求 500ms
// 无网络活动——SSE 流打开期间该条件结构性不可达或随机达成，是 E2E 抖动源。
// Playwright 官方口径（params.md / best-practices-js.md，Context7 核验）：
// 「Don't use this method for testing, rely on web assertions to assess
// readiness instead」。下列 helper 以各路由的稳定渲染元素为就绪信号，
// web-first 断言自动等待并重试，语义确定且不依赖网络静默。

/** 主应用（/ 路由）就绪：聊天输入框可见（AgentLayout 渲染完成信号） */
export async function waitAppReady(page: import('@playwright/test').Page) {
  const { expect } = await import('@playwright/test');
  await expect(page.locator('#chatInputTextarea')).toBeVisible({ timeout: 15000 });
}

/** API 设置页（/settings 路由）就绪：页头标题渲染完成 */
export async function waitSettingsReady(page: import('@playwright/test').Page) {
  const { expect } = await import('@playwright/test');
  await expect(page.locator('.aps-page-head h1')).toHaveText('API 设置', { timeout: 15000 });
}

/** 全局设置页（/global-settings 路由）就绪：面板标题渲染完成 */
export async function waitGlobalSettingsReady(page: import('@playwright/test').Page) {
  const { expect } = await import('@playwright/test');
  await expect(page.locator('.gs-title')).toHaveText('全局模型设置', { timeout: 15000 });
}
