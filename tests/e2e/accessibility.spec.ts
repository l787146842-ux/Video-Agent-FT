/**
 * E2E：核心界面无障碍审计（axe-core）
 *
 * 四模式扫描：
 *   1. 影视工作台（dark 主题，完成态对话流）
 *   2. 影视工作台（light 主题，空态）
 *   3. API 配置页（dark 主题）
 *   4. 全局设置页（dark 主题）
 *
 * 策略：
 * - 白名单归零：critical 级违规存量已修（conv-tabs 补 role=tablist），
 *   断言 critical violations = 0，任何新增即红。
 * - 棘轮（计数只减不增）：全量违规总数锁定上界（RATCHET），
 *   新增违规导致总数超标即红；修复后需同步收紧上界。
 * - 扫描面扩：四个页面/主题组合均独立扫描，各自落盘违规清单。
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {
  startSseServer, wireAgentRoutes, wireEmptyConversations,
  sendMessage, pinDefaultTheme, expectDefaultTheme,
  waitAppReady, waitSettingsReady, waitGlobalSettingsReady,
} from './helpers/sse-mock';

/**
 * 棘轮上界：全模式违规类型总数不得超过此值。
 * 修复违规后收紧此数字（只减不增）。
 * 初始值 = 修复 aria-required-parent 后实测存量（moderate/serious/total）。
 */
const RATCHET_TOTAL = 8;

/** 运行 axe 扫描并输出违规清单，返回违规类型总数 */
async function runAxeScan(
  page: import('@playwright/test').Page,
  testInfo: import('@playwright/test').TestInfo,
  label: string,
): Promise<number> {
  const results = await new AxeBuilder({ page }).analyze();

  // 违规清单落盘
  const byImpact: Record<string, number> = {};
  for (const v of results.violations) {
    byImpact[v.impact || 'unknown'] = (byImpact[v.impact || 'unknown'] || 0) + 1;
  }
  const ledger = {
    mode: label,
    scannedAt: new Date().toISOString(),
    summary: byImpact,
    totalTypes: results.violations.length,
    violations: results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.length,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
    })),
  };
  await testInfo.attach(`axe-${label}.json`, {
    body: JSON.stringify(ledger, null, 2),
    contentType: 'application/json',
  });
  console.log(`[axe:${label}] 违规统计：${JSON.stringify(byImpact)}（共 ${results.violations.length} 类）`);
  for (const v of results.violations) {
    console.log(`[axe:${label}] ${v.impact} ${v.id} ×${v.nodes.length} — ${v.help}`);
  }

  // 白名单归零：critical 级违规不允许存在
  const critical = results.violations.filter((v) => v.impact === 'critical');
  expect(
    critical,
    `[${label}] critical 级违规必须为零（白名单已归零）：${critical.map((v) => `${v.id} ×${v.nodes.length}`).join(', ')}`,
  ).toHaveLength(0);

  return results.violations.length;
}

test.describe('无障碍审计（四模式 + 棘轮）', () => {
  test('模式1：影视工作台 dark 主题（完成态对话流）', async ({ page }, testInfo) => {
    await pinDefaultTheme(page);

    const handle = await startSseServer({
      frames: [
        '{"type":"status","text":"正在思考…"}',
        '{"type":"reasoning_delta","text":"先评估素材"}',
        '{"type":"tool_started","id":"t1","name":"script_analyze","summary":"分析剧本"}',
        '{"type":"tool_finished","id":"t1","ok":true,"elapsed_ms":800,"result_summary":"分析完成"}',
      ],
      done: { text: '剧本评估完成', elapsed_ms: 900, steps: 1, applied_actions: 1 },
    });
    const capturedBodies: Array<Record<string, unknown>> = [];
    await wireAgentRoutes(page, handle, capturedBodies);
    await wireEmptyConversations(page);

    await page.goto('/');
    await waitAppReady(page);
    await expectDefaultTheme(page);
    await sendMessage(page, '帮我评估剧本');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('剧本评估完成', { timeout: 10000 });

    const count = await runAxeScan(page, testInfo, 'dark-chat');
    expect(count, `棘轮：dark-chat 违规类型总数 ${count} 超过上界 ${RATCHET_TOTAL}`).toBeLessThanOrEqual(RATCHET_TOTAL);
    await handle.close();
  });

  test('模式2：影视工作台 light 主题（空态）', async ({ page }, testInfo) => {
    await page.addInitScript(() => {
      localStorage.setItem('ftdyb-theme', 'light');
    });
    await wireEmptyConversations(page);

    await page.goto('/');
    await waitAppReady(page);
    await expect(page.locator('html')).toHaveClass(/(^|\s)light(\s|$)/);

    const count = await runAxeScan(page, testInfo, 'light-empty');
    expect(count, `棘轮：light-empty 违规类型总数 ${count} 超过上界 ${RATCHET_TOTAL}`).toBeLessThanOrEqual(RATCHET_TOTAL);
  });

  test('模式3：API 配置页 dark 主题', async ({ page }, testInfo) => {
    await pinDefaultTheme(page);

    await page.goto('/settings');
    await waitSettingsReady(page);

    const count = await runAxeScan(page, testInfo, 'dark-settings');
    expect(count, `棘轮：dark-settings 违规类型总数 ${count} 超过上界 ${RATCHET_TOTAL}`).toBeLessThanOrEqual(RATCHET_TOTAL);
  });

  test('模式4：全局设置页 dark 主题', async ({ page }, testInfo) => {
    await pinDefaultTheme(page);

    await page.goto('/global-settings');
    await waitGlobalSettingsReady(page);

    const count = await runAxeScan(page, testInfo, 'dark-global-settings');
    expect(count, `棘轮：dark-global-settings 违规类型总数 ${count} 超过上界 ${RATCHET_TOTAL}`).toBeLessThanOrEqual(RATCHET_TOTAL);
  });
});
