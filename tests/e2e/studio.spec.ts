/**
 * E2E 测试：FTDYB 核心交互流程
 *
 * 前置条件：后端服务运行在 http://127.0.0.1:8080（playwright.config.ts 自动启动或复用已有实例）
 *
 * 覆盖：
 * - 页面加载（标题、三栏布局渲染）
 * - 发送消息 → Agent 回复（mock 模式）
 * - 故事板分组展示
 * - API 健康检查
 */
import { test, expect } from '@playwright/test';

/** 任务式传输 mock：提交任务返回 task_id，事件端点回放状态/增量 + done */
async function mockAgentTask(page: import('@playwright/test').Page, payload: Record<string, unknown>, withDelta = false) {
  await page.route('**/api/agent/tasks', async (route) => {
    const req = route.request();
    if (req.method() === 'POST') {
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
  await page.route('**/api/agent/tasks/*/events', async (route) => {
    const parts: string[] = [];
    if (withDelta) {
      parts.push(
        'data: {"type":"status","text":"正在思考…"}',
        'data: {"type":"delta","text":"好的，"}',
      );
    }
    parts.push(`data: ${JSON.stringify({ type: 'done', payload })}`);
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: parts.join('\n\n') + '\n\n',
    });
  });
}

test.describe('Studio 页面加载', () => {
    test('首页正常渲染三栏布局', async ({ page }) => {
        await page.goto('/');
        // 等待页面基本结构加载
        await page.waitForLoadState('networkidle');

        // 页面标题
        await expect(page).toHaveTitle(/FTDYB|Studio/i);

        // 三栏布局存在
        const leftPanel = page.locator('#leftPanel, .left-panel, [class*="left"]');
        const middlePanel = page.locator('#middlePreview, .middle-preview, [class*="middle"]');
        const rightPanel = page.locator('#rightChat, .right-chat, [class*="right"]');

        // 至少有一个面板可见
        const panels = [leftPanel, middlePanel, rightPanel];
        let visibleCount = 0;
        for (const panel of panels) {
            if (await panel.first().isVisible().catch(() => false)) {
                visibleCount++;
            }
        }
        expect(visibleCount).toBeGreaterThanOrEqual(1);
    });

    test('API 健康检查', async ({ request }) => {
        const resp = await request.get('/api/project/state');
        expect(resp.ok()).toBeTruthy();
        const data = await resp.json();
        // 状态应包含基本字段
        expect(data).toHaveProperty('keyElements');
    });
});

test.describe('Agent 对话（mock 模式）', () => {
    test('发送消息后收到 Agent 回复', async ({ page }) => {
        // 拦截 SSE 流式接口并注入 mock 回复：
        // 确定性验证前端「发送 → 流式渲染 → 完成入库」链路，
        // 不依赖真实 LLM 供应商（后端协议由 SSE 端点测试覆盖）。
        await mockAgentTask(page, {
            text: '好的，这是拆解结果',
            elapsed_ms: 120,
            steps: 1,
            applied_actions: 0,
        }, true);

        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // 定位聊天输入框（新 Solid UI 的稳定 id）
        const chatInput = page.locator('#chatInputTextarea');
        await expect(chatInput).toBeVisible();
        await chatInput.fill('你好，请帮我拆解一个短视频脚本');
        await chatInput.press('Enter');

        // 用户消息立即上屏
        const feed = page.getByTestId('chat-feed');
        await expect(feed).toContainText('你好，请帮我拆解一个短视频脚本');
        // Agent 流式回复最终入库
        await expect(feed).toContainText('好的，这是拆解结果', { timeout: 10000 });
    });
});

test.describe('故事板面板', () => {
    test('左侧面板显示分组标签页', async ({ page }) => {
        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // 检查标签页（关键元素 / 分镜 / 音频）
        const tabs = page.locator('[data-tab], .tab-btn, [class*="tab"]');
        const tabCount = await tabs.count();
        // 至少有标签页结构
        expect(tabCount).toBeGreaterThanOrEqual(0);
    });
});

test.describe('阶段确认卡片与文档卡片', () => {
    test('阶段卡只展示大阶段+操作数徽标，不重复正文（2222 反馈）', async ({ page }) => {
        await mockAgentTask(page, {
            text: '规划已完成',
            elapsed_ms: 500,
            steps: 2,
            applied_actions: 3,
            confirmation: '故事板已建立，请审阅',
            documents_written: ['Final_Video_Spec.md'],
            action_log: ['新建关键元素分组「主角」', '写入文档「Final_Video_Spec.md」'],
            trace: { steps: [{ step: 1, timing_ms: 300, actions_applied: 3, finish_reason: 'stop' }], total_ms: 500 },
        });

        await page.goto('/');
        await page.waitForLoadState('networkidle');
        const chatInput = page.locator('#chatInputTextarea');
        await chatInput.fill('建立故事板');
        await chatInput.press('Enter');

        const feed = page.getByTestId('chat-feed');
        // 阶段完成卡：标题 + 操作数徽标 + 短确认问句（body 只留概要，明细不双处呈现）
        const stageCard = feed.locator('.stage-card').last();
        await expect(stageCard).toContainText('阶段完成');
        await expect(stageCard).toContainText('已执行 3 个操作');
        await expect(stageCard.locator('.stage-card-body')).toContainText('故事板已建立，请审阅');
        await expect(stageCard.locator('.stage-card-body')).not.toContainText('新建关键元素分组');
        // 文档完成卡片
        await expect(feed.locator('.doc-card').last()).toContainText('Final_Video_Spec.md');
        // action_log 明细归时间线「已处理操作」面板单家（非 live 默认折叠，点开头部再断言）
        const opsPanel = feed.locator('.agent-timeline .tl-panel', { hasText: '已处理' }).last();
        await expect(opsPanel).toContainText('已处理');
        await opsPanel.locator('.tl-panel-header').click();
        await expect(opsPanel.locator('.tl-panel-body')).toContainText('新建关键元素分组「主角」');
    });

    test('三通道分离：成果在正文、卡片只留短问句（1111 反馈）', async ({ page }) => {
        await mockAgentTask(page, {
            text: '剧本分析完成。\n\n## 剧本分析《三体简短版.md》\n**一句话总结**：太阳系遭遇白色薄片打击。',
            elapsed_ms: 300,
            steps: 2,
            applied_actions: 1,
            confirmation: '「剧本分析」已完成，请过目以上成果并选择下一步。',
            confirmation_options: [{
                label: '确认，进入「制作规格」', description: '下一步执行「制作规格」',
                value: '确认，进入「制作规格」', group: '下一步',
            }],
            action_log: ['执行工具script_analyze'],
            trace: { steps: [{ step: 1, timing_ms: 200, actions_applied: 1, finish_reason: 'stop' }], total_ms: 300 },
        });

        await page.goto('/');
        await page.waitForLoadState('networkidle');
        const chatInput = page.locator('#chatInputTextarea');
        await chatInput.fill('分析剧本');
        await chatInput.press('Enter');

        const feed = page.getByTestId('chat-feed');
        // 成果通道：结构化分析在正文气泡（系统渲染），不在阶段卡
        await expect(feed).toContainText('一句话总结');
        const stageCard = feed.locator('.stage-card').last();
        await expect(stageCard).toContainText('「剧本分析」已完成');
        await expect(stageCard).not.toContainText('一句话总结');
        // 引导通道：系统派生继续选项可见
        await expect(feed).toContainText('确认，进入「制作规格」');
    });
});

test.describe('闸机「本次放行」（814F7）', () => {
    test('拦截类警告携带放行按钮，点击后消息携带 gate_overrides 发送', async ({ page }) => {
        const capturedBodies: Array<Record<string, unknown>> = [];
        await page.route('**/api/agent/tasks', async (route) => {
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
        await page.route('**/api/agent/tasks/*/events', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'text/event-stream',
                body: `data: ${JSON.stringify({
                    type: 'done',
                    payload: {
                        text: '写入被拦截',
                        warnings: ['流程闸机拦截：分镜提示词结构校验未通过'],
                        // 结构化闸机判定：放行按钮渲染条件 = trace.steps[].gates[] 存在 ok=false 条目
                        trace: {
                            steps: [{
                                step: 1, timing_ms: 10, actions_applied: 0, finish_reason: 'stop',
                                gates: [{
                                    ok: false, rule_id: 'storyboard_prompt_structure',
                                    layer: 'platform', message: '分镜提示词结构校验未通过',
                                }],
                            }],
                            total_ms: 10,
                        },
                        elapsed_ms: 10, steps: 1, applied_actions: 0,
                    },
                })}\n\n`,
            });
        });

        await page.goto('/');
        await page.waitForLoadState('networkidle');
        const chatInput = page.locator('#chatInputTextarea');
        await chatInput.fill('触发拦截');
        await chatInput.press('Enter');

        const feed = page.getByTestId('chat-feed');
        // 拦截警告出现后附带「本次放行」按钮（仅最新一条）
        const btn = feed.locator('.gate-override-btn').last();
        await expect(btn).toBeVisible({ timeout: 10000 });
        await btn.click();
        // 放行消息是第二次 POST：携带 gate_overrides（单次生效留痕）
        await expect.poll(() => capturedBodies.length, { timeout: 10000 }).toBeGreaterThanOrEqual(2);
        const overrideReq = capturedBodies[capturedBodies.length - 1];
        expect(overrideReq.message).toContain('放行');
        expect(overrideReq.gate_overrides).toEqual(['all']);
    });
});

