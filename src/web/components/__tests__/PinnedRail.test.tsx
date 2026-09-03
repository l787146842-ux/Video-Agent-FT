/**
 * PinnedRail 钉住侧栏渲染冒烟测试（F3）。
 *
 * 钉死：① 元数据列表渲染（图标+文件名）；② 仅激活项挂载媒体 src，
 * 非激活项无 img/video（内存纪律）；③ 点击列表项切换激活；
 * ④ 文档项走 markdown 渲染器（懒加载动态 import，正文现读 studio documents）；
 * ⑤ 取消钉住按钮移除条目。
 */
import { render, fireEvent, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { PinnedRail } from '../layout/PinnedRail';
import {
  pinArtifact, clearAllPinned,
} from '@/stores/pinned';
import { setState } from '@/stores/studio';
import type { DocRecord } from '@/types';

const DOC: DocRecord = {
  id: 'd1', kind: 'project', key: '剧本.md', name: '剧本.md', content: '# 第一场\n\n雨夜重逢。',
};

describe('PinnedRail 钉住侧栏', () => {
  beforeEach(() => {
    clearAllPinned();
    setState('documents', [DOC]);
  });
  afterEach(() => {
    clearAllPinned();
    setState('documents', []);
  });

  it('空列表渲染占位提示', () => {
    const { container } = render(() => <PinnedRail />);
    expect(container.querySelector('.pinned-rail')).toBeTruthy();
    expect(container.querySelector('.pinned-preview-empty')?.textContent)
      .toContain('钉住产物后在此对照查看');
  });

  it('仅激活项挂载媒体 src：非激活项只渲染元数据行', async () => {
    pinArtifact({ kind: 'image', url: '/a/img1.png', name: 'img1.png' });
    pinArtifact({ kind: 'video', url: '/a/v1.mp4', name: 'v1.mp4' }); // 后钉者为激活
    const { container } = render(() => <PinnedRail />);

    expect(container.querySelectorAll('.pinned-item')).toHaveLength(2);
    // 激活的视频挂 <video preload=none>，非激活图片不挂 <img>
    const video = container.querySelector('.pinned-preview-video');
    expect(video).toBeTruthy();
    expect(video?.getAttribute('preload')).toBe('none');
    expect(container.querySelector('.pinned-preview-img')).toBeNull();

    // 点击切换到图片项：<img loading=lazy> 挂载、视频卸载
    const imgItem = container.querySelectorAll('.pinned-item')[0] as HTMLElement;
    await fireEvent.click(imgItem);
    const img = container.querySelector('.pinned-preview-img');
    expect(img).toBeTruthy();
    expect(img?.getAttribute('loading')).toBe('lazy');
    expect(container.querySelector('.pinned-preview-video')).toBeNull();
  });

  it('文档项复用 markdown 渲染器（渲染器懒加载，异步出内容）', async () => {
    pinArtifact({ kind: 'doc', name: '剧本.md' });
    const { container } = render(() => <PinnedRail />);
    // markdown-it 经动态 import 加载（移出首屏关键路径），等资源解析后再断言
    await waitFor(() => {
      const doc = container.querySelector('.pinned-doc');
      expect(doc).toBeTruthy();
      expect(doc?.innerHTML).toContain('第一场');
    });
  });

  it('文档不存在时给降级提示', () => {
    setState('documents', []);
    pinArtifact({ kind: 'doc', name: '已删除.md' });
    const { container } = render(() => <PinnedRail />);
    expect(container.querySelector('.pinned-preview-empty')?.textContent)
      .toContain('已删除.md');
  });

  it('取消钉住按钮移除条目', async () => {
    pinArtifact({ kind: 'image', url: '/a/img1.png', name: 'img1.png' });
    const { container } = render(() => <PinnedRail />);
    const unpin = container.querySelector('.pinned-item-unpin') as HTMLButtonElement;
    await fireEvent.click(unpin);
    expect(container.querySelectorAll('.pinned-item')).toHaveLength(0);
  });
});
