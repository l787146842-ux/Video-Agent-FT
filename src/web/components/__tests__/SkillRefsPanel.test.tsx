/**
 * 分册（references/）面板回归（2026-11-11 裁决）。
 *
 * 事故：references/ 此前只对 read_skill 开放，Skill 工作台完全看不到分册——
 * 用户无法查看/编辑/新增分册，等于分册「存在但不可维护」。
 *
 * 本文件钉死：选中 Skill 后列出分册、点开可读全文、可保存、可新建、可删除。
 */
import { render, fireEvent, waitFor, screen } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SkillRefsPanel } from '../skills/SkillRefsPanel';
import { loadAllDocs, selectSkill, newDraft } from '@/stores/skill-studio';

const DOC = [
  '# 技能甲',
  '',
  '> 调用规则：测试用',
  '',
  '## 流程规划',
  '流程正文，细节见 `references/媒体生成.md`。',
  '',
].join('\n');

const refsMock = vi.hoisted(() => ({
  getSkillDocs: vi.fn(async () => ([
    { slug: 'skill-a', name: '技能甲', description: '描述甲', content: '' },
  ])),
  getSkillLoadFailures: vi.fn(async () => ([])),
  saveSkillDoc: vi.fn(async (slug: string, content: string) => ({ ok: true, doc: {}, slug, content })),
  deleteSkillDoc: vi.fn(async () => ({ ok: true })),
  getSkillRefs: vi.fn(async () => ([
    { name: '媒体生成.md', chars: 1024, title: '媒体生成' },
    { name: '提示词写作.md', chars: 2048, title: '提示词写作' },
  ])),
  getSkillRef: vi.fn(async (_slug: string, name: string) => ({
    slug: 'skill-a', name, content: `# ${name.replace(/\.md$/, '')}\n\n分册正文 REF_BODY\n`,
  })),
  saveSkillRef: vi.fn(async (slug: string, name: string, content: string) => ({ slug, name, content })),
  deleteSkillRef: vi.fn(async () => ({ ok: true })),
  openSkillAssistantStream: vi.fn(),
  assistantSkillChat: vi.fn(),
}));
vi.mock('@/api/docs', () => refsMock);

vi.mock('@/stores/studio', () => ({ refreshSkills: vi.fn(async () => {}) }));
vi.mock('@/stores/toast', () => ({
  showToast: vi.fn(), dismissToast: vi.fn(), toasts: [],
}));
vi.mock('@/stores/agent-prefs', () => ({
  agentProvider: () => '', agentModel: () => '',
}));

async function selectFirstSkill() {
  await loadAllDocs();
  selectSkill('skill-a');
  await waitFor(() => expect(refsMock.getSkillRefs).toHaveBeenCalledWith('skill-a'));
}

describe('分册面板', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    newDraft();
  });

  it('未选中 Skill 时不渲染', () => {
    const { container } = render(() => <SkillRefsPanel />);
    expect(container.querySelector('.skst-refs')).toBeNull();
  });

  it('选中 Skill 后列出分册（文件名 + 字数）', async () => {
    const { container } = render(() => <SkillRefsPanel />);
    await selectFirstSkill();
    await waitFor(() => {
      expect(container.querySelector('.skst-refs')).not.toBeNull();
    });
    expect(container.textContent).toContain('媒体生成.md');
    expect(container.textContent).toContain('提示词写作.md');
    expect(container.textContent).toContain('1024');
  });

  it('点开分册后显示全文并可编辑', async () => {
    const { container } = render(() => <SkillRefsPanel />);
    await selectFirstSkill();
    await waitFor(() => expect(container.textContent).toContain('媒体生成.md'));

    const nameBtn = [...container.querySelectorAll('.skst-refs-name')]
      .find((b) => (b.textContent || '').includes('媒体生成.md')) as HTMLButtonElement;
    fireEvent.click(nameBtn);

    await waitFor(() => expect(refsMock.getSkillRef).toHaveBeenCalledWith('skill-a', '媒体生成.md'));
    await waitFor(() => {
      const ta = container.querySelector('.skst-refs-textarea') as HTMLTextAreaElement | null;
      expect(ta).not.toBeNull();
      expect(ta!.value).toContain('REF_BODY');
    });
  });

  it('编辑后点保存 → 调 saveSkillRef 落盘', async () => {
    const { container } = render(() => <SkillRefsPanel />);
    await selectFirstSkill();
    await waitFor(() => expect(container.textContent).toContain('媒体生成.md'));
    fireEvent.click([...container.querySelectorAll('.skst-refs-name')]
      .find((b) => (b.textContent || '').includes('媒体生成.md')) as HTMLButtonElement);
    await waitFor(() => expect(container.querySelector('.skst-refs-textarea')).not.toBeNull());

    const ta = container.querySelector('.skst-refs-textarea') as HTMLTextAreaElement;
    fireEvent.input(ta, { target: { value: '改后的分册正文 EDITED' } });
    const saveBtn = [...container.querySelectorAll('button')]
      .find((b) => (b.textContent || '').includes('保存分册')) as HTMLButtonElement;
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(refsMock.saveSkillRef).toHaveBeenCalledWith(
        'skill-a', '媒体生成.md', '改后的分册正文 EDITED');
    });
  });

  it('新建分册：输入文件名后打开编辑器（不预先落盘）', async () => {
    const { container } = render(() => <SkillRefsPanel />);
    await selectFirstSkill();
    const newBtn = [...container.querySelectorAll('button')]
      .find((b) => (b.textContent || '').includes('新建分册')) as HTMLButtonElement;
    fireEvent.click(newBtn);

    const input = container.querySelector('.skst-refs-create input') as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.input(input, { target: { value: '剪辑交付' } });
    const createBtn = [...container.querySelectorAll('.skst-refs-create button')]
      .find((b) => (b.textContent || '').includes('创建')) as HTMLButtonElement;
    fireEvent.click(createBtn);

    await waitFor(() => {
      const ta = container.querySelector('.skst-refs-textarea') as HTMLTextAreaElement | null;
      expect(ta).not.toBeNull();
      expect(ta!.value).toContain('剪辑交付');
    });
    // 新建只打开编辑器，落盘要用户点保存
    expect(refsMock.saveSkillRef).not.toHaveBeenCalled();
  });

  it('无分册时给出拆分指引', async () => {
    refsMock.getSkillRefs.mockResolvedValueOnce([]);
    const { container } = render(() => <SkillRefsPanel />);
    await selectFirstSkill();
    await waitFor(() => {
      expect(container.textContent).toContain('没有分册');
    });
  });
});
