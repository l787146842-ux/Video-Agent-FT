import { describe, it, expect, afterEach } from 'vitest';
import { t, tDynamic, setLocale, getLocale } from '@/lib/locale';

describe('lib/locale（i18n 基础）', () => {
  afterEach(() => setLocale('zh-CN'));

  it('zh-CN 为默认语言，直接命中字典', () => {
    expect(getLocale()).toBe('zh-CN');
    expect(t('rp.feed.empty')).toBe('和 Agent 聊聊，让它帮你规划故事板');
  });

  it('占位符插值（多处同名占位不残留）', () => {
    expect(t('rp.input.added', { name: '图A' })).toBe('已放入输入框：图A');
    expect(t('rp.msg.appliedOps', { count: 3 })).toBe('已执行 3 个操作');
    expect(t('rp.asset.cardToggle', { name: 'x.png', action: '选中' }))
      .toBe('x.png — 点击选中');
  });

  it('动态键缺失时回退为 key 本身（tDynamic 运行时回退链）', () => {
    expect(tDynamic('rp.not.exists')).toBe('rp.not.exists');
    // 字典已登记的键经动态通道同样命中（后端 status 事件同键翻译）
    expect(tDynamic('agent.planning')).toBe('正在推理…（模型正在读状态并规划操作）');
    expect(tDynamic('agent.opsDone', { ops: '写入剧本' })).toBe('已完成：写入剧本');
  });

  it('未提供的语言（en 未补齐）回退 zh-CN', () => {
    setLocale('en');
    expect(t('rp.feed.empty')).toBe('和 Agent 聊聊，让它帮你规划故事板');
  });
});
