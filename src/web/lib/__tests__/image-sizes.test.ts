import { describe, it, expect } from 'vitest';
import { studioImageSizeForRatio } from '@/lib/image-sizes';

describe('studioImageSizeForRatio', () => {
  it('标准比例映射', () => {
    expect(studioImageSizeForRatio('1:1')).toBe('1024x1024');
    expect(studioImageSizeForRatio('16:9')).toBe('1280x720');
    expect(studioImageSizeForRatio('9:16')).toBe('720x1280');
  });

  it('未知比例回退 1:1', () => {
    expect(studioImageSizeForRatio('5:4')).toBe('1024x1024');
  });

  it('自定义比例计算（横版）', () => {
    const size = studioImageSizeForRatio('custom', '16', '9');
    const [w, h] = size.split('x').map(Number);
    expect(w).toBe(1536);
    expect(h).toBeGreaterThan(800);
    expect(w % 16).toBe(0);
    expect(h % 16).toBe(0);
  });

  it('自定义比例计算（竖版）', () => {
    const size = studioImageSizeForRatio('custom', '9', '16');
    const [w, h] = size.split('x').map(Number);
    expect(h).toBe(1536);
    expect(w).toBeLessThan(h);
  });

  it('非法自定义返回空串', () => {
    expect(studioImageSizeForRatio('custom', '0', '5')).toBe('');
    expect(studioImageSizeForRatio('custom', '', '')).toBe('');
  });
});
