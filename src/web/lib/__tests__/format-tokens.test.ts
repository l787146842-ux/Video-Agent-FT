/**
 * formatTokens K/M 记法格式化（上下文容量卡/圆环数值显示）。
 * 边界：<1000 原数；<1M 用 K（一位小数，去 .0）；≥1M 用 M。
 */
import { describe, it, expect } from 'vitest';
import { formatTokens } from '../utils';

describe('formatTokens（token 数 K/M 记法）', () => {
  it('<1000 显示原数', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
  });

  it('1000 起用 K，整数去掉多余的 .0', () => {
    expect(formatTokens(1000)).toBe('1K');
    expect(formatTokens(128000)).toBe('128K');
  });

  it('非整千保留一位小数', () => {
    expect(formatTokens(10500)).toBe('10.5K');
    expect(formatTokens(1100)).toBe('1.1K');
  });

  it('≥1M 用 M', () => {
    expect(formatTokens(1500000)).toBe('1.5M');
    expect(formatTokens(1000000)).toBe('1M');
  });

  it('负数按 0 处理，小数四舍五入', () => {
    expect(formatTokens(-5)).toBe('0');
    expect(formatTokens(999.6)).toBe('1K');
  });
});
