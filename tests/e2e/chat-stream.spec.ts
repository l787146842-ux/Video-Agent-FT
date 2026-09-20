/**
 * E2E：对话流交互四场景（P4-19 回归防护）
 *
 * 确定性验证，无需真实 LLM：
 * (a) tool_started/tool_finished/reasoning_delta 帧 → 时间线两面板呈现与耗时角标；
 * (b) 停止按钮 → 已累积文本落停止气泡（任务 #17 阶段化措辞）；
 * (c) 悬停工具条矩阵 / 末条原地编辑（truncate-resend）/ 重新生成 / 分支截断（任务 #17 新交互模型）；
 * (d) 排队引导 → 条目原位 spinner，轮间注入成功后引导上屏。
 *
 * SSE 保活：route.fulfill 一次性交付会立即结束流（忙态随之复位），
 * (b)(d) 需要流保持打开——用测试进程内的本地 SSE 服务器承接事件订阅
 * （route.continue 重定向，服务端带 CORS 头），按需分帧推送、可长时间挂起。
 */
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import { test, expect } from '@playwright/test';
import { waitAppReady } from './helpers/sse-mock';

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
    await waitAppReady(page);
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
    await waitAppReady(page);
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
    await waitAppReady(page);
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
    await waitAppReady(page);
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

