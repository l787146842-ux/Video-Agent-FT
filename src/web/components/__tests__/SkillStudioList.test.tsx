/**
 * SkillStudioList 启停开关（批7/对齐 Flova 卡片开关）：
 * 左栏每卡渲染开关（role=switch）；初始启停由
 * runtime_settings.skills_disabled 决定、停用卡置灰；
 * 点击开关发 PUT skills_disabled（加入=停用），即时反映并置灰。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SkillStudioList } from '../skills/SkillStudioList';
import { loadAllDocs } from '@/stores/skill-studio';
import { ensureGlobalSettings } from '@/stores/global-settings';

const docsMock = vi.hoisted(() => ({
  getSkillDocs: vi.fn(async () => ([
    { slug: 'skill-a', name: '技能甲', description: '描述甲', content: '' },
    { slug: 'skill-b', name: '技能乙', description: '', content: '' },
  ])),
}));
vi.mock('@/api/docs', () => docsMock);

const agentMock = vi.hoisted(() => ({
  getRuntimeSettings: vi.fn(async () => ({
    skills_disabled: ['skill-b'],
    // 批 B：RuntimeSettings 新增必填字段，mock 同步补齐（默认档）
    execution_preference: 'confirm_before_gen',
  })),
  setRuntimeSettings: vi.fn(async (body: { skills_disabled?: string[] }) => (
    { skills_disabled: body.skills_disabled ?? [], execution_preference: 'confirm_before_gen' }
  )),
}));
vi.mock('@/api/agent', () => agentMock);

const toastMock = vi.hoisted(() => vi.fn());
vi.mock('@/stores/toast', () => ({
  showToast: (...args: unknown[]) => toastMock(...args),
  dismissToast: vi.fn(),
  toasts: [],
}));

beforeEach(async () => {
  vi.clearAllMocks();
  await loadAllDocs();
  await ensureGlobalSettings();
});

describe('SkillStudioList 启停开关（批7）', () => {
  it('每卡渲染开关：初始启停按 skills_disabled，停用卡置灰', () => {
    const { container } = render(() => <SkillStudioList onCollapse={() => {}} />);
    const switches = container.querySelectorAll('button.skst-switch');
    expect(switches).toHaveLength(2);
    expect(switches[0].getAttribute('aria-checked')).toBe('true');
    expect(switches[0].classList.contains('on')).toBe(true);
    expect(switches[1].getAttribute('aria-checked')).toBe('false');
    expect(container.querySelectorAll('.skst-item.off')).toHaveLength(1);
  });

  it('点击开关发 PUT 停用（slug 加入），即时反映且卡片置灰', async () => {
    const { container } = render(() => <SkillStudioList onCollapse={() => {}} />);
    const switchA = container.querySelectorAll('button.skst-switch')[0];
    await fireEvent.click(switchA);
    expect(agentMock.setRuntimeSettings).toHaveBeenCalledWith({
      skills_disabled: ['skill-b', 'skill-a'],
    });
    expect(switchA.getAttribute('aria-checked')).toBe('false');
    expect(container.querySelectorAll('.skst-item.off')).toHaveLength(2);
  });
});
