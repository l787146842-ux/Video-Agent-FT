import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { toasts, showToast, dismissToast } from '@/stores/toast';

describe('toast store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // 清空
    [...toasts].forEach((t) => dismissToast(t.id));
  });
  afterEach(() => vi.useRealTimers());

  it('showToast 添加并按级别记录', () => {
    showToast('成功消息', 'success');
    expect(toasts).toHaveLength(1);
    expect(toasts[0].level).toBe('success');
    expect(toasts[0].message).toBe('成功消息');
  });

  it('到时自动消失', () => {
    showToast('临时消息', 'info', 1000);
    expect(toasts).toHaveLength(1);
    vi.advanceTimersByTime(1100);
    expect(toasts).toHaveLength(0);
  });

  it('支持 action 按钮', () => {
    const onClick = vi.fn();
    showToast('已删除', 'warning', 0, { label: '撤销', onClick });
    expect(toasts[0].action?.label).toBe('撤销');
    toasts[0].action?.onClick();
    expect(onClick).toHaveBeenCalled();
  });

  it('dismissToast 手动关闭', () => {
    showToast('消息A', 'info', 0);
    showToast('消息B', 'info', 0);
    dismissToast(toasts[0].id);
    expect(toasts).toHaveLength(1);
    expect(toasts[0].message).toBe('消息B');
  });
});
