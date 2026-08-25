/**
 * E2E：核心对话界面无障碍审计（axe-core）
 *
 * 启动方式对齐既有 e2e：webServer 拉起后端 + 进程内本地 SSE 服务器
 * 分帧推送确定性对话流（helpers/sse-mock.ts）。
 *
 * 阈值策略（任务 #6）：先跑实测得存量 4 类违规（critical ×1 / serious ×1 /
 * moderate ×2），按任务约定取「记录全量清单 + 断言 critical」；而唯一 critical
 *（aria-required-parent：会话标签 role=tab 缺 tablist 父级）属存量 UI 债务，
 * 任务明令不为本测试改业务 UI → 白名单显式豁免并钉死数量，
 * 任何新增 critical 规则或该规则扩散即红。UI 修复另立项。
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {
  startSseServer, wireAgentRoutes, wireEmptyConversations,
  sendMessage, pinDefaultTheme, expectDefaultTheme,
} from './helpers/sse-mock';

test.describe('无障碍审计（默认 dark 主题）', () => {
  test('核心对话界面：无 critical 级违规，全量违规落盘记录', async ({ page }, testInfo) => {
    await pinDefaultTheme(page);

    // 完成态对话流：一条消息 + 时间线面板入库，覆盖面最大化
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
    await page.waitForLoadState('networkidle');
    await expectDefaultTheme(page);
    await sendMessage(page, '帮我评估剧本');
    const feed = page.getByTestId('chat-feed');
    await expect(feed).toContainText('剧本评估完成', { timeout: 10000 });

    // 扫描全页（含头部导航/左栏/对话区/输入区）
    const results = await new AxeBuilder({ page }).analyze();

    // 全量违规清单落盘：存量台账（按 impact 聚合 + 逐条 rule/节点数）
    const byImpact: Record<string, number> = {};
    for (const v of results.violations) {
      byImpact[v.impact || 'unknown'] = (byImpact[v.impact || 'unknown'] || 0) + 1;
    }
    const ledger = {
      scannedAt: new Date().toISOString(),
      summary: byImpact,
      violations: results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
      })),
    };
    await testInfo.attach('axe-violations.json', {
      body: JSON.stringify(ledger, null, 2),
      contentType: 'application/json',
    });
    console.log(`[axe] 违规统计：${JSON.stringify(byImpact)}（共 ${results.violations.length} 类）`);
    for (const v of results.violations) {
      console.log(`[axe] ${v.impact} ${v.id} ×${v.nodes.length} — ${v.help}`);
    }

    // critical 存量豁免白名单（2026-08-25 实测锁定）：
    // aria-required-parent ×1 —— 会话标签条 .conv-tab 用了 role="tab" 但父容器无
    // role="tablist"。属存量 UI 债务（修复另立项），白名单钉死：
    // 新增 critical 规则 / 该规则节点扩散都会立即失败
    const CRITICAL_BASELINE: Record<string, number> = {
      'aria-required-parent': 1,
    };
    const critical = results.violations.filter((v) => v.impact === 'critical');
    for (const v of critical) {
      const allowed = CRITICAL_BASELINE[v.id];
      expect(
        allowed,
        `新增 critical 违规（不在存量白名单）：${v.id} ×${v.nodes.length} — ${v.help}`,
      ).toBeDefined();
      expect(
        v.nodes.length,
        `critical 存量违规 ${v.id} 扩散：白名单 ${allowed} 个节点，实测 ${v.nodes.length}`,
      ).toBe(allowed);
    }
    // 白名单中已修复的规则不得残留登记（修复后同步删白名单条目）
    const unresolved = Object.keys(CRITICAL_BASELINE)
      .filter((id) => !critical.some((v) => v.id === id));
    expect(unresolved, `白名单条目已无对应违规，请同步删除：${unresolved.join(', ')}`)
      .toHaveLength(0);
    await handle.close();
  });
});
