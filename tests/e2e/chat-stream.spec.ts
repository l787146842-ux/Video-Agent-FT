/**
 * E2E：对话流交互四场景（P4-19 回归防护）
 *
 * 确定性验证，无需真实 LLM：
 * (a) tool_started/tool_finished/reasoning_delta 帧 → 时间线两面板呈现与耗时角标；
 * (b) 停止按钮 → 已累积文本落停止气泡（任务 #17 阶段化措辞）；
 * (c) 重新生成按钮 → 机械重发该回复前最近的用户消息；
 * (d) 排队引导 → 条目原位 spinner，轮间注入成功后引导上屏。
 *
 * SSE 保活：route.fulfill 一次性交付会立即结束流（忙态随之复位），
 * (b)(d) 需要流保持打开——用测试进程内的本地 SSE 服务器承接事件订阅
 * （route.continue 重定向，服务端带 CORS 头），按需分帧推送、可长时间挂起。
 */
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { test, expect } from '@playwright/test';

/** 帧用 \n\n 分隔；done 缺省 = 流保持打开（前端忙态持续） */
interface ScriptOpts {
  /** 事件订阅建立时立即推送的帧（不含 data: 前缀） */
  frames?: string[];
  /** 完成帧负载；省略则流保持打开。函数形式按任务次序返回不同负载 */
  done?: Record<string, unknown> | ((taskNo: number) => Record<string, unknown>);
  /** 收到引导登记（POST /guidance）时向打开的流追加的帧；
   *  函数形式可读取登记体（回注真实排队 id）；返回 Promise 可延迟注入 */
  onGuidance?: string[] | ((body: Record<string, unknown>) => string[] | Promise<string[]>);
}

interface ScriptHandle {
  base: string;
  close: () => Promise<void>;
}

function startSseServer(opts: ScriptOpts): Promise<ScriptHandle> {
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
 * 用正则而非 glob：glob `**\/api/agent/tasks` 不匹配带查询串的列表请求，
 * 真实后端残留 running 任务会经 resume 泄漏进页面（误挂按钮/误占忙态）。 */
async function wireAgentRoutes(
  page: import('@playwright/test').Page,
  handle: ScriptHandle,
  capturedBodies: Array<Record<string, unknown>>,
) {
  // 先注册通用再注册特化（Playwright 后注册优先）：特化路由先于通用命中
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

async function sendMessage(page: import('@playwright/test').Page, text: string) {
  const input = page.locator('#chatInputTextarea');
  await expect(input).toBeVisible();
  await input.fill(text);
  await input.press('Enter');
}

test.describe('时间线两面板（结构化 SSE 帧）', () => {
  test('reasoning_delta 与 tool 帧 → 深度思考/已处理操作面板与耗时角标', async ({ page }) => {
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"reasoning_delta","text":"先评估素材，再决定拆分方案"}',
        '{"type":"tool_started","id":"t1","name":"script_analyze","summary":"分析剧本"}',
        '{"type":"tool_finished","id":"t1","ok":true,"elapsed_ms":800,"result_summary":"分析完成"}',
      ],
      done: {
        text: '剧本评估完成', elapsed_ms: 900, steps: 1, applied_actions: 1,
        trace: {
          steps: [{
            step: 1, timing_ms: 800, actions_applied: 1, finish_reason: 'stop',
            reasoning: '先评估素材，再决定拆分方案',
            actions: [{ name: 'script_analyze', summary: '分析剧本', ok: true, elapsed_ms: 800 }],
          }],
          total_ms: 900,
        },
      },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '帮我评估剧本');

    const feed = page.getByTestId('chat-feed');
    // 流式中：深度思考面板实时展开，思考文本上屏
    // first()：后端真实会话历史可能携带同型时间线（E2E 不 mock 会话端点），
    // 断言只要求「存在且可见」，后续 toContainText 钉本场景自身内容
    await expect(feed.locator('.agent-timeline .tl-panel-title', { hasText: '深度思考' }).first())
      .toBeVisible({ timeout: 10000 });
    await expect(feed).toContainText('先评估素材，再决定拆分方案', { timeout: 10000 });
    // 完成入库：已处理操作面板 + 条目耗时角标（800ms → 0.8s）
    await expect(feed).toContainText('剧本评估完成', { timeout: 10000 });
    await expect(feed).toContainText('已处理', { timeout: 10000 });
    await expect(feed.locator('.tl-item-elapsed').last()).toContainText('0.8s');
    await handle.close();
  });
});

