/**
 * 图片参数栏「比例空值」显示口径（2026-10-27 用户裁决 A，2222 项目取证）。
 *
 * 病根：卡上 `aspectRatio` 为空时（子代理按委派要求「画幅未确认先留空」把建卡默认值清空，
 * 2222 的沈砚/苏棠两张形象卡落库即 `aspectRatio=""`），参数栏用 `|| '1:1'` 兜底成
 * 「已选 1:1」；而执行期后端用 `|| "16:9"` 兜底 —— 同一个空值被两处读成两个不同的值，
 * 用户目测「1:1」、「出图不是 1:1」，看板自相矛盾。
 *
 * 钉死（只改显示口径，不动执行口径 —— 后者由债务 D-30 承重）：
 *   ① 空值 ⇒ 下拉选中项显示「未设置」，不得出现任何具体比例被伪装成已选值；
 *   ② 已有值 ⇒ 原样显示（不得被「未设置」吞掉）；
 *   ③ 用户显式选具体比例 ⇒ 照常写回 `aspectRatio`（保留人工回填通道）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setState, studioActions } from '@/stores/studio';
import { ImageParams } from '../params/ImageParams';

function seedDraft(aspectRatio: string) {
  setState('keyElements', [{
    id: 'g1', title: 'Element_沈砚', desc: '',
    drafts: [{ id: 'd1', label: '沈砚 · 角色形象三视图', mediaType: 'image', prompt: 'p', aspectRatio }],
  }] as never);
  setState('selectedType', 'keyElement');
  setState('selectedDraftId', 'd1');
}

function ratioSelect(container: HTMLElement): HTMLSelectElement {
  return container.querySelector('[aria-label="图片画面比例"]') as HTMLSelectElement;
}

function selectedLabel(sel: HTMLSelectElement): string {
  return (sel.options[sel.selectedIndex]?.textContent || '').trim();
}

beforeEach(() => {
  setState({ apiProviders: [], keyElements: [], selectedDraftId: '', selectedType: 'keyElement' });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ImageParams · 图片比例空值显示口径', () => {
  it('空值显示「未设置」：不得伪装成 1:1', () => {
    seedDraft('');
    const { container } = render(() => <ImageParams draft={{
      id: 'd1', label: '沈砚 · 角色形象三视图', mediaType: 'image', prompt: 'p', aspectRatio: '',
    }} />);
    const sel = ratioSelect(container);
    expect(sel.value).toBe('');
    expect(selectedLabel(sel)).toContain('未设置');
    // 反向钉：空值绝不能被显示成任何具体比例（1:1 是 2222 误判的直接来源）
    expect(selectedLabel(sel)).not.toBe('1:1');
    expect(selectedLabel(sel)).not.toContain('1:1');
  });

  it('已有值原样显示，不被「未设置」吞掉', () => {
    seedDraft('16:9');
    const { container } = render(() => <ImageParams draft={{
      id: 'd1', label: '场景参考图', mediaType: 'image', prompt: 'p', aspectRatio: '16:9',
    }} />);
    const sel = ratioSelect(container);
    expect(sel.value).toBe('16:9');
    expect(selectedLabel(sel)).toBe('16:9');
  });

  it('用户显式选具体比例仍写回 aspectRatio（人工回填通道不被关闭）', () => {
    seedDraft('');
    const spy = vi.spyOn(studioActions, 'updateDraftLocal');
    const { container } = render(() => <ImageParams draft={{
      id: 'd1', label: '沈砚 · 角色形象三视图', mediaType: 'image', prompt: 'p', aspectRatio: '',
    }} />);
    fireEvent.change(ratioSelect(container), { target: { value: '9:16' } });
    expect(spy).toHaveBeenCalledWith('keyElement', 'd1', { aspectRatio: '9:16' });
  });
});
