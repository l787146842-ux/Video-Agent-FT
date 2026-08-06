import { describe, it, expect, beforeEach } from 'vitest';
import { state, setState, studioActions } from '@/stores/studio';

describe('activeGenerations 读秒状态', () => {
  beforeEach(() => setState('activeGenerations', {}));

  it('startGeneration 后 finishGeneration 应彻底删除条目', () => {
    studioActions.startGeneration('d1', 'image');
    expect(state.activeGenerations['d1']).toBeTruthy();
    expect(Object.keys(state.activeGenerations)).toContain('d1');

    const sec = studioActions.finishGeneration('d1');
    expect(sec).not.toBeNull();
    // 关键断言：条目必须被删除（Solid store 对象合并语义下 delete 可能失效）
    expect(state.activeGenerations['d1']).toBeUndefined();
    expect(Object.keys(state.activeGenerations)).not.toContain('d1');
  });

  it('多草稿并发时只删除目标条目', () => {
    studioActions.startGeneration('d1', 'image');
    studioActions.startGeneration('d2', 'video');
    studioActions.finishGeneration('d1');
    expect(state.activeGenerations['d1']).toBeUndefined();
    expect(state.activeGenerations['d2']).toBeTruthy();
  });
});
