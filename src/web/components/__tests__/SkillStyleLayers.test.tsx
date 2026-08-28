/**
 * SkillStyleLayers 风格层多选区（任务 #11：1 pipeline 可选 + N style 层）。
 *
 * 钉死：① 仅渲染 kind=style 的 Skill（流程型不进本区）；
 * ② 勾选切换全量替换式清单（乐观写 + 快照口径）；
 * ③ 当前主流程同 slug 时点击提示互斥、不写清单；
 * ④ 眼睛按钮走预览回调且不触发勾选。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SkillStyleLayers } from '../right-panel/SkillStyleLayers';
import { setState, state } from '@/stores/studio';
import { t } from '@/lib/locale';
import type { Skill } from '@/types';

const apiMock = vi.hoisted(() => ({
  setActiveSkillApi: vi.fn(async () => ({})),
  setActiveStyleLayersApi: vi.fn(async () => ({})),
}));
vi.mock('@/api/docs', () => apiMock);

const toastMock = vi.hoisted(() => vi.fn());
vi.mock('@/stores/toast', () => ({
  showToast: (...args: unknown[]) => toastMock(...args),
  dismissToast: vi.fn(),
  toasts: [],
}));

const SKILLS: Skill[] = [
  { id: 'doc:flow-a', name: '流程甲', description: '', system_prompt: '', source: 'doc', slug: 'flow-a', kind: 'pipeline' },
  { id: 'doc:style-a', name: '风格甲', description: '风格描述甲', system_prompt: '', source: 'doc', slug: 'style-a', kind: 'style' },
  { id: 'doc:style-b', name: '风格乙', description: '', system_prompt: '', source: 'doc', slug: 'style-b', kind: 'style' },
];

describe('SkillStyleLayers 风格层多选区', () => {
  beforeEach(() => {
    apiMock.setActiveStyleLayersApi.mockClear();
    toastMock.mockClear();
    setState('skills', SKILLS);
    setState('activeSkill', null);
    setState('activeStyleSkills', []);
  });
  afterEach(() => {
    setState('skills', []);
    setState('activeStyleSkills', []);
    setState('activeSkill', null);
  });

  it('仅渲染 kind=style 的 Skill（含标题区文案）', () => {
    const { container } = render(() => <SkillStyleLayers onPreview={() => {}} />);
    expect(container.querySelector('.skill-picker-style-title')?.textContent)
      .toBe(t('rp.skill.styleSection'));
    const cards = container.querySelectorAll('.skill-picker-card.skill-picker-style');
    expect(cards).toHaveLength(2);
    expect(container.textContent).toContain('风格甲');
    expect(container.textContent).not.toContain('流程甲');
  });

  it('无风格型 Skill 时整区不渲染', () => {
    setState('skills', [SKILLS[0]]);
    const { container } = render(() => <SkillStyleLayers onPreview={() => {}} />);
    expect(container.querySelector('.skill-picker-style-header')).toBeNull();
  });

  it('点击卡片勾选为风格层：全量替换式下发 + 勾选态点亮', async () => {
    const { container } = render(() => <SkillStyleLayers onPreview={() => {}} />);
    const cardA = container.querySelectorAll('.skill-picker-card.skill-picker-style')[0] as HTMLElement;
    await fireEvent.click(cardA);
    expect(apiMock.setActiveStyleLayersApi).toHaveBeenCalledWith({ slugs: ['style-a'] });
    expect(state.activeStyleSkills).toEqual(['style-a']);
    expect(cardA.classList.contains('active')).toBe(true);
    expect(cardA.querySelector('.skill-picker-check svg')).toBeTruthy();
  });

  it('当前主流程同 slug 时拒绝勾选并提示互斥', async () => {
    setState('activeSkill', { slug: 'style-a', source: 'user' });
    const { container } = render(() => <SkillStyleLayers onPreview={() => {}} />);
    const cardA = container.querySelectorAll('.skill-picker-card.skill-picker-style')[0] as HTMLElement;
    await fireEvent.click(cardA);
    expect(apiMock.setActiveStyleLayersApi).not.toHaveBeenCalled();
    expect(state.activeStyleSkills).toEqual([]);
    expect(toastMock).toHaveBeenCalledWith(
      t('rp.skill.styleAsPrimaryTip', { name: '风格甲' }), 'info');
  });

  it('眼睛按钮触发预览回调且不改变勾选态', async () => {
    const onPreview = vi.fn();
    const { container } = render(() => <SkillStyleLayers onPreview={onPreview} />);
    const eye = container.querySelectorAll('.skill-picker-card.skill-picker-style .skill-picker-eye')[1] as HTMLElement;
    await fireEvent.click(eye);
    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onPreview.mock.calls[0][0].id).toBe('doc:style-b');
    expect(apiMock.setActiveStyleLayersApi).not.toHaveBeenCalled();
  });
});
