/**
 * E2E：核心对话流视觉回归（任务 #6）
 *
 * 复用 chat-stream.spec.ts 的进程内 SSE mock 模式（helpers/sse-mock.ts），
 * 钉住 4 个关键态的 chat-feed 区域截图基线：
 *   1. 空态（初始加载，无消息）
 *   2. 流式输出中（delta 累积 + 忙碌态，无 done 帧流保持打开）
 *   3. 工具时间线完成入库（深度思考/已处理操作双面板）
 *   4. 错误气泡（SSE error 帧 → ErrorPayload 落气泡）
 *
 * 主题策略：项目双主题，只钉默认 dark 主题（pinDefaultTheme + 前置断言），
 * 避免基线爆炸。toHaveScreenshot 默认禁用 CSS 动画/过渡（typing-dots 等
 * 动效不参与像素比对）；首次运行生成基线属正常（--update-snapshots 隐含）。
 *
 * 【债务登记 · 任务 #11】截图基线目前仅有 win32 版（*-win32.png）。
 * 本机无 docker，无法用官方 playwright 镜像生成 linux 基线，故非 win32
 * 平台显式 skip（严禁用 snapshotPathTemplate 去平台后缀跨平台复用基线，
 * 字体渲染差异会导致随机红）。待具备 docker/linux 环境后补生成
 * feed-*-linux.png 并移除下方 skip 条件。
 */
import { test, expect } from '@playwright/test';
import {
  startSseServer, wireAgentRoutes, wireEmptyConversations, wireEmptyProjectState,
  sendMessage, pinDefaultTheme, expectDefaultTheme, waitAppReady,
} from './helpers/sse-mock';

// 基线缺失平台跳过：仅 win32 存在截图基线（见文件头债务登记）
test.skip(
  () => process.platform !== 'win32',
  '视觉基线仅有 win32 版，当前平台基线缺失跳过（linux 基线待 docker 环境生成）',
);

/** 截图比对容差：允许极小抗锯齿/字体渲染差异，结构性变化即红 */
const SNAP_OPTS = { maxDiffPixelRatio: 0.01 } as const;

test.describe('视觉回归：核心对话流关键态（默认 dark 主题）', () => {
  test('空态：初始加载的对话区', async ({ page }) => {
    await pinDefaultTheme(page);
    // 无任务提交也需钉空任务列表/会话，隔离后端残留历史
    const handle = await startSseServer({});
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    await wireEmptyProjectState(page);

    await page.goto('/');
    await waitAppReady(page);
    await expectDefaultTheme(page);

    const feed = page.getByTestId('chat-feed');
    await expect(feed).toBeVisible({ timeout: 10000 });
    await expect(feed.locator('.chat-msg')).toHaveCount(0);
    await expect(feed).toHaveScreenshot('feed-idle.png', SNAP_OPTS);
    await handle.close();
  });

  test('流式输出中：delta 累积文本 + 忙碌态', async ({ page }) => {
    await pinDefaultTheme(page);
    // 无 done 帧：流保持打开，忙碌态持续 → 「流式中」关键态可稳定截图
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"delta","text":"开场白第一句。"}',
        '{"type":"delta","text":"开场白第二句，镜头缓缓推进。"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    await wireEmptyProjectState(page);

    await page.goto('/');
    await waitAppReady(page);
    await expectDefaultTheme(page);
    await sendMessage(page, '写一段开场白');

    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('开场白第二句', { timeout: 10000 });
    // 忙碌态已建立（停止按钮出现）再截，否则截到发送前瞬态
    await expect(page.locator('.send-btn-stop')).toBeVisible({ timeout: 10000 });
    await expect(feed).toHaveScreenshot('feed-streaming.png', SNAP_OPTS);
    await handle.close();
  });

  test('工具时间线完成：深度思考/已处理操作双面板', async ({ page }) => {
    await pinDefaultTheme(page);
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"reasoning_delta","text":"先评估素材，再决定拆分方案"}',
        '{"type":"tool_started","id":"t1","name":"script_analyze","summary":"分析剧本"}',
        '{"type":"tool_finished","id":"t1","ok":true,"elapsed_ms":800,"result_summary":"分析完成"}',
      ],
      done: { text: '剧本评估完成', elapsed_ms: 900, steps: 1, applied_actions: 1 },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    await wireEmptyProjectState(page);

    await page.goto('/');
    await waitAppReady(page);
    await expectDefaultTheme(page);
    await sendMessage(page, '帮我评估剧本');

    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('剧本评估完成', { timeout: 10000 });
    await expect(feed).toContainText('已处理', { timeout: 10000 });
    // 时间线面板入库后再截（耗时角标 0.8s 为静态文本，无动效噪声）；
    // first()：防御性写法，与 chat-stream.spec.ts 对同型时间线的处理一致
    await expect(feed.locator('.agent-timeline').first()).toBeVisible({ timeout: 10000 });
    await expect(feed).toHaveScreenshot('feed-timeline-done.png', SNAP_OPTS);
    await handle.close();
  });

  test('错误气泡：SSE error 帧落 ErrorPayload', async ({ page }) => {
    await pinDefaultTheme(page);
    // error 帧为终态：前端落错误气泡后自行关流收尾（无需 done）
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        // raw 携带上游原始报文：错误气泡的「技术详情」折叠区（.msg-error-detail）
        // 仅在 errorDetail（raw）非空时渲染，无 raw 只剩人话气泡
        '{"type":"error","code":"err.auth.invalid_key","kind":"auth","detail":"API Key 无效","raw":"upstream 401 {\\"error\\":\\"invalid_api_key\\"}"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    await wireEmptyProjectState(page);

    await page.goto('/');
    await waitAppReady(page);
    await expectDefaultTheme(page);
    await sendMessage(page, '生成一张海报');

    const feed = page.getByTestId('chat-feed');
    // 错误气泡渲染（含折叠的原始报文 details）
    await expect(feed.locator('.msg-error-detail')).toBeVisible({ timeout: 10000 });
    // 忙碌态已复位（终态），截图中不含停止按钮瞬态
    await expect(page.locator('.send-btn-stop')).toHaveCount(0, { timeout: 10000 });
    await expect(feed).toHaveScreenshot('feed-error.png', SNAP_OPTS);
    await handle.close();
  });
});
