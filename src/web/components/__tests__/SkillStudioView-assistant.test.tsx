/**
 * Skill 工作台右栏显隐（2026-10-20 用户裁决）：
 * 只有「新建」与「编辑」两种状态才挂出 Skill 优化助手；
 * 纯查看保持两栏（左列表 + 中结构化视图），取消编辑后右栏收回。
 * 同时锁定新建草稿的通用标题式骨架（frontmatter + H1 + 六个二级标题，
 * 含制作流程与参考资料）。
 */
import { render, fireEvent, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SkillStudioView from '../skills/SkillStudioView';
import {
  loadAllDocs, selectSkill, setStudioEditing,
} from '@/stores/skill-studio';

const DOC = [
  '# 技能甲',
  '',
  '> 调用规则：测试用',
  '',
  '## 流程规划',
  '流程正文',
  '',
].join('\n');

const DOC_B = [
  '# 技能乙',
  '',
  '> 调用规则：测试用乙',
  '',
  '## 流程规划',
  '流程正文乙',
  '',
].join('\n');

const docsMock = vi.hoisted(() => ({
  getSkillDocs: vi.fn(async () => ([
    { slug: 'skill-a', name: '技能甲', description: '描述甲', content: '' },
  ])),
  // 记录落盘入参：新建模板的最终形态（通用标题式）在此断言
  saveSkillDoc: vi.fn(async (slug: string, content: string) => ({ ok: true, doc: {}, slug, content })),
  deleteSkillDoc: vi.fn(async () => ({ ok: true })),
  assistantSkillChat: vi.fn(async () => ({ reply: '', content: null })),
}));
vi.mock('@/api/docs', () => docsMock);

vi.mock('@/stores/studio', () => ({ refreshSkills: vi.fn(async () => {}) }));

vi.mock('@/stores/toast', () => ({
  showToast: vi.fn(), dismissToast: vi.fn(), toasts: [],
}));

// 助手面板本体不参与本批断言（其依赖聊天/用量 API），只验证挂载时机
vi.mock('@/components/skills/SkillAssistantPanel', () => ({
  SkillAssistantPanel: () => <div data-testid="assistant-panel" />,
}));

function buttonByText(root: HTMLElement, text: string): HTMLButtonElement {
  const hit = [...root.querySelectorAll('button')]
    .find((b) => (b.textContent || '').includes(text));
  if (!hit) throw new Error(`button not found: ${text}`);
  return hit as HTMLButtonElement;
}

const assistantCol = (root: HTMLElement) => root.querySelector('.skst-assistant');

beforeEach(async () => {
  vi.clearAllMocks();
  docsMock.getSkillDocs.mockImplementation(async () => ([
    { slug: 'skill-a', name: '技能甲', description: '描述甲', content: DOC },
    { slug: 'skill-b', name: '技能乙', description: '描述乙', content: DOC_B },
  ]));
  await loadAllDocs();
  selectSkill('skill-a');
  setStudioEditing(false);
});

describe('SkillStudioView 助手右栏只在编辑/新建时出现', () => {
  it('查看态两栏；点编辑弹出助手；取消后收回', async () => {
    const { container } = render(() => <SkillStudioView />);
    // 两栏：左列表 + 中结构化视图，没有右栏与拖拽分界
    expect(container.querySelector('.skst-list')).not.toBeNull();
    expect(container.querySelector('.skst-center')).not.toBeNull();
    expect(assistantCol(container)).toBeNull();
    expect(container.querySelector('.splitter-v')).toBeNull();

    fireEvent.click(buttonByText(container, '编辑'));
    await waitFor(() => expect(assistantCol(container)).not.toBeNull());
    expect(container.querySelector('[data-testid="assistant-panel"]')).not.toBeNull();
    expect(container.querySelector('.splitter-v')).not.toBeNull();

    fireEvent.click(buttonByText(container, '取消'));
    await waitFor(() => expect(assistantCol(container)).toBeNull());
    expect(container.querySelector('.splitter-v')).toBeNull();
  });

  it('新建草稿带助手 + 通用骨架齐全；保存后回到两栏', async () => {
    const { container } = render(() => <SkillStudioView />);
    fireEvent.click(buttonByText(container, '新建'));
    await waitFor(() => expect(assistantCol(container)).not.toBeNull());

    // 通用骨架：模板标题原文即章节名
    const titles = [...container.querySelectorAll('.sks-h2')].map((el) => el.textContent);
    for (const title of ['三、制作流程', '四、结构与素材', '六、参考资料']) {
      expect(titles.some((t) => (t || '').includes(title))).toBe(true);
    }

    // 保存落盘后「新建」态结束：不再是未落盘草稿，右栏收回（仍是两栏）
    await fireEvent.click(buttonByText(container, '保存'));
    await waitFor(() => expect(assistantCol(container)).toBeNull());
    expect(docsMock.saveSkillDoc).toHaveBeenCalledTimes(1);
    // 落盘内容：Markdown 标题式主文档 + frontmatter
    const saved = String(docsMock.saveSkillDoc.mock.calls[0]?.[1] ?? '');
    expect(saved).toContain('## 三、制作流程');
    expect(saved).toMatch(/^# 新 Skill/m);
    expect(saved).not.toContain('<planner>');
  });

  it('编辑中切换到另一个 Skill：自动退出编辑态并收回右栏', async () => {
    const { container } = render(() => <SkillStudioView />);
    fireEvent.click(buttonByText(container, '编辑'));
    await waitFor(() => expect(assistantCol(container)).not.toBeNull());

    fireEvent.click(container.querySelectorAll('.skst-item')[1] as HTMLElement);
    await waitFor(() => expect(assistantCol(container)).toBeNull());
    expect(container.querySelector('.skst-center')?.textContent).toContain('技能乙');
  });
});
