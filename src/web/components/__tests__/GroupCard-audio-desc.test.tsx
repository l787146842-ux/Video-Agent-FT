/**
 * 音频组描述位**真实渲染**测试（2026-09-25 用户裁决：「音频也要给 desc。
 * 写的地方和看的地方要对的上。」）
 *
 * 与 GroupCard-badge.test.tsx 的分工：那份把 GroupDescEditor 打了桩（条款断言
 * 不需要它），本份**不桩**，断言页面上真实出现的文本——即用户肉眼所见。
 *
 * 病灶复现（8888 取证）：模型把音频层设计写在 `desc`（146 字），而描述位读的是
 * `prompt`（模型从不写、恒空）⇒ 界面显示占位符「双击添加描述...」。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/components/left-panel/DraftCard', () => ({ DraftCard: () => null }));
vi.mock('@/components/left-panel/group-card/ShotRefsChips', () => ({ ShotRefsChips: () => null }));
vi.mock('@/components/left-panel/group-card/GroupAdjustBox', () => ({ GroupAdjustBox: () => null }));
vi.mock('@/lib/agent-actions', () => ({ sendUserMessage: vi.fn() }));

import { GroupCard } from '../left-panel/GroupCard';
import type { AnyGroup, AudioGroup, DraftType } from '@/types';

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

function audioGroup(extra: Partial<AudioGroup>): AudioGroup {
  return {
    id: 'a1', title: 'Audio_BGM-01 末日序曲',
    drafts: [{ id: 'd1', label: 'BGM-01', mediaType: 'audio', audioUrl: '', prompt: '' }],
    ...extra,
  } as AudioGroup;
}

function descText(container: HTMLElement): string {
  return (container.querySelector('.sb-desc')?.textContent || '').trim();
}

describe('音频组描述位真实渲染（desc 为唯一载体）', () => {
  it('组有 desc → 页面显示 desc 正文，不显示占位符', () => {
    const { container } = setup(audioGroup({
      desc: '覆盖场一（Shot 1–4）。情绪：低沉压抑。配器：低频弦乐+drone。约46s。',
    }), 'audio');
    expect(descText(container)).toContain('覆盖场一');
    expect(descText(container)).not.toContain('双击添加描述');
  });

  it('存量数据只有 prompt → 回落显示（读时兼容，不空窗）', () => {
    const { container } = setup(audioGroup({ prompt: '历史前端写口留下的描述' }), 'audio');
    expect(descText(container)).toContain('历史前端写口留下的描述');
  });

  it('desc 与 prompt 同存 → desc 优先（第二事实源不得回潮）', () => {
    const { container } = setup(audioGroup({
      desc: 'desc 是唯一载体', prompt: 'prompt 是历史遗留',
    }), 'audio');
    expect(descText(container)).toContain('desc 是唯一载体');
    expect(descText(container)).not.toContain('prompt 是历史遗留');
  });

  it('两者皆空 → 显示占位符（引导用户填写）', () => {
    const { container } = setup(audioGroup({}), 'audio');
    expect(descText(container)).toContain('双击添加描述');
  });
});
