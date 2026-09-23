/**
 * P2-H：分镜时长独立徽标（.sb-duration）防回归断言
 * ① shot + duration → .sb-duration textContent 为时长字符串，标题 span 不含括号/时长
 * ② shot + 无 duration → .sb-duration 为 null
 * ③ 非 shot（keyElement / audio）→ .sb-duration 为 null
 * ④ 双击 .sb-duration 不进入标题编辑态（.sb-title-input 仍为 null）
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

/** 旁路子件打桩（同 GroupCard-badge.test.tsx） */
vi.mock('@/components/left-panel/DraftCard', () => ({ DraftCard: () => null }));
vi.mock('@/components/left-panel/group-card/ShotRefsChips', () => ({ ShotRefsChips: () => null }));
vi.mock('@/components/left-panel/group-card/GroupDescEditor', () => ({ GroupDescEditor: () => null }));
vi.mock('@/components/left-panel/group-card/GroupAdjustBox', () => ({ GroupAdjustBox: () => null }));
vi.mock('@/components/left-panel/group-card/ShotDescEditor', () => ({ ShotDescEditor: () => null }));
vi.mock('@/lib/agent-actions', () => ({ sendUserMessage: vi.fn() }));

import { GroupCard } from '../left-panel/GroupCard';
import type { AnyGroup, AudioGroup, DraftType, KeyElementGroup, ShotGroup } from '@/types';

const noop = () => {};

function setup(group: AnyGroup, type: DraftType) {
  return render(() => (
    <GroupCard
      group={group}
      type={type}
      index={1}
      dragOver={false}
      onDragStart={noop}
      onDragOver={noop}
      onDragLeave={noop}
      onDrop={noop}
      onDragEnd={noop}
      onContextMenu={noop}
    />
  ));
}

describe('.sb-duration 独立时长徽标（P2-H）', () => {
  it('shot + duration → .sb-duration textContent 为时长字符串，标题 span 不含括号', () => {
    const group: ShotGroup = {
      id: 'g1',
      title: '开场',
      duration: '5s',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'shot');
    const badge = container.querySelector('.sb-duration');
    expect(badge).toBeTruthy();
    expect((badge!.textContent || '').trim()).toBe('5s');

    // 标题 span 不含时长字符串，不含括号
    const titleSpan = container.querySelector('.sb-title span[title="双击编辑标题"]');
    expect(titleSpan).toBeTruthy();
    const spanText = titleSpan!.textContent || '';
    expect(spanText).not.toContain('5s');
    expect(spanText).not.toContain('(');
    expect(spanText).not.toContain(')');
  });

  it('shot + 无 duration → .sb-duration 为 null', () => {
    const group: ShotGroup = {
      id: 'g2',
      title: '过场',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'shot');
    expect(container.querySelector('.sb-duration')).toBeNull();
  });

  it('非 shot（keyElement）→ .sb-duration 为 null', () => {
    const group: KeyElementGroup = {
      id: 'g3',
      title: '月球',
      drafts: [{ id: 'd1', label: '草稿 1', tag: '手动', mediaType: 'image', imgUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'keyElement');
    expect(container.querySelector('.sb-duration')).toBeNull();
  });

  it('非 shot（audio）→ .sb-duration 为 null', () => {
    const group: AudioGroup = {
      id: 'g4',
      title: '配乐',
      drafts: [{ id: 'd1', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'audio');
    expect(container.querySelector('.sb-duration')).toBeNull();
  });

  it('双击 .sb-duration 不进入标题编辑态（.sb-title-input 仍为 null）；shot 进入摘要编辑态（flova 对齐批）', () => {
    const group: ShotGroup = {
      id: 'g5',
      title: '转场',
      duration: '3s',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'shot');
    const badge = container.querySelector('.sb-duration') as HTMLElement;
    expect(badge).toBeTruthy();
    fireEvent.dblClick(badge);
    // 徽标双击不应触发标题编辑
    expect(container.querySelector('.sb-title-input')).toBeNull();
    // 标题 span 仍然存在（未进入编辑态）
    expect(container.querySelector('.sb-title span[title="双击编辑标题"]')).toBeTruthy();
    // flova 对齐批（2026-09-17）：shot 徽标位双击进摘要编辑（Esc 可退出）
    const input = container.querySelector('.sb-duration-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.value).toBe('3s');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(container.querySelector('.sb-duration-input')).toBeNull();
  });

  it('summary 优先渲染于徽标位；空 summary 回落 duration（D2 裁决不空窗）', () => {
    const withSummary: ShotGroup = {
      id: 'g6',
      title: 'Shot_01 场一·苏醒',
      summary: '含3个内切镜头（约18s）',
      duration: '18s',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const c1 = setup(withSummary, 'shot').container;
    expect((c1.querySelector('.sb-duration')!.textContent || '').trim())
      .toBe('含3个内切镜头（约18s）');
    const legacy: ShotGroup = {
      id: 'g7',
      title: '过场',
      duration: '10s',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const c2 = setup(legacy, 'shot').container;
    expect((c2.querySelector('.sb-duration')!.textContent || '').trim()).toBe('10s');
  });
});
