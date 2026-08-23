/**
 * E2E：设置页冒烟（任务 #13 F-7）
 *
 * 场景：顶栏入口打开全局设置（/global-settings），关键区块可见；
 * 模型分层策略的角色推理档位可切换且不报错（真实后端 PUT 往返，
 * 测试结束回拨原值保持环境幂等）。
 */
import { test, expect } from '@playwright/test';

test.describe('设置页冒烟', () => {
  test('打开全局设置：关键区块可见，模型角色档位可切换不报错', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    // 捕获运行时设置读写（continue 走真实后端；记录初值用于结束时回拨）
    const putBodies: Array<Record<string, unknown>> = [];
    let initialThinking = '';
    await page.route(/\/api\/settings\/runtime/, async (route) => {
      const req = route.request();
      if (req.method() === 'PUT') putBodies.push(req.postDataJSON());
      const res = await route.fetch();
      if (req.method() === 'GET' && res.ok()) {
        try {
          const body = await res.json();
          initialThinking = (body?.model_policy?.summary?.thinking_level || '') as string;
        } catch { /* 非 JSON 忽略 */ }
      }
      await route.fulfill({ response: res });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 顶栏入口打开全局设置
    await page.getByLabel('全局模型选择设置').click();
    await expect(page).toHaveURL(/\/global-settings$/);
    await expect(page.locator('.gs-title')).toHaveText('全局模型设置');

    // 关键区块可见
    for (const section of ['出图默认', '出视频默认', '聊天框出图', '自动切换', '模型分层策略', '运行成本']) {
      await expect(page.locator('.gs-section h3', { hasText: section }))
        .toBeVisible({ timeout: 10000 });
    }

    // 模型角色档位可切换：摘要角色推理档位 → 高（真实 PUT 往返后仍保持）
    const summarySelect = page.getByLabel('摘要推理档位');
    await expect(summarySelect).toBeVisible({ timeout: 10000 });
    await summarySelect.selectOption('high');
    await expect(summarySelect).toHaveValue('high', { timeout: 10000 });
    await expect.poll(() => putBodies.length, { timeout: 10000 }).toBeGreaterThanOrEqual(1);
    const put = putBodies[putBodies.length - 1];
    const policy = (put.model_policy || {}) as Record<string, { thinking_level?: string }>;
    expect(policy.summary?.thinking_level).toBe('high');

    // 回拨原值（幂等：不改变环境既有设置）
    await summarySelect.selectOption(initialThinking);
    await expect(summarySelect).toHaveValue(initialThinking, { timeout: 10000 });

    // 全程无未捕获异常
    expect(pageErrors).toEqual([]);
  });
});
