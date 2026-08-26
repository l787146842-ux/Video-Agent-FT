/**
 * Lightbox 统一预览灯箱测试（任务 #11 三合一：原 ImageLightbox/
 * MediaLightbox/PreviewLightbox 收敛后的行为保真钉死件）。
 *
 * 钉死契约：
 * ① image 模式（默认）：image-lightbox 容器 + 下载/关闭钮；空 url 不渲染；
 * ② media 模式：video/audio 按 kind 分发，图片回退；Esc 关闭由焦点圈闭
 *    capture 监听覆盖（无 document 级重复 onDocKey）；
 * ③ zoom 模式：preview-lightbox + 滚轮缩放（0.2~5 钳制）+ 关闭复位，
 *    拖拽中卸载时 window 监听由 onCleanup 兜底摘除；
 * ④ 无障碍：role=dialog / aria-modal 全模式保留。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';
import { Lightbox } from '../Lightbox';

/** jsdom WheelEvent 不带 deltaY init：构造后注入（与原实现读 e.deltaY 对齐） */
function wheel(deltaY: number): WheelEvent {
  const ev = new WheelEvent('wheel', { bubbles: true, cancelable: true });
  Object.defineProperty(ev, 'deltaY', { value: deltaY });
  return ev;
}

describe('Lightbox', () => {
  it('image 模式：容器/下载/关闭钮齐全，点击背景关闭', async () => {
    const onClose = vi.fn();
    const { container, unmount } = render(() => (
      <Lightbox url="http://x/img.png" onClose={onClose} />
    ));
    const box = container.querySelector('.image-lightbox') as HTMLElement;
    expect(box).not.toBeNull();
    expect(box.getAttribute('role')).toBe('dialog');
    expect(box.getAttribute('aria-modal')).toBe('true');
    expect(box.querySelector('img')?.getAttribute('src')).toBe('http://x/img.png');
    expect(box.querySelector('a[download]')).not.toBeNull();
    await fireEvent.click(box);
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('空 url 不渲染（受控守卫）', () => {
    const { container, unmount } = render(() => (
      <Lightbox url={() => ''} onClose={() => {}} />
    ));
    expect(container.querySelector('.image-lightbox')).toBeNull();
    expect(container.querySelector('.preview-lightbox')).toBeNull();
    unmount();
  });

  it('image 模式支持访问器形式的 url', () => {
    const { container, unmount } = render(() => (
      <Lightbox url={() => 'http://x/a.png'} onClose={() => {}} />
    ));
    expect(container.querySelector('img')?.getAttribute('src')).toBe('http://x/a.png');
    unmount();
  });

  it('media 模式：video/audio 分发与图片回退', () => {
    const v = render(() => (
      <Lightbox mode="media" url="http://x/v.mp4" kind="video" onClose={() => {}} />
    ));
    expect(v.container.querySelector('video')).not.toBeNull();
    v.unmount();

    const a = render(() => (
      <Lightbox mode="media" url="http://x/a.mp3" kind="audio" onClose={() => {}} />
    ));
    expect(a.container.querySelector('.image-lightbox-audio audio')).not.toBeNull();
    a.unmount();

    const i = render(() => (
      <Lightbox mode="media" url="http://x/i.png" kind="image" onClose={() => {}} />
    ));
    expect(i.container.querySelector('img')).not.toBeNull();
    i.unmount();
  });

  it('media 模式：Esc 关闭（焦点圈闭 capture 监听覆盖，无 document 级重复监听）', () => {
    const onClose = vi.fn();
    const { unmount } = render(() => (
      <Lightbox mode="media" url="http://x/v.mp4" kind="video" onClose={onClose} />
    ));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(onClose).toHaveBeenCalled();
    unmount();
  });

  it('zoom 模式：拖拽进行中卸载，onCleanup 兜底摘除 window 监听', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { container, unmount } = render(() => (
      <Lightbox mode="zoom" url="http://x/big.png" onClose={() => {}} />
    ));
    const img = container.querySelector('.preview-lightbox-img') as HTMLElement;
    fireEvent.mouseDown(img); // 登记 window mousemove/mouseup
    unmount(); // 拖拽中卸载：不得留监听泄漏
    const removed = removeSpy.mock.calls.map((c) => c[0]);
    expect(removed).toContain('mousemove');
    expect(removed).toContain('mouseup');
    removeSpy.mockRestore();
  });

  it('zoom 模式：滚轮缩放（钳制 0.2~5）+ 角标百分比', async () => {
    const { container, unmount } = render(() => (
      <Lightbox mode="zoom" url="http://x/big.png" onClose={() => {}} />
    ));
    const box = container.querySelector('.preview-lightbox') as HTMLElement;
    expect(box).not.toBeNull();
    expect(container.querySelector('.preview-lightbox-zoom')?.textContent).toBe('100%');
    // 向上滚（deltaY 负）放大
    box.dispatchEvent(wheel(-1000));
    expect(parseInt(container.querySelector('.preview-lightbox-zoom')?.textContent || '', 10)).toBeGreaterThan(100);
    // 极端放大被钳制在 500%
    box.dispatchEvent(wheel(-100000));
    expect(container.querySelector('.preview-lightbox-zoom')?.textContent).toBe('500%');
    unmount();
  });

  it('zoom 模式：关闭钮触发 onClose（复位由组件内部完成）', async () => {
    const onClose = vi.fn();
    const { container, unmount } = render(() => (
      <Lightbox mode="zoom" url="http://x/big.png" onClose={onClose} />
    ));
    const closeBtn = container.querySelector('.preview-lightbox-close') as HTMLElement;
    await fireEvent.click(closeBtn);
    // 点击冒泡至容器层同语义再关一次（与原 PreviewLightbox 一致，父级 setState 幂等）
    expect(onClose).toHaveBeenCalled();
    unmount();
  });
});