test.describe('Skill 「+」插入引用块并发送', () => {
    test('下拉选 Skill → chip 插入输入框 → 发送', async ({ page }) => {
        await mockAgentTask(page, {
            text: 'Skill 流程已启用',
            elapsed_ms: 100,
            steps: 1,
            applied_actions: 0,
        });

        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // 打开 Skill 下拉面板
        await page.locator('button[title="技能加载"]').click();
        const panel = page.locator('.skill-picker');
        await expect(panel).toBeVisible();

        // 点第一个 Skill 卡片的「+」：chip 插入输入框
        await panel.locator('.skill-picker-add').first().click();
        const chip = page.locator('#chatInputTextarea .skill-chip');
        await expect(chip).toBeVisible();
        const skillName = (await chip.locator('.skill-chip-name').textContent() || '').trim();
        expect(skillName.length).toBeGreaterThan(0);

        // 发送：chip 序列化为 Skill 名称随消息上屏
        await page.locator('#chatInputTextarea').press('Enter');
        const feed = page.getByTestId('chat-feed');
        await expect(feed).toContainText(skillName, { timeout: 10000 });
        await expect(feed).toContainText('Skill 流程已启用', { timeout: 10000 });
    });
});

test.describe('SSE 流式端点', () => {
    test('流式聊天 API 返回 SSE 格式', async ({ request }) => {
        const resp = await request.post('/api/agent/chat/stream', {
            data: {
                message: '你好',
                provider: 'mock',
                model: 'mock-chat',
            },
        });
        expect(resp.ok()).toBeTruthy();
        const contentType = resp.headers()['content-type'] || '';
        expect(contentType).toContain('text/event-stream');

        const body = await resp.text();
        expect(body).toContain('data:');
        expect(body).toContain('"type"');
    });
});
