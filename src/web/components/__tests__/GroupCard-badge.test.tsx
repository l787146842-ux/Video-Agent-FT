/**
 * 任务 #8 机械断言（前端体验规范 §二 分组卡片 / 台账 #10）：
 * 「右上徽标」的可机械断言部分——
 * ① keyElement 不渲染徽标（2026-09-17 裁决：类别标识退役），
 *    存量数据残留 badgeLabel 也只读透传不显示；
 * ② 徽标按类型落在：分镜=无类别角标（2026-09-18 批 D 删「分镜」角标，右上改显 summary 摘要徽标）、音频=时段或「音频」；
 * ③ 徽标/标题双击可编辑且能退出（音频时段承载编辑面不锁死）。
 *
 * 与条款无关的旁路子件（草稿卡/引用/描述/微调行）以桩替代控制测试面。
 *
 * 任务 #15（用户裁决后补）：条款「左上标题纯中文（剥离 Element_ 等英文前缀）」
 * 的展示层剥离逻辑已在 034747f 重构中丢失，现已按 b6011a5 原口径恢复于
 * GroupHeader（仅显示层剥离，数据层标题原样存储），本文件补正向防回归断言。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

/** 条款断言不涉及的旁路子件打桩（防无关模块进入测试面） */
vi.mock('@/components/left-panel/DraftCard', () => ({ DraftCard: () => null }));
vi.mock('@/components/left-panel/group-card/ShotRefsChips', () => ({ ShotRefsChips: () => null }));
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

