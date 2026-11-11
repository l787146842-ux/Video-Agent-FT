/**
 * Skill 助手 store：新建草稿走 create（创作模式），既有 Skill 走 optimize；
 * 流式帧（思考/正文/done）收口为消息，checks 随消息入列供右栏展示自检徽标。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const docsMock = vi.hoisted(() => ({
  getSkillDocs: vi.fn(),
  saveSkillDoc: vi.fn(async () => ({ ok: true, doc: {} })),
  deleteSkillDoc: vi.fn(async () => ({ ok: true })),
  openSkillAssistantStream: vi.fn(),
}));
vi.mock('@/api/docs', () => docsMock);
const streamMock = vi.hoisted(() => ({
  consumeSkillAssistantStream: vi.fn(),
}));
vi.mock('@/lib/skill-assistant-stream', () => streamMock);
vi.mock('@/stores/toast', () => ({
  showToast: vi.fn(), dismissToast: vi.fn(), toasts: [],
}));

const DOC = '# 技能甲\n\n> 调用规则：测试\n\n## 制作流程\n流程正文\n';
let store: typeof import('../skill-studio');

/** 让流式消费桩按脚本回放帧 */
function replay(frames: unknown[]) {
  streamMock.consumeSkillAssistantStream.mockImplementation(
    async (_body: unknown, onFrame: (f: unknown) => void) => {
      for (const f of frames) onFrame(f);
    },
  );
}

beforeEach(async () => {
  vi.clearAllMocks();
  vi.resetModules(); // 单例 store 每用例重建，避免消息/草稿串场
  docsMock.getSkillDocs.mockResolvedValue([
    { slug: 'skill-a', name: '技能甲', description: '描述', content: DOC },
  ]);
  docsMock.openSkillAssistantStream.mockResolvedValue(new ReadableStream());
  store = await import('../skill-studio');
  await store.loadAllDocs();
});

describe('skill-studio 助手流式链路', () => {
  it('编辑既有 Skill → mode=optimize；思考累积 + done 收口', async () => {
    replay([
      { type: 'reasoning_delta', text: '先看结构，' },
      { type: 'reasoning_delta', text: '再改标题。' },
      { type: 'delta', text: '已优化。\n```markdown\n# 新技能甲\n```' },
      {
        type: 'done', reply: '已优化', content: DOC,
        checks: { passed: true, issues: [] },
      },
    ]);
    store.selectSkill('skill-a');
    await store.sendAssistant('改得更具体');

    expect(docsMock.openSkillAssistantStream).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: 'optimize',
        content: DOC,
        messages: [{ role: 'user', content: '改得更具体' }],
      }),
      expect.any(AbortSignal),
    );
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.text).toBe('已优化');
    expect(last.reasoning).toBe('先看结构，再改标题。');
    expect(last.mode).toBe('optimize');
    expect(last.checks).toEqual({ passed: true, issues: [] });
    // 流式气泡收口后清空；busy 复位
    expect(store.assistantStream()).toBeNull();
    expect(store.assistantBusy()).toBe(false);
  });

  it('新建草稿 → mode=create；doc_delta 累积进实时预览，done 提交并清空', async () => {
    store.newDraft();
    const generated = '# 新 Skill\n\n> 调用规则：待补\n';
    const live: string[] = [];
    streamMock.consumeSkillAssistantStream.mockImplementation(
      async (_body: unknown, onFrame: (f: unknown) => void) => {
        onFrame({ type: 'doc_delta', text: '# 新' });
        live.push(store.assistantLiveDoc());
        onFrame({ type: 'doc_delta', text: ' Skill' });
        live.push(store.assistantLiveDoc());
        onFrame({
          type: 'done', reply: '已生成', content: generated,
          checks: { passed: false, issues: ['缺少章节「组装导出」'] },
        });
      },
    );
    await store.sendAssistant('做个宠物广告');

    expect(docsMock.openSkillAssistantStream).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'create' }),
      expect.any(AbortSignal),
    );
    expect(live).toEqual(['# 新', '# 新 Skill']);
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.mode).toBe('create');
    expect(last.checks?.passed).toBe(false);
    expect(last.checks?.issues).toContain('缺少章节「组装导出」');
    expect(store.draftRaw()).toBe(generated);
    // done 后实时预览清空，中间栏换回已提交草稿
    expect(store.assistantLiveDoc()).toBe('');
  });

  it('流断（未收到 done）：保留已收正文、清空实时预览并标注中断', async () => {
    replay([
      { type: 'reasoning_delta', text: '想到一半…' },
      { type: 'delta', text: '正在生成的开头' },
      { type: 'doc_delta', text: '## 制作流程\n半成品' },
    ]);
    store.selectSkill('skill-a');
    const before = store.draftRaw();
    await store.sendAssistant('继续');

    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.text).toContain('正在生成的开头');
    expect(last.text).toContain('流式连接中断');
    expect(last.reasoning).toBe('想到一半…');
    expect(store.draftRaw()).toBe(before);
    // 半成品不落预览，也不留在实时草稿里
    expect(store.assistantLiveDoc()).toBe('');
  });

  it('请求失败只入错误消息，不覆盖草稿', async () => {
    docsMock.openSkillAssistantStream.mockRejectedValue(new Error('offline'));
    store.newDraft();
    const before = store.draftRaw();
    await store.sendAssistant('你好');
    const last = store.assistantMessages()[store.assistantMessages().length - 1];
    expect(last.text).toContain('请求失败');
    expect(store.draftRaw()).toBe(before);
  });
});