test.describe('停止按钮', () => {
  test('点击停止：已累积文本落「已在输出阶段停止」气泡', async ({ page }) => {
    const capturedStops: string[] = [];
    await page.route(/\/api\/agent\/tasks\/[^/]+\/stop/, (route) => {
      capturedStops.push(route.request().url());
      void route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"cancelled":1}' });
    });
    // 无 done 帧：流保持打开，忙碌态持续
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"delta","text":"半途而废的回答"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '写一段很长的开场白');

    const feed = page.getByTestId('chat-feed');
    // 累积文本进入流式气泡且忙碌态持续（停止键出现）
    await expect(feed).toContainText('半途而废的回答', { timeout: 10000 });
    const stopBtn = page.locator('.send-btn-stop');
    await expect(stopBtn).toBeVisible({ timeout: 10000 });
    await stopBtn.click();

    // 已累积文本落为停止气泡（任务 #17 阶段化措辞：有累积文本 → 输出阶段）；停止指令确实下发
    await expect(feed).toContainText('已在输出阶段停止', { timeout: 10000 });
    await expect.poll(() => capturedStops.length, { timeout: 10000 }).toBeGreaterThanOrEqual(1);
    await handle.close();
  });

  test('P4-21 停止后挂「继续刚才的任务」建议：点击机械重发最近用户消息', async ({ page }) => {
    await page.route(/\/api\/agent\/tasks\/[^/]+\/stop/, (route) => {
      void route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"cancelled":1}' });
    });
    // 无 done 帧：流保持打开，忙碑态持续至手动停止
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"delta","text":"半途而废的回答"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '写一段很长的开场白');

    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('半途而废的回答', { timeout: 10000 });
    await page.locator('.send-btn-stop').click();

    // 停止气泡本地派生继续建议（前端本地推导，不经 SSE 下发）
    const continueBtn = feed.locator('.suggested-action-btn', { hasText: '继续刚才的任务' });
    await expect(continueBtn).toBeVisible({ timeout: 10000 });

    // 点击走机械重发：新任务携带的是最近一条用户消息原文
    const postsBefore = capturedBodies.length;
    await continueBtn.click();
    await expect.poll(() => capturedBodies.length, { timeout: 10000 })
      .toBeGreaterThanOrEqual(postsBefore + 1);
    const resent = capturedBodies[capturedBodies.length - 1];
    expect(resent.message).toBe('写一段很长的开场白');
    await handle.close();
  });

  test('任务 #17 思考阶段停止：无文本停止也落停止气泡 + 继续建议 + 在途提醒', async ({ page }) => {
    // stop 响应携带在途外部生成任务登记（第一版不撤销，仅文案告知）
    const capturedStops17: string[] = [];
    await page.route(/\/api\/agent\/tasks\/[^/]+\/stop/, (route) => {
      capturedStops17.push(route.request().url());
      void route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ok: true, cancelled: 1,
          inflight: [{ task_id: 'g1', media_type: 'image', summary: '生成海报' }],
        }),
      });
    });
    // 只有 status 帧、无 delta：流保持打开、忙碑态持续，尚无任何可见正文（思考阶段）
    const handle = await startSseServer({
      frames: ['{"type":"status","text":"正在思考…"}'],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '帮我搭建故事板');

    // 忙碑态建立（停止键出现），此时仍无正文
    const stopBtn = page.locator('.send-btn-stop');
    await expect(stopBtn).toBeVisible({ timeout: 10000 });
    await stopBtn.click();

    const feed = page.getByTestId('chat-feed');
    // 停止指令确实下发（调试钉死：定位气泡缺失是请求未发还是渲染丢失）
    await expect.poll(() => capturedStops17.length, { timeout: 10000 }).toBeGreaterThanOrEqual(1);
    // 不变式：无文本停止不得静默——落思考阶段措辞的轻量停止气泡
    await expect(feed).toContainText('已在思考阶段停止', { timeout: 10000 });
    // 在途外部生成任务登记提醒（供应商侧仍在继续）
    await expect(feed).toContainText('在供应商侧继续', { timeout: 10000 });
    // 出口：挂「继续刚才的任务」建议
    const continueBtn = feed.locator('.suggested-action-btn', { hasText: '继续刚才的任务' });
    await expect(continueBtn).toBeVisible({ timeout: 10000 });
    await handle.close();
  });
});

