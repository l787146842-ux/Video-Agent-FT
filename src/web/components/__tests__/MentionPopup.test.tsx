/** MentionPopup 测试：成功加载态的"整画布而非选中项"诚实提示 */
import { render, screen } from '@solidjs/testing-library';
import { describe, it, expect } from 'vitest';
import { MentionPopup } from '../right-panel/MentionPopup';
import { t } from '@/lib/locale';
import type { CanvasNodeImageItem } from '@/api/canvas';

const items: CanvasNodeImageItem[] = [
  { id: 'n1', name: '场景概念图', url: '/assets/a.png', thumb: '/assets/a.png', category: 'smart' },
  { id: 'n2', name: '角色立绘', url: '/assets/b.png', thumb: '', category: 'smart' },
];

const baseProps = {
  activeIdx: 0,
  query: '',
  onSelect: () => {},
};

describe('MentionPopup 画布引用诚实提示', () => {
  it('成功加载（有图片）时展示整画布提示', () => {
    render(() => <MentionPopup {...baseProps} loading={false} canvasOnline={true} items={items} />);
    expect(screen.getByText(t('rp.mention.scope'))).toBeTruthy();
    // 列表项正常渲染
    expect(screen.getByText('场景概念图')).toBeTruthy();
  });

  it('加载中不展示提示', () => {
    render(() => <MentionPopup {...baseProps} loading={true} canvasOnline={true} items={items} />);
    expect(screen.queryByText(t('rp.mention.scope'))).toBeNull();
  });

  it('空列表（画布无图片）时不展示提示，展示空态', () => {
    render(() => <MentionPopup {...baseProps} loading={false} canvasOnline={true} items={[]} />);
    expect(screen.queryByText(t('rp.mention.scope'))).toBeNull();
    expect(screen.getByText(t('rp.mention.none'))).toBeTruthy();
  });

  it('画布离线时不展示提示，展示离线态', () => {
    render(() => <MentionPopup {...baseProps} loading={false} canvasOnline={false} items={[]} />);
    expect(screen.queryByText(t('rp.mention.scope'))).toBeNull();
    expect(screen.getByText(t('rp.mention.offline'))).toBeTruthy();
  });

  it('画布离线且 items 非空时也不展示 scope 提示（任务 #11 离线排除）', () => {
    render(() => <MentionPopup {...baseProps} loading={false} canvasOnline={false} items={items} />);
    expect(screen.queryByText(t('rp.mention.scope'))).toBeNull();
  });
});
