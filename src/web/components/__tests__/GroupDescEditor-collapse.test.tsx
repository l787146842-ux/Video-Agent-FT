/**
 * 关键元素/音频 desc 展开收起（2026-10-26 用户裁决：与分镜同口径）。
 * ① 默认折叠两行 + 「展开」按钮；② 点按钮展开全文并变「收起」；
 * ③ 双击正文进编辑（textarea）；④ 空描述 → 占位符、无展开按钮。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/stores/studio', () => ({ studioActions: { renameGroupLocal: vi.fn() } }));

import { GroupDescEditor } from '../left-panel/group-card/GroupDescEditor';

const LONG = '角色名：沈砚（28）。外形：身形颀长挺拔，肩宽腰窄；五官冷峻锋利。'
  + '妆发服装：长发半束、白玉冠束顶；玄黑织金蟒纹锦袍，外披玄色斗篷。';

function setup(desc: string) {
  return render(() => <GroupDescEditor type="keyElement" groupId="g1" desc={() => desc} />);
}

describe('关键元素/音频 desc 折叠（对齐分镜）', () => {
  it('默认折叠两行，并出现「展开」按钮', () => {
    const { container } = setup(LONG);
    const body = container.querySelector('.sb-desc') as HTMLElement;
    expect(body.classList.contains('sb-desc--collapsed')).toBe(true);
    expect(container.querySelector('.sb-design-toggle')?.textContent).toContain('展开');
  });

  it('点「展开」→ 全文展开 + 按钮变「收起」', () => {
    const { container } = setup(LONG);
    fireEvent.click(container.querySelector('.sb-design-toggle') as HTMLElement);
    const body = container.querySelector('.sb-desc') as HTMLElement;
    expect(body.classList.contains('sb-desc--collapsed')).toBe(false);
    expect(container.querySelector('.sb-design-toggle')?.textContent).toContain('收起');
  });

  it('双击正文进编辑态（textarea，可编辑 desc）', () => {
    const { container } = setup(LONG);
    fireEvent.dblClick(container.querySelector('.sb-desc') as HTMLElement);
    const editor = container.querySelector('.sb-desc-input') as HTMLTextAreaElement;
    expect(editor).toBeTruthy();
    expect(editor.value).toBe(LONG);
  });

  it('空描述 → 占位符 + 不渲染展开按钮', () => {
    const { container } = setup('');
    expect(container.querySelector('.sb-desc')?.textContent).toContain('双击添加描述');
    expect(container.querySelector('.sb-design-toggle')).toBeNull();
  });
});
