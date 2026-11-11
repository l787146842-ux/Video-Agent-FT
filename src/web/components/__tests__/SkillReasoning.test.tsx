/**
 * 助手思考面板渲染：流式标题随阶段切换（思考中/深度思考中/自修复），
 * 完成后折叠为 details（默认收起，可展开回看全文）。
 */
import { render } from '@solidjs/testing-library';
import { describe, it, expect } from 'vitest';
import { SkillReasoningDone, SkillReasoningLive } from '../skills/SkillReasoning';

describe('SkillReasoning 思考面板', () => {
  it('流式：无思考显示「思考中…」；有思考显示「深度思考中…」+ 正文', () => {
    const empty = render(() => <SkillReasoningLive reasoning="" status="" />);
    expect(empty.container.textContent).toContain('思考中…');
    empty.unmount();

    const live = render(() => <SkillReasoningLive reasoning="先看结构" status="" />);
    expect(live.container.textContent).toContain('深度思考中…');
    expect(live.container.textContent).toContain('先看结构');
    live.unmount();
  });

  it('流式状态优先（自检修复中）；完成后折叠标题 + 全文', () => {
    const live = render(
      () => <SkillReasoningLive reasoning="想" status="正在自动修复…" />,
    );
    expect(live.container.textContent).toContain('正在自动修复…');
    expect(live.container.querySelector('.skst-reasoning.live')).not.toBeNull();
    // 定高滚动视窗：新文字入底，旧文字上滑（与主对话 tl-reasoning-live 同口径）
    expect(live.container.querySelector('.skst-reasoning-body.live')).not.toBeNull();
    live.unmount();

    const done = render(() => <SkillReasoningDone reasoning="思考全文" />);
    const details = done.container.querySelector('details.skst-reasoning');
    expect(details).not.toBeNull();
    expect(done.container.querySelector('summary')?.textContent).toBe('深度思考');
    expect(details?.textContent).toContain('思考全文');
    done.unmount();
  });
});
