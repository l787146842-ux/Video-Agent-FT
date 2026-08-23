/**
 * E2E：闸机放行交互（任务 #13 F-7）
 *
 * 场景：Agent 任务完成帧携带 trace.gates ok=false → 消息挂闸机拦截 chips
 * 与「本次放行」按钮 → 点击以系统动作形态发送（gate_overrides + system_action
 * 随消息留痕）→ 新任务继续执行并上屏。
 *
 * 确定性验证，无需真实 LLM：沿用 chat-stream.spec.ts 的后端 mock 方式——
 * 任务提交经 route.fulfill 捕获 body，事件订阅重定向到测试进程内本地 SSE
 * 服务器（done 负载按任务次序返回不同剧本）。
 */
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { test, expect } from '@playwright/test';

interface ScriptOpts {
  /** 完成帧负载，按任务次序返回不同负载（省略则流保持打开） */
  done?: (taskNo: number) => Record<string, unknown>;
}

interface ScriptHandle {
  base: string;
  close: () => Promise<void>;
}

function startSseServer(opts: ScriptOpts): Promise<ScriptHandle> {
  const streams = new Set<http.ServerResponse>();
  let taskNo = 0;
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
      if (opts.done) {
        const payload = opts.done(taskNo);
        res.write(`data: ${JSON.stringify({ type: 'done', payload })}\n\n`);
      }
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

/** 任务提交 mock + 事件订阅重定向到本地 SSE 服务器（任务列表强制为空，
 * 隔离后端历史 running 任务的 resume 订阅）。 */
async function wireAgentRoutes(
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
        body: JSON.stringify({ task_id: 'e2e-gate', project_id: 'e2e-p' }),
      });
    } else {
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
}

test.describe('闸机放行交互（§2.4）', () => {
  test('闸机警告出现 → 本次放行 → 留痕继续', async ({ page }) => {
    // 第 1 个任务：done 携带 trace.gates ok=false（平台层拦截）；
    // 第 2 个任务（放行触发）：正常完成，证明放行后继续执行。
    const handle = await startSseServer({
      done: (taskNo) => (taskNo === 1 ? {
        text: '任务被闸机拦截', elapsed_ms: 100, steps: 1, applied_actions: 0,
        trace: {
          steps: [{
            step: 1, timing_ms: 100, actions_applied: 0, finish_reason: 'stop',
            gates: [{
              ok: false, rule_id: 'platform.tool_risk', layer: 'platform',
              message: '高危工具调用需人工确认',
            }],
          }],
          total_ms: 100,
        },
      } : {
        text: '已按放行继续执行', elapsed_ms: 80, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const input = page.locator('#chatInputTextarea');
    await expect(input).toBeVisible();
    await input.fill('执行高风险清理操作');
    await input.press('Enter');

    const feed = page.getByTestId('chat-feed');
    // 闸机警告出现：拦截文案 + 平台 chip + 折叠摘要 + 放行按钮
    await expect(feed).toContainText('任务被闸机拦截', { timeout: 10000 });
    await expect(feed).toContainText('高危工具调用需人工确认', { timeout: 10000 });
    await expect(feed.locator('.gate-chip-platform').first()).toBeVisible({ timeout: 10000 });
    await expect(feed.locator('.msg-gate-collapse-summary').last())
      .toContainText('闸机拦截 1 条', { timeout: 10000 });
    const overrideBtn = feed.locator('.gate-override-btn').last();
    await expect(overrideBtn).toBeVisible({ timeout: 10000 });

    // 本次放行：以系统动作形态发送，gate_overrides + system_action 随消息留痕
    await overrideBtn.click();
    await expect.poll(() => capturedBodies.length, { timeout: 10000 })
      .toBeGreaterThanOrEqual(2);
    const overrideBody = capturedBodies[capturedBodies.length - 1];
    expect(overrideBody.message).toBe('放行本次拦截，继续任务');
    expect(overrideBody.gate_overrides).toEqual(['all']);
    expect(overrideBody.system_action).toBe('system_action');

    // 留痕：系统动作行上屏（不占用户气泡形态）；放行后新任务继续执行并完成
    await expect(feed.locator('.system-action-line').last())
      .toContainText('放行本次拦截，继续任务', { timeout: 10000 });
    await expect(feed).toContainText('已按放行继续执行', { timeout: 10000 });
    await handle.close();
  });
});
