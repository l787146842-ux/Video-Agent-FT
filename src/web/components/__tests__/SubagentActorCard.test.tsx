/**
 * SubagentActorCard 组件单测（流式二期，计划书 §五 前端②③）。
 *
 * 钉死：卡面三要素（标签 / 实时态 / 步数）、running→completed 文案翻转、
 * 子工具名单默认折叠点标题展开（信息不丢只换载体）、点击卡 → 中间面板切
 * 「子任务」视图 + 登记该 cid 的打开请求；cid 空（降级不落流）→ 按钮禁用，
 * 点击不切视图（不给死链）。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { SseEvent, SseSubagentMeta } from '@/types';
import { state, setState } from '@/stores/studio';
import {
  subagentActorActions, resetSubagentActors, pendingSubagentRecord, actorByKey,
  SUBAGENT_DELEGATE_TOOL,
} from '@/stores/chat/subagent-actors';
import { SubagentActorCard } from '../right-panel/SubagentActorCard';

const META: SseSubagentMeta = {
  cid: 'conv-sub-9', stage: 'script_analyze', label: '剧本分析', depth: 1,
};

/** 播一条子工具活动（建 actor + 占账本槽位） */
function seed(meta: SseSubagentMeta = META): void {
  subagentActorActions.applyChildEvent(meta, {
    type: 'tool_started', id: 'c1', name: 'read_uploaded_doc', summary: '读剧本',
  } as SseEvent);
}

/** 父委派收尾（completed / failed） */
function finishDelegate(ok: boolean): void {
  subagentActorActions.applyDelegateEvent({
    type: 'tool_started', id: 'p1', name: SUBAGENT_DELEGATE_TOOL, summary: '委派',
  } as SseEvent);
  subagentActorActions.applyDelegateEvent({
    type: 'tool_finished', id: 'p1', ok, elapsed_ms: 900,
  } as SseEvent);
}

function renderCard(key: string) {
  return render(() => <SubagentActorCard actor={() => actorByKey(key)} />);
}

beforeEach(() => {
  resetSubagentActors();
  setState('middleView', 'preview');
});
afterEach(() => cleanup());

describe('SubagentActorCard 卡面', () => {
  it('渲染标签 / 实时态 / 步数（执行中）', () => {
    seed();
    const { getByText, getByTestId } = renderCard('conv-sub-9');
    expect(getByTestId('subagent-actor-card')).toBeTruthy();
    expect(getByText('剧本分析')).toBeTruthy();
    expect(getByText('执行中')).toBeTruthy();
    expect(getByText('0 步')).toBeTruthy();
    expect(getByText('子代理')).toBeTruthy();     // 归组身份徽标
  });

  it('actor 缺失（键对不上）→ 不渲染空壳卡', () => {
    const { queryByTestId } = renderCard('conv-nope');
    expect(queryByTestId('subagent-actor-card')).toBeNull();
  });

  it('running→completed：卡面状态文案随 actor 翻转', () => {
    seed();
    finishDelegate(true);
    const { getByText } = renderCard('conv-sub-9');
    expect(getByText('已完成')).toBeTruthy();
  });

  it('委派失败 → 卡面显已中断', () => {
    seed();
    finishDelegate(false);
    const { getByText } = renderCard('conv-sub-9');
    expect(getByText('已中断')).toBeTruthy();
  });

  it('子工具名单默认折叠，点标题展开看全名单', async () => {
    seed();
    subagentActorActions.applyChildEvent(META, {
      type: 'tool_finished', id: 'c1', ok: true, elapsed_ms: 8, result_summary: '读完',
    } as SseEvent);
    const { getByText, queryByText } = renderCard('conv-sub-9');
    expect(queryByText('读剧本')).toBeNull();
    await fireEvent.click(getByText('子代理操作（1）'));
    expect(getByText('读剧本')).toBeTruthy();
  });
});

describe('SubagentActorCard 点击进只读记录', () => {
  it('点卡 → 中间面板切子任务视图 + 登记该 cid 的打开请求', async () => {
    seed();
    const { getByTestId } = renderCard('conv-sub-9');
    await fireEvent.click(getByTestId('subagent-actor-head'));
    expect(state.middleView).toBe('subagents');
    expect(pendingSubagentRecord()).toBe('conv-sub-9');
  });

  it('cid 空（降级不落流）→ 按钮禁用，点击不切视图不给死链', async () => {
    seed({ cid: '', stage: '', label: '写提示词', depth: 1 });
    const { getByTestId } = renderCard('写提示词#1');
    const head = getByTestId('subagent-actor-head') as HTMLButtonElement;
    expect(head.disabled).toBe(true);
    await fireEvent.click(head);
    expect(state.middleView).toBe('preview');
    expect(pendingSubagentRecord()).toBe('');
  });
});
