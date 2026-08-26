/**
 * E2E：流式中刷新页面 → 轮次账本条目/停止痕迹从 trace 重建不丢（任务 #11）。
 *
 * 重建链路钉死：GET /api/project/state 快照 chatMessages → LayoutShell
 * loadMessages → settledLedgerForMessage（消息无本地 ledger 时回落
 * ledgerFromSettled，从 trace.steps[].actions 重建账本）→ 时间线渲染。
 *
 * 复用 chat-stream.spec 的 mock SSE 帧模式（helpers/sse-mock）：
 * 无 done 帧 = 流保持打开（刷新时确为「流式中」）；刷新前把项目状态
 * 快照切换为后端已定型持久化的形态（trace 在、本地账本不在），
 * page.reload() 后断言重建结果。page.route 注册跨 reload 存活。
 */
import { test, expect } from '@playwright/test';
import {
  startSseServer, wireAgentRoutes, wireEmptyConversations, sendMessage,
} from './helpers/sse-mock';

/** 可切换的项目状态快照：初始钉空，刷新前切换为含 trace 的定型持久化形态 */
function emptyProjectState(): Record<string, unknown> {
  return { project_id: 'e2e-p', chatMessages: [], conversations: [], activeConversationId: '' };
}

async function wireSwitchableProjectState(
  page: import('@playwright/test').Page,
  getSnapshot: () => Record<string, unknown>,
) {
  await page.route(/\/api\/project\/state(\?.*)?$/, (route) => {
    if (route.request().method() === 'GET') {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(getSnapshot()),
      });
    } else {
      void route.continue();
    }
  });
}

test.describe('流式中刷新重建（任务 #11）', () => {
  test('流式中刷新：轮次账本条目/思考/耗时角标从 trace 重建不丢', async ({ page }) => {
    // 无 done 帧：流保持打开（刷新时处于流式中，忙态挂起）
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"reasoning_delta","text":"先评估素材，再决定拆分方案"}',
        '{"type":"tool_started","id":"t1","name":"script_analyze","summary":"分析剧本"}',
        '{"type":"tool_finished","id":"t1","ok":true,"elapsed_ms":800,"result_summary":"分析完成"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    let snapshot = emptyProjectState();
    await wireSwitchableProjectState(page, () => snapshot);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '帮我评估剧本');
    const feed = page.getByTestId('chat-feed');
    // 流式中：工具条目 live 上屏（刷新前基线）
    await expect(feed).toContainText('分析剧本', { timeout: 10000 });

    // 刷新前切换快照：后端已定型持久化（trace 在、本地账本字段不在）——
    // 前端必须走 ledgerFromSettled 从 trace 重建，不得丢条目
    snapshot = {
      ...snapshot,
      chatMessages: [
        { sender: 'user', text: '帮我评估剧本' },
        {
          sender: 'agent', text: '剧本评估完成',
          trace: {
            steps: [{
              step: 1, timing_ms: 800, actions_applied: 1, finish_reason: 'stop',
              reasoning: '先评估素材，再决定拆分方案',
              actions: [{
                name: 'script_analyze', summary: '分析剧本',
                ok: true, elapsed_ms: 800, result_summary: '分析完成',
              }],
            }],
            total_ms: 900,
          },
        },
      ],
    };
    await page.reload();
    await page.waitForLoadState('networkidle');

    // 重建断言：正文 + 账本条目 + 耗时角标 + 深度思考文本全部从 trace 回来
    await expect(feed).toContainText('剧本评估完成', { timeout: 10000 });
    await expect(feed).toContainText('分析剧本', { timeout: 10000 });
    await expect(feed.locator('.tl-item-elapsed').last()).toContainText('0.8s', { timeout: 10000 });
    await expect(feed).toContainText('先评估素材，再决定拆分方案', { timeout: 10000 });
    // 刷新后忙态不残留（任务列表钉空，无 resume 泄漏）
    await expect(page.locator('.send-btn-stop')).toHaveCount(0);
    await handle.close();
  });

  test('流式中刷新：停止痕迹（部分文本 + 阶段措辞）从快照重建不丢', async ({ page }) => {
    await page.route(/\/api\/agent\/tasks\/[^/]+\/stop/, (route) => {
      void route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"cancelled":1}' });
    });
    // 无 done 帧：流保持打开至手动停止
    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"delta","text":"半途而废的回答"}',
      ],
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);
    let snapshot = emptyProjectState();
    await wireSwitchableProjectState(page, () => snapshot);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await sendMessage(page, '写一段很长的开场白');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('半途而废的回答', { timeout: 10000 });
    // 停止：已累积文本落停止气泡（本地派生，刷新即失）
    await page.locator('.send-btn-stop').click();
    await expect(feed).toContainText('已在输出阶段停止', { timeout: 10000 });

    // 刷新前切换快照：后端已把停止痕迹定型持久化（部分文本 + 阶段措辞 meta）
    snapshot = {
      ...snapshot,
      chatMessages: [
        { sender: 'user', text: '写一段很长的开场白' },
        { sender: 'agent', text: '半途而废的回答', meta: '已在输出阶段停止' },
      ],
    };
    await page.reload();
    await page.waitForLoadState('networkidle');

    // 重建断言：部分正文与停止痕迹（meta）都在，痕迹不因刷新而失踪
    await expect(feed).toContainText('半途而废的回答', { timeout: 10000 });
    await expect(feed).toContainText('已在输出阶段停止', { timeout: 10000 });
    await expect(page.locator('.send-btn-stop')).toHaveCount(0);
    await handle.close();
  });
});
