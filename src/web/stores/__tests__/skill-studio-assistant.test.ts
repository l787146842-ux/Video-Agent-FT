/**
 * Skill 助手 store：新建草稿走 create（创作模式），既有 Skill 走 optimize；
 * 后端 checks 随消息入列，供右栏展示「通过/未通过项目规范自检」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const docsMock = vi.hoisted(() => ({
  getSkillDocs: vi.fn(),
  saveSkillDoc: vi.fn(async () => ({ ok: true, doc: {} })),
  deleteSkillDoc: vi.fn(async () => ({ ok: true })),
  assistantSkillChat: vi.fn(),
}));
vi.mock('@/api/docs', () => docsMock);
vi.mock('@/stores/toast', () => ({
  showToast: vi.fn(), dismissToast: vi.fn(), toasts: [],
}));

const DOC = '# 技能甲\n\n> 调用规则：测试\n\n## 流程规划\n流程正文\n';
let store: typeof import('../skill-studio');

beforeEach(async () => {
  vi.clearAllMocks();
  vi.resetModules(); // 单例 store 每用例重建，避免消息/草稿串场
  docsMock.getSkillDocs.mockResolvedValue([
    { slug: 'skill-a', name: '技能甲', description: '描述', content: DOC },
  ]);
  store = await import('../skill-studio');
  await store.loadAllDocs();
});

describe('skill-studio 助手创作/优化模式', () => {
  it('编辑既有 Skill → mode=optimize；checks 随消息入列', async () => {
    docsMock.assistantSkillChat.mockResolvedValue({
      reply: '已优化', content: DOC, checks: { passed: true, issues: [] },
    });
    store.selectSkill('skill-a');
    await store.sendAssistant('改得更具体');

    expect(docsMock.assistantSkillChat).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'optimize',
      content: DOC,
      messages: [{ role: 'user', content: '改得更具体' }],
    }));
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.text).toBe('已优化');
    expect(last.mode).toBe('optimize');
    expect(last.checks).toEqual({ passed: true, issues: [] });
  });

  it('新建草稿 → mode=create；自检问题随消息入列', async () => {
    store.newDraft();
    const generated = '# 新 Skill\n\n> 调用规则：待补\n';
    docsMock.assistantSkillChat.mockResolvedValue({
      reply: '已生成', content: generated,
      checks: { passed: false, issues: ['缺少章节「组装导出」'] },
    });
    await store.sendAssistant('做个宠物广告');

    expect(docsMock.assistantSkillChat).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'create',
    }));
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.mode).toBe('create');
    expect(last.checks?.passed).toBe(false);
    expect(last.checks?.issues).toContain('缺少章节「组装导出」');
    expect(store.draftRaw()).toBe(generated);
  });

  it('请求失败只入错误消息，不覆盖草稿', async () => {
    docsMock.assistantSkillChat.mockRejectedValue(new Error('offline'));
    store.newDraft();
    const before = store.draftRaw();
    await store.sendAssistant('你好');
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.text).toContain('请求失败');
    expect(store.draftRaw()).toBe(before);
  });
});
