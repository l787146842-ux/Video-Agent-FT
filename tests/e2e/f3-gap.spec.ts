/**
 * E2E：F-3 遗留三场景补钉（整改计划第三波验收）
 *
 * 确定性验证，无需真实 LLM（复用 chat-stream 的 mock 模式）：
 * (a) 结构化决策表单：done 载荷携带 workflow.pending_decision_payload +
 *     pause_id → 决策表单卡渲染；提交后 pause_response 结构化回携；
 * (b) 钉住栏（PinnedRail）：文档卡右键「钉住到侧栏」→ 栏内条目 + 计数；
 *     取消钉住 → 条目消失；
 * (c) 画布降级：/api/canvas/list 失败 → CanvasView 错误覆盖层；主链聊天
 *     不受影响。
 */
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { test, expect } from '@playwright/test';
import { waitAppReady } from './helpers/sse-mock';

/** 与 chat-stream.spec.ts 同款的本地 SSE 服务器（帧注入 / done 收口） */
function startSseServer(opts: {
  frames?: string[];
  done?: Record<string, unknown>;
}): Promise<{ base: string; close: () => Promise<void> }> {
  const streams = new Set<http.ServerResponse>();
  const server = http.createServer((req, res) => {
    if (req.method === 'GET' && (req.url || '').startsWith('/sse')) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Access-Control-Allow-Origin': '*',
      });
      streams.add(res);
      res.on('close', () => streams.delete(res));
      for (const f of opts.frames || []) res.write(`data: ${f}\n\n`);
      if (opts.done) {
        res.write(`data: ${JSON.stringify({ type: 'done', payload: opts.done })}\n\n`);
      }
      return;
    }
    res.writeHead(404).end();
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

async function wireAgentRoutes(
  page: import('@playwright/test').Page,
  handle: { base: string },
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

async function sendMessage(page: import('@playwright/test').Page, text: string) {
  const input = page.locator('#chatInputTextarea');
  await expect(input).toBeVisible();
  await input.fill(text);
  await input.press('Enter');
}

test.describe('F-3 补钉：结构化决策表单', () => {
  test('done+workflow 联动渲染表单卡，提交携带 pause_response 结构化回携', async ({ page }) => {
    const handle = await startSseServer({
      frames: ['{"type":"status","text":"正在思考…"}'],
      done: {
        text: '', applied_actions: 0, steps: 1,
        pause_id: 'pause-e2e-1',
        workflow: {
          run_id: 'r1', status: 'waiting_user',
          current_node: 'review_spec', completed_nodes: [],
          pending_decision: true,
          pending_decision_payload: {
            token: 'review:r1',
            node_id: 'review_spec',
            message: '请确认成片规格参数',
            schema: {
              type: 'fields',
              fields: [
                {
                  key: 'aspect', label: '画幅', type: 'select', required: true,
                  options: [
                    { value: '16:9', label: '横屏 16:9' },
                    { value: '9:16', label: '竖屏 9:16' },
                  ],
                },
                { key: 'shots', label: '分镜数量', type: 'number', required: true, default: 4 },
              ],
            },
            options: [],
          },
        },
      },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '开始规划');

    // 表单卡渲染：标题 + select/number 字段（number 出 schema.default=4）
    const card = page.getByTestId('decision-form-card').first();
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText('请确认成片规格参数');
    const numInput = card.locator('input[type="number"]');
    await expect(numInput).toHaveValue('4');
    await card.locator('select').selectOption({ label: '竖屏 9:16' });

    // 提交：序列化「字段: 值」逐行 + pause_response 结构化回携
    await card.locator('.confirm-btn.primary').click();
    await expect.poll(() => capturedBodies.length, { timeout: 10000 })
      .toBeGreaterThan(1);
    const submitBody = capturedBodies[capturedBodies.length - 1];
    expect(String(submitBody.message)).toContain('画幅: 9:16');
    expect(String(submitBody.message)).toContain('分镜数量: 4');
    expect(submitBody.pause_response).toEqual({
      pause_id: 'pause-e2e-1',
      value: expect.stringContaining('分镜数量: 4'),
    });
    await handle.close();
  });
});

test.describe('F-3 补钉：钉住栏', () => {
  test('文档卡右键钉住 → 栏内条目与计数；取消钉住 → 栏随空隐藏', async ({ page }) => {
    // 隔离：清掉历史运行遗留的 pinned localStorage（持久化键）
    await page.addInitScript(() => localStorage.clear());
    const handle = await startSseServer({
      frames: ['{"type":"status","text":"正在处理…"}'],
      done: {
        text: '规格已写入。', applied_actions: 1, steps: 1,
        documents_written: ['执行铁律.md'],
      },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '把规范写下来');

    // 文档卡上屏 → 右键出上下文菜单 → 钉住到侧栏
    const docCard = page.locator('.doc-card', { hasText: '执行铁律.md' }).first();
    await expect(docCard).toBeVisible({ timeout: 10000 });
    // 真实指针右键（悬停工具条可能覆盖卡片右上角，取元素中心点规避）
    const box = await docCard.boundingBox();
    await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2,
      { button: 'right' });
    await expect(page.locator('[data-context-menu]')).toBeVisible({ timeout: 5000 });
    await page.locator('.context-menu-item', { hasText: '钉住到' }).click();

    // 钉住栏：条目 + 计数 1/
    const rail = page.locator('.pinned-rail');
    await expect(rail).toBeVisible();
    await expect(rail.locator('.pinned-item-name', { hasText: '执行铁律.md' }))
      .toHaveCount(1);
    await expect(rail.locator('.pinned-rail-count')).toHaveText(/1\//);

    // 取消钉住：唯一条目清空 → 栏整体卸载（AgentLayout: pinned>0 才挂载）
    await rail.locator('.pinned-item-unpin').first().click();
    await expect(page.locator('.pinned-rail')).toHaveCount(0);
    await handle.close();
  });
});

test.describe('F-3 补钉：画布降级', () => {
  test('canvas 探测失败 → 错误覆盖层可关闭；聊天主链不受影响', async ({ page }) => {
    // 画布探测必败：列表接口 500（CanvasView onMount probeCanvasOnline）
    await page.route(/\/api\/canvas\/list/, (route) => route.fulfill({
      status: 500, contentType: 'application/json', body: '{"detail":"boom"}',
    }));

    await page.goto('/canvas');
    const fallback = page.locator('.canvas-fallback');
    await expect(fallback).toBeVisible({ timeout: 10000 });
    await expect(fallback).toContainText('画布加载失败');

    // 关闭覆盖层（继续等待）：不阻塞用户停留当前页
    await fallback.locator('.btn-secondary', { hasText: '继续等待' }).click();
    await expect(fallback).toHaveCount(0);

    // 主链回归：回到工作台，mock 流正常收发（画布离线不拖垮聊天）
    const handle = await startSseServer({
      frames: ['{"type":"status","text":"正在思考…"}'],
      done: { text: '画布虽离线我仍能回答', elapsed_ms: 50, steps: 1 },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '画布挂了你还能干活吗');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('画布虽离线我仍能回答', { timeout: 10000 });
    await handle.close();
  });
});