test.describe('悬停工具条与截断重答（任务 #17 新交互模型）', () => {
  /** 确定性点亮工具条并等待过渡终值：focus 触发 :focus-within（不依赖鼠标命中/
   * 隐藏窗口 :hover 合成），再轮询 opacity 计算样式收敛到终值 '1'——
   * 不赌 0.12s CSS 过渡的中间态（慢机器/后台窗口下过渡可能冻结或延迟）。
   * 工具条按钮集由 affordances 矩阵条件渲染（Show），落盘与否与显隐无关。 */
  async function revealToolbar(
    msg: import('@playwright/test').Locator,
    anchorTestid: string,
  ) {
    const anchor = msg.locator(`[data-testid="${anchorTestid}"]`);
    await expect(anchor).toBeAttached({ timeout: 10000 });
    await anchor.focus();
    await expect(msg.locator('[data-testid="msg-hover-toolbar"]'))
      .toHaveCSS('opacity', '1', { timeout: 10000 });
  }

  /** 截断重答端点 mock：捕获 body，返回与 /agent/tasks 同形的 {task_id, project_id} */
  async function wireTruncateRoute(
    page: import('@playwright/test').Page,
    captured: Array<Record<string, unknown>>,
  ) {
    await page.route(/\/api\/chat\/truncate-resend$/, (route) => {
      captured.push(route.request().postDataJSON());
      void route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ task_id: 'e2e-trunc', project_id: 'e2e-p' }),
      });
    });
  }

  test('悬停工具条矩阵：末条挂编辑/重新生成，历史轮不挂；分支挂全部 agent 回复', async ({ page }) => {
    const handle = await startSseServer({
      done: (taskNo) => ({
        text: taskNo === 1 ? '回复甲' : '回复乙',
        elapsed_ms: 100, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '原始问题');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('回复甲', { timeout: 10000 });
    await sendMessage(page, '第二个问题');
    await expect(feed).toContainText('回复乙', { timeout: 10000 });

    // 末条用户消息：复制+编辑（无分支/重新生成）；工具条带 HH:MM 时间戳。
    // 键盘 focus 通路点亮（见 revealToolbar）：hover 命中点在消息底缘与相邻条目
    // 竞态，隐藏窗口下 :hover 合成不稳——focus-within 是确定性路径
    const lastUser = feed.locator('.chat-msg.user', { hasText: '第二个问题' });
    await revealToolbar(lastUser, 'msg-act-edit');
    await expect(lastUser.locator('[data-testid="msg-act-edit"]')).toBeEnabled();
    await expect(lastUser.locator('[data-testid="msg-act-copy"]')).toBeEnabled();
    await expect(lastUser.locator('[data-testid="msg-act-branch"]')).toHaveCount(0);
    await expect(lastUser.locator('[data-testid="msg-act-regenerate"]')).toHaveCount(0);
    await expect(lastUser.locator('.msg-hover-time')).toContainText(/^\d{2}:\d{2}$/);

    // 末条 agent 回复：复制+分支+重新生成+存为文档（含正文的助手消息挂，任务#6 C-2）
    const lastAgent = feed.locator('.chat-msg.agent', { hasText: '回复乙' });
    await revealToolbar(lastAgent, 'msg-act-regenerate');
    await expect(lastAgent.locator('[data-testid="msg-act-regenerate"]')).toBeEnabled();
    await expect(lastAgent.locator('[data-testid="msg-act-branch"]')).toBeEnabled();
    await expect(lastAgent.locator('[data-testid="msg-act-copy"]')).toBeEnabled();
    await expect(lastAgent.locator('[data-testid="msg-act-save-doc"]')).toBeEnabled();

    // 历史轮：agent 回复只留分支（无重新生成）；用户消息只留复制（无编辑）
    const histAgent = feed.locator('.chat-msg.agent', { hasText: '回复甲' });
    await revealToolbar(histAgent, 'msg-act-branch');
    await expect(histAgent.locator('[data-testid="msg-act-regenerate"]')).toHaveCount(0);
    await expect(histAgent.locator('[data-testid="msg-act-save-doc"]')).toBeEnabled();
    const histUser = feed.locator('.chat-msg.user', { hasText: '原始问题' });
    await revealToolbar(histUser, 'msg-act-copy');
    await expect(histUser.locator('[data-testid="msg-act-edit"]')).toHaveCount(0);
    await handle.close();
  });

  test('末条用户消息原地编辑：旧回复消失，截断重答携带新正文', async ({ page }) => {
    const handle = await startSseServer({
      done: (taskNo) => ({
        text: taskNo === 1 ? '旧回复' : '重答后的新回复',
        elapsed_ms: 100, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    const truncateBodies: Array<Record<string, unknown>> = [];
    await wireTruncateRoute(page, truncateBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '原始问题');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('旧回复', { timeout: 10000 });

    // 键盘通路：focus 经 :focus-within 点亮工具条，Enter 触发按钮——
    // hover+click 在布局变化（新消息上屏）时会被相邻条目拦截指针事件
    const lastUser = feed.locator('.chat-msg.user', { hasText: '原始问题' });
    await lastUser.locator('[data-testid="msg-act-edit"]').focus();
    await lastUser.locator('[data-testid="msg-act-edit"]').press('Enter');
    const box = feed.locator('[data-testid="inline-edit-box"]');
    await expect(box).toBeVisible({ timeout: 10000 });
    const ta = box.locator('.inline-edit-textarea');
    await expect(ta).toHaveValue('原始问题');

    // 改写后发送 → POST truncate-resend {text}；旧回复消失，新回复流式接续
    await ta.fill('改写后的问题');
    await box.locator('[data-testid="inline-edit-send"]').click();
    await expect.poll(() => truncateBodies.length, { timeout: 10000 }).toBe(1);
    expect(truncateBodies[0].text).toBe('改写后的问题');
    await expect(feed.locator('.user-bubble-text', { hasText: '改写后的问题' })).toBeVisible({ timeout: 10000 });
    await expect(feed.locator('.chat-msg', { hasText: '旧回复' })).toHaveCount(0, { timeout: 10000 });
    await expect(feed).toContainText('重答后的新回复', { timeout: 10000 });
    await handle.close();
  });

  test('末条 agent 回复重新生成：truncate-resend 无 text，原地更新为新回复', async ({ page }) => {
    const handle = await startSseServer({
      done: (taskNo) => ({
        text: taskNo === 1 ? '第一版回复' : '第二版回复',
        elapsed_ms: 100, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    const truncateBodies: Array<Record<string, unknown>> = [];
    await wireTruncateRoute(page, truncateBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '写一首诗');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('第一版回复', { timeout: 10000 });

    // 键盘通路（同上）：focus 点亮 :focus-within 工具条后 Enter 触发重新生成
    const lastAgent = feed.locator('.chat-msg.agent', { hasText: '第一版回复' });
    await lastAgent.locator('[data-testid="msg-act-regenerate"]').focus();
    await lastAgent.locator('[data-testid="msg-act-regenerate"]').press('Enter');

    // 无 text 截断重答（body 不带正文）；旧回复消失、新回复上屏，用户消息保留
    await expect.poll(() => truncateBodies.length, { timeout: 10000 }).toBe(1);
    expect(truncateBodies[0].text ?? null).toBeNull();
    await expect(feed.locator('.chat-msg', { hasText: '第一版回复' })).toHaveCount(0, { timeout: 10000 });
    await expect(feed).toContainText('第二版回复', { timeout: 10000 });
    await expect(feed.locator('.user-bubble-text', { hasText: '写一首诗' })).toBeVisible();
    await handle.close();
  });

  test('分支截断：以该消息为分叉点，分支对话不含被截断消息', async ({ page }) => {
    const handle = await startSseServer({
      done: (taskNo) => ({
        text: taskNo === 1 ? '第一轮回复' : '第二轮回复',
        elapsed_ms: 100, steps: 1, applied_actions: 0,
      }),
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    // 快照/分支端点 mock：捕获 up_to_index；分支 payload 只含分叉点及之前的消息
    const snapshotBodies: Array<Record<string, unknown>> = [];
    await page.route(/\/api\/conversations\/snapshot$/, (route) => {
      snapshotBodies.push(route.request().postDataJSON());
      void route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ snap_id: 'snap-1', title: '快照' }),
      });
    });
    await page.route(/\/api\/conversations\/snapshots\/[^/]+\/branch$/, (route) => {
      void route.fulfill({
        status: 200, contentType: 'application/json',
        // E-2 消息单一来源：分支响应只含元信息，消息经按会话拉消息接口装载
        body: JSON.stringify({
          conversations: [{ id: 'c-branch', title: '分支对话' }],
          active_conversation_id: 'c-branch',
        }),
      });
    });
    await page.route(/\/api\/conversations\/[^/]+\/messages$/, (route) => {
      void route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          conversation_id: 'c-branch',
          messages: [
            { sender: 'user', text: '第一个问题' },
            { sender: 'agent', text: '第一轮回复' },
          ],
        }),
      });
    });

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '第一个问题');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('第一轮回复', { timeout: 10000 });
    await sendMessage(page, '第二个问题');
    await expect(feed).toContainText('第二轮回复', { timeout: 10000 });

    // 悬停历史 agent 回复「第一轮回复」→ 点分支
    // force：工具条贴消息底缘，点击命中点可能被相邻下一条 .chat-msg 遮挡判定拦截
    const target = feed.locator('.chat-msg.agent', { hasText: '第一轮回复' });
    // 先读分叉点下标（点击后消息列表会被分支对话替换，元素可能失效）
    const forkIdx = Number(await target.getAttribute('data-msg-index'));
    await target.hover();
    await target.locator('[data-testid="msg-act-branch"]').click({ force: true });

    // 分叉点 = 该消息索引（含；与消息 data-msg-index 对齐，不依赖环境历史长度）；
    // 切换后分支对话不含被截断的第二轮
    await expect.poll(() => snapshotBodies.length, { timeout: 10000 }).toBe(1);
    expect(snapshotBodies[0].up_to_index).toBe(forkIdx);
    await expect(feed.locator('.chat-msg', { hasText: '第二个问题' })).toHaveCount(0, { timeout: 10000 });
    await expect(feed.locator('.chat-msg', { hasText: '第二轮回复' })).toHaveCount(0, { timeout: 10000 });
    await expect(feed).toContainText('第一轮回复', { timeout: 10000 });
    await handle.close();
  });
});

test.describe('视频结果内联预览卡（任务 #10）', () => {
  test('done payload chat_inserts 视频项 → 内联预览卡（poster + ▶ 角标 + lightbox）', async ({ page }) => {
    const handle = await startSseServer({
      done: {
        text: '视频已生成', elapsed_ms: 100, steps: 1, applied_actions: 0,
        // 数据通路：done payload 的 chat_inserts 中 kind=video 项（带首帧 thumb）
        chat_inserts: [
          { kind: 'video', url: 'http://127.0.0.1:1/media/opening.mp4', name: '开场.mp4', thumb: 'http://127.0.0.1:1/media/opening.jpg' },
        ],
      },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);

    await page.goto('/');
    await waitAppReady(page);
    await sendMessage(page, '生成一段开场视频');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('视频已生成', { timeout: 10000 });

    // 视频卡上屏：标题（locale rp.msg.videoResult）+ 首帧 poster + ▶ 角标 + 文件名
    const card = feed.locator('.video-card');
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText('视频结果');
    await expect(card).toContainText('开场.mp4');
    const video = card.locator('video');
    await expect(video).toHaveAttribute('src', /opening\.mp4/);
    await expect(video).toHaveAttribute('poster', /opening\.jpg/);
    await expect(card.locator('.video-card-badge')).toContainText('▶');

    // 点击缩略 → lightbox 播放（共享 MediaLightbox kind=video）
    await card.locator('.video-card-thumb').click();
    const lightbox = page.locator('.image-lightbox');
    await expect(lightbox).toBeVisible({ timeout: 10000 });
    await expect(lightbox.locator('video')).toHaveAttribute('src', /opening\.mp4/);
    // Esc 关闭
    await page.keyboard.press('Escape');
    await expect(lightbox).toHaveCount(0, { timeout: 10000 });
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
    await waitAppReady(page);
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
    await waitAppReady(page);
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
    await waitAppReady(page);
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
