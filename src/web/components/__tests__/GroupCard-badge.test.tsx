/**
 * 任务 #8 机械断言（前端体验规范 §二 分组卡片 / 台账 #10）：
 * 「右上徽标 = 元素类型」的可机械断言部分——
 * ① 徽标永不显示状态类值（已上传/已确认/手动/待确认/生成失败）；
 * ② 徽标按类型落在元素类型字段上：关键元素=徽标字段或「关键元素」、
 *    分镜=镜头类型或「分镜」、音频=时段或「音频」（均为中文类型词）；
 * ③ 徽标/标题双击可编辑且能退出（徽标承载类型语义的交互面不锁死）。
 *
 * 与条款无关的旁路子件（草稿卡/场景引用/描述/微调行）以桩替代控制测试面。
 *
 * 已知缺口（同批报告，不在本文件断言）：条款「左上标题纯中文（剥离
 * Element_ 等英文前缀）」的展示层剥离逻辑已在后续重构中丢失，当前
 * UI 原样显示带前缀标题——属违反条款的冲突项，交上级裁决（宪法 §3
 * UI 改动须用户目测，本任务只补测试不改 UI）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

/** 条款断言不涉及的旁路子件打桩（防无关模块进入测试面） */
vi.mock('@/components/left-panel/DraftCard', () => ({ DraftCard: () => null }));
vi.mock('@/components/left-panel/group-card/SceneRefsChips', () => ({ SceneRefsChips: () => null }));
vi.mock('@/components/left-panel/group-card/GroupDescEditor', () => ({ GroupDescEditor: () => null }));
vi.mock('@/components/left-panel/group-card/GroupAdjustBox', () => ({ GroupAdjustBox: () => null }));
vi.mock('@/lib/agent-actions', () => ({ sendUserMessage: vi.fn() }));

import { GroupCard } from '../left-panel/GroupCard';
import type {
  AnyGroup, AudioGroup, Draft, DraftType, KeyElementGroup, ShotGroup,
} from '@/types';

const noop = () => {};

/** 条款明示的状态类 tag（不作为元素类型展示） */
const STATUS_TAGS = ['已上传', '已确认', '手动', '待确认', '生成失败'];

function draft(id: string, tag?: string): Draft {
  return { id, label: `草稿 ${id}`, tag, mediaType: 'image', imgUrl: '', prompt: '' };
}

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

function badgeText(container: HTMLElement): string {
  const badge = container.querySelector('.sb-badge');
  expect(badge).toBeTruthy();
  return (badge!.textContent || '').trim();
}