test.describe('重新生成（机械重发）', () => {
  test('非末条 agent 回复点重新生成：重发其前最近用户消息', async ({ page }) => {
    // 按任务次序给不同回复：首问回「回复甲」，之后一律「回复乙」
    const handle = await startSseServer({
      done: (taskNo) => ({
        text: taskNo === 1 ? '回复甲' : '回复乙',
        elapsed_ms: 100, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '原始问题');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('回复甲', { timeout: 10000 });

    // 发出第二条用户消息，使第一条 agent 回复变为非末条（挂重新生成按钮）
    await sendMessage(page, '追加问题');
    await expect(feed).toContainText('回复乙', { timeout: 10000 });

    // 锺定「回复甲」气泡上的重新生成按钮（历史持久消息也挂同款按钮，不能用 first()）
    const regenBtn = feed.locator('.chat-msg', { hasText: '回复甲' })
      .locator('.msg-regenerate-btn').first();
    await expect(regenBtn).toBeVisible({ timeout: 10000 });
    const postsBefore = capturedBodies.length;
    await regenBtn.click();

    // 机械重发：新任务携带的是第一条用户消息的原文
    await expect.poll(() => capturedBodies.length, { timeout: 10000 })
      .toBeGreaterThanOrEqual(postsBefore + 1);
    const resent = capturedBodies[capturedBodies.length - 1];
    expect(resent.message).toBe('原始问题');
    await handle.close();
  });
});

test.describe('滚底保持（P4 滚底回归修复）', () => {
  /** 长回复：80 行撑高滚动容器，让「是否贴底」可度量（短内容恒贴底无区分度） */
  const longText = (prefix: string) => Array.from({ length: 80 }, (_, i) => `${prefix} ${i + 1}`).join('\n');
  const distFromBottom = (el: HTMLElement) => el.scrollHeight - el.scrollTop - el.clientHeight;

  test('发送消息后滚动容器保持在底部（不跳顶）', async ({ page }) => {
    const handle = await startSseServer({
      done: { text: longText('回复行'), elapsed_ms: 100, steps: 1, applied_actions: 0 },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '第一条消息');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('回复行 80', { timeout: 10000 });
    // 首轮回覆后内容已超高：容器应贴底（content-visibility 高度逐段兑现，用 poll 收敛）
    await expect.poll(() => feed.evaluate(distFromBottom), { timeout: 10000 }).toBeLessThan(80);

    // 再发一条：发送动作本身不得把容器打回顶部
    await sendMessage(page, '第二条消息');
    await expect(feed).toContainText('第二条消息', { timeout: 10000 });
    await expect.poll(() => feed.evaluate(distFromBottom), { timeout: 10000 }).toBeLessThan(80);
    await handle.close();
  });

  test('流式中点停止后保持在底部（不跳顶）', async ({ page }) => {
    await page.route(/\/api\/agent\/tasks\/[^/]+\/stop/, (route) => {
      void route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"cancelled":1}' });
    });
    // 无 done 帧：流保持打开，忙碌态持续至手动停止
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        JSON.stringify({ type: 'delta', text: longText('流式行') }),
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '写一段很长的开场白');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('流式行 80', { timeout: 10000 });
    // 流式增长中近底跟随生效
    await expect.poll(() => feed.evaluate(distFromBottom), { timeout: 10000 }).toBeLessThan(80);

    // 停止：已累积文本落停止气泡（任务 #17 阶段化措辞）后容器仍贴底
    await page.locator('.send-btn-stop').click();
    await expect(feed).toContainText('已在输出阶段停止', { timeout: 10000 });
    await expect.poll(() => feed.evaluate(distFromBottom), { timeout: 10000 }).toBeLessThan(80);
    await handle.close();
  });
});

test.describe('排队引导（忙碌中发送）', () => {
  test('排队条目点引导：原位 spinner，注入成功后引导上屏', async ({ page }) => {
    // 无 done 帧保持忙碌；引导登记延迟 3s 再回注真实排队 id（留出 spinner 可观察窗口）
    const handle = await startSseServer({
      frames: ['{"type":"status","text":"正在思考…"}'],
      onGuidance: async (body) => {
        await new Promise((r) => setTimeout(r, 3000));
        return [JSON.stringify({
          type: 'guidance_injected', id: body.id || '', text: body.text || '',
        })];
      },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '第一条消息');
    // 等待忙碌态真正建立（停止键出现）再发第二条，避免与建流竞态
    await expect(page.locator('.send-btn-stop')).toBeVisible({ timeout: 10000 });

    // 忙碌中继续发送 → 进入排队引导区（不阻断用户）
    await sendMessage(page, '换个风格试试');
    const chip = page.locator('.queued-bar .queued-chip-text', { hasText: '换个风格试试' });
    await expect(chip).toBeVisible({ timeout: 10000 });

    // 点「引导」：条目原位转圈等待轮间注入
    await page.locator('.queued-bar .queued-action-guide').first().click();
    await expect(page.locator('.queued-bar .queued-spin')).toBeVisible({ timeout: 10000 });

    // 注入成功：引导消息上屏为用户气泡并从排队区移除
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('换个风格试试', { timeout: 10000 });
    await expect(page.locator('.queued-bar .queued-chip')).toHaveCount(0, { timeout: 10000 });
    await handle.close();
  });
});