describe('分组卡右上徽标（台账 #10；2026-09-17 裁决：keyElement 类别标识退役）', () => {
  it('关键元素：不渲染徽标（组序号仍显示），状态类 tag 不上卡头', () => {
    const group: KeyElementGroup = {
      id: 'g1',
      title: '月球',
      drafts: [draft('d1', '已上传'), draft('d2', '已确认')],
    };
    const { container } = setup(group, 'keyElement');
    expect(container.querySelector('.sb-badge')).toBeNull();
    expect((container.querySelector('.sb-index')!.textContent || '').trim()).toBe('1');
  });

  it('关键元素：存量数据残留 badgeLabel 也不显示（只读透传不渲染）', () => {
    const legacy = {
      id: 'g1', title: '艾AA', badgeLabel: '人物', drafts: [draft('d1', '已上传')],
    } as unknown as KeyElementGroup;
    const { container } = setup(legacy, 'keyElement');
    expect(container.querySelector('.sb-badge')).toBeNull();
  });

  it('分镜：不再渲染类别角标（2026-09-18 批 D：「分镜」角标删除，右上改显 summary 徽标）', () => {
    const legacyType: ShotGroup = {
      id: 'g2', title: '开场', shotType: '特写',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const plain: ShotGroup = {
      id: 'g3', title: '过场',
      drafts: [{ id: 'd2', label: '分镜 2', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    // shot 类别角标已删（旧数据残留 shotType 也不入角标）；右上角改由 summary 徽标承载
    expect(setup(legacyType, 'shot').container.querySelector('.sb-badge')).toBeNull();
    expect(setup(plain, 'shot').container.querySelector('.sb-badge')).toBeNull();
  });

  it('音频：缺省回落「音频」类型词', () => {
    const group: AudioGroup = {
      id: 'g4', title: '配乐',
      drafts: [{ id: 'd1', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'audio');
    expect(badgeText(container)).toBe('音频');
  });

  it('各类型徽标均不含状态类值（负向收口；keyElement 无徽标）', () => {
    const groups: Array<[AnyGroup, DraftType]> = [
      [{ id: 'g1', title: '元素', drafts: [draft('d1', '手动')] } as KeyElementGroup, 'keyElement'],
      [{
        id: 'g2', title: '分镜',
        drafts: [{ id: 'd2', label: '分镜', tag: '生成失败', mediaType: 'video', videoUrl: '', prompt: '' }],
      } as ShotGroup, 'shot'],
    ];
    for (const [group, type] of groups) {
      const { container } = setup(group, type);
      const badge = container.querySelector('.sb-badge');
      const text = badge ? (badge.textContent || '').trim() : '';
      expect(STATUS_TAGS).not.toContain(text);
    }
  });

  it('音频徽标双击进入编辑、Esc 退出（时段徽标可维护不锁死）', () => {
    const group: AudioGroup = {
      id: 'g4', title: '配乐', timeRange: '0-10s',
      drafts: [{ id: 'd1', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
    };
    const { container } = setup(group, 'audio');
    const badge = container.querySelector('.sb-badge') as HTMLElement;
    fireEvent.dblClick(badge);
    const input = container.querySelector('.sb-badge-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(container.querySelector('.sb-badge-input')).toBeNull();
    expect(badgeText(container)).toBe('0-10s');
  });

  it('分镜无类别角标（2026-09-18 批 D 删除）、音频徽标编辑后 Enter 保存', () => {
    const shot: ShotGroup = {
      id: 'g2', title: '开场',
      drafts: [{ id: 'd1', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
    };
    const { container: cShot } = setup(shot, 'shot');
    // 分镜类别角标已删（批 D）：shot 不渲染 .sb-badge，摘要走右上角 .sb-duration
    expect(cShot.querySelector('.sb-badge')).toBeNull();

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

describe('分组卡左上标题纯中文（剥离英文前缀，台账 #10，任务 #15）', () => {
  function titleText(container: HTMLElement): string {
    const span = container.querySelector('.sb-title span[title="双击编辑标题"]');
    expect(span).toBeTruthy();
    return (span!.textContent || '').trim();
  }

  it('三类新建组的 Element_/Shot_/Audio_ 前缀均不显示（正向防回归）', () => {
    const cases: Array<[AnyGroup, DraftType]> = [
      [{ id: 'g1', title: 'Element_未命名', drafts: [draft('d1', '手动')] } as KeyElementGroup, 'keyElement'],
      [{
        id: 'g2', title: 'Shot_未命名',
        drafts: [{ id: 'd2', label: '分镜 1', mediaType: 'video', videoUrl: '', prompt: '' }],
      } as ShotGroup, 'shot'],
      [{
        id: 'g3', title: 'Audio_未命名',
        drafts: [{ id: 'd3', label: '音频 1', mediaType: 'audio', audioUrl: '', prompt: '' }],
      } as AudioGroup, 'audio'],
    ];
    for (const [group, type] of cases) {
      const text = titleText(setup(group, type).container);
      expect(text).not.toMatch(/^(Element|Shot|Audio)_/);
      expect(text).toBe('未命名');
    }
  });

  it('存量中文类别前缀属名字原样显示（2026-09-17 对齐 flova：纯结构性无词表翻译）', () => {
    const legacy: KeyElementGroup = {
      id: 'g1', title: '角色-程心', drafts: [draft('d1', '手动')],
    };
    expect(titleText(setup(legacy, 'keyElement').container)).toBe('角色-程心');
  });

  it('显示层只剥容器类型前缀：名字原样（含下划线，不二次清洗）', () => {
    // 标题本身含下划线：名字原样显示（2026-09-17 裁决退役 b6011a5 去下划线口径）
    const withUnderscore: KeyElementGroup = {
      id: 'g1', title: 'Element_月球_基地', drafts: [draft('d1', '手动')],
    };
    expect(titleText(setup(withUnderscore, 'keyElement').container)).toBe('月球_基地');
    // 无中文可留：回退原文（不显示空标题）
    const noChinese: KeyElementGroup = {
      id: 'g2', title: 'BGM', drafts: [draft('d2', '手动')],
    };
    expect(titleText(setup(noChinese, 'keyElement').container)).toBe('BGM');
    // 纯中文标题不受影响
    const pure: KeyElementGroup = {
      id: 'g3', title: '开场', drafts: [draft('d3', '手动')],
    };
    expect(titleText(setup(pure, 'keyElement').container)).toBe('开场');
  });

  it('仅显示层剥离：双击编辑时输入框承载数据层原标题（含前缀）', () => {
    const group: KeyElementGroup = {
      id: 'g1', title: 'Element_未命名', drafts: [draft('d1', '手动')],
    };
    const { container } = setup(group, 'keyElement');
    expect(titleText(container)).toBe('未命名');
    fireEvent.dblClick(container.querySelector('.sb-title span[title="双击编辑标题"]') as HTMLElement);
    const input = container.querySelector('.sb-title-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.value).toBe('Element_未命名');
  });
});