describe('分组卡右上徽标 = 元素类型（台账 #10）', () => {
  it('关键元素：草稿 tag 全为状态值时徽标回落「关键元素」，不显示状态值', () => {
    const group: KeyElementGroup = {
      id: 'g1',
      title: '月球',
      drafts: [draft('d1', '已上传'), draft('d2', '已确认')],
    };
    const { container } = setup(group, 'keyElement');
    const badge = badgeText(container);
    expect(badge).toBe('关键元素');
    expect(STATUS_TAGS).not.toContain(badge);
  });

  it('关键元素：显式徽标字段（人物/场景/道具类元素类型）优先展示', () => {
    const group: KeyElementGroup = {
      id: 'g1',
      title: '艾AA',
      badgeLabel: '人物',
      drafts: [draft('d1', '已上传')],
    };
    const { container } = setup(group, 'keyElement');
    expect(badgeText(container)).toBe('人物');
  });

  it('分镜：镜头类型字段优先，缺省回落「分镜」', () => {
    const withType: ShotGroup = {
      id: 'g2', title: '开场', shotType: '特写',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const plain: ShotGroup = {
      id: 'g3', title: '过场',
      drafts: [{ id: 'd2', label: '分镜 2', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    expect(badgeText(setup(withType, 'shot').container)).toBe('特写');
    expect(badgeText(setup(plain, 'shot').container)).toBe('分镜');
  });

  it('音频：缺省回落「音频」类型词', () => {
    const group: AudioGroup = {
      id: 'g4', title: '配乐',
      drafts: [{ id: 'd1', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'audio');
    expect(badgeText(container)).toBe('音频');
  });

  it('三类型徽标均不含状态类值（负向收口）', () => {
    const groups: Array<[AnyGroup, DraftType]> = [
      [{ id: 'g1', title: '元素', drafts: [draft('d1', '手动')] } as KeyElementGroup, 'keyElement'],
      [{
        id: 'g2', title: '分镜',
        drafts: [{ id: 'd2', label: '分镜', tag: '生成失败', mediaType: 'video', videoUrl: '', prompt: '' }],
      } as ShotGroup, 'shot'],
    ];
    for (const [group, type] of groups) {
      const { container } = setup(group, type);
      expect(STATUS_TAGS).not.toContain(badgeText(container));
    }
  });

  it('徽标双击进入编辑、Esc 退出（类型徽标可维护不锁死）', () => {
    const group: KeyElementGroup = {
      id: 'g1', title: '月球', badgeLabel: '场景',
      drafts: [draft('d1', '已上传')],
    };
    const { container } = setup(group, 'keyElement');
    const badge = container.querySelector('.sb-badge') as HTMLElement;
    fireEvent.dblClick(badge);
    const input = container.querySelector('.sb-badge-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(container.querySelector('.sb-badge-input')).toBeNull();
    expect(badgeText(container)).toBe('场景');
  });

  it('分镜/音频徽标编辑后 Enter 保存（类型字段各自落库分支）', () => {
    const shot: ShotGroup = {
      id: 'g2', title: '开场', shotType: '特写',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const { container: cShot } = setup(shot, 'shot');
    fireEvent.dblClick(cShot.querySelector('.sb-badge') as HTMLElement);
    const shotInput = cShot.querySelector('.sb-badge-input') as HTMLInputElement;
    fireEvent.input(shotInput, { target: { value: '全景' } });
    fireEvent.keyDown(shotInput, { key: 'Enter' });
    expect(cShot.querySelector('.sb-badge-input')).toBeNull();

    const audio: AudioGroup = {
      id: 'g4', title: '配乐', timeRange: '0-10s',
      drafts: [{ id: 'd2', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
    };
    const { container: cAudio } = setup(audio, 'audio');
    expect((cAudio.querySelector('.sb-badge')!.textContent || '').trim()).toBe('0-10s');
    fireEvent.dblClick(cAudio.querySelector('.sb-badge') as HTMLElement);
    const audioInput = cAudio.querySelector('.sb-badge-input') as HTMLInputElement;
    fireEvent.input(audioInput, { target: { value: '10-20s' } });
    fireEvent.keyDown(audioInput, { key: 'Enter' });
    expect(cAudio.querySelector('.sb-badge-input')).toBeNull();
  });

  it('标题双击可编辑、Enter/Esc 均能退出（标题与徽标编辑面一致）', () => {
    const group: KeyElementGroup = {
      id: 'g1', title: '月球',
      drafts: [draft('d1', '已上传')],
    };
    const { container } = setup(group, 'keyElement');
    const titleSpan = container.querySelector('.sb-title span[title="双击编辑标题"]') as HTMLElement;
    expect(titleSpan).toBeTruthy();
    fireEvent.dblClick(titleSpan);
    const input = container.querySelector('.sb-title-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(container.querySelector('.sb-title-input')).toBeNull();
    // Enter 路径同样能退出编辑（输入为空回落原标题）
    fireEvent.dblClick(container.querySelector('.sb-title span[title="双击编辑标题"]') as HTMLElement);
    const input2 = container.querySelector('.sb-title-input') as HTMLInputElement;
    fireEvent.keyDown(input2, { key: 'Enter' });
    expect(container.querySelector('.sb-title-input')).toBeNull();
    expect(container.querySelector('.sb-title')!.textContent).toContain('月球');
  });
});
