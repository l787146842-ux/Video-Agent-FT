/**
 * 暂停卡长说明折叠（2026-10-09，事故 6666，用户裁决「改成折叠展示」）。
 *
 * 病灶：模型按既有契约（`WorkflowPauseInput.detail`：「确认批次产出时，把被确认
 * 的对象逐条列在这里」，4444/P2-1 裁决）把 9 张待生成卡逐条列出 ⇒ 645 字 / 10
 * 个换行顶在卡面标题下，把题面与选项区挤出视野。
 * 口径：**不改契约、只改呈现**——内容一字不少，长清单默认收起。
 *
 * 钉死契约：
 * ① 短单行说明 **保持内联**（不退化既有体验基线，不白加一次点击）；
 * ② 含换行或多行长说明 **默认折叠**，只露首行摘要 + 「展开全部（N 条）」；
 * ③ 点击展开后 **全文（含全部换行）完整可见**，一条不少；
 * ④ 折叠只影响呈现，说明**永不进入选项区**（dsh detail 语义不变）。
 */
/// <reference types="node" />
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import {
  PAUSE_DETAIL_MAX_INLINE, detailLineCount, detailSummary, shouldCollapseDetail,
} from '@/lib/pause-detail';
import type { ChatMessage } from '@/types';

vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));
vi.mock('@/lib/providers', () => ({
  apiProvidersFor: () => [{ id: 'volc', name: '火山引擎' }],
  providerModels: () => ['doubao-seed'],
}));

/** 6666 现场实测形态：9 张待确认卡逐条清单（645 字 / 10 个换行） */
const LONG_DETAIL = [
  '本次拟生成关键元素（keyElement）设定图共 9 张，出图渠道按全局设置采用 custom-api-2 / gemini-3.1-flash-image（分辨率 2K，画幅 16:9）：',
  '',
  '1. 【角色三视图】程心_角色三视图设定图（正/侧/背三视角，清冷知性短发、素色极简冬眠服）',
  '2. 【角色三视图】AA_角色三视图设定图（正/侧/背三视角，微卷短发、机敏灵动、浅银灰冬眠服）',
  '3. 【角色三视图】曹彬_角色三视图设定图（正/侧/背三视角，斑白短发、深刻皱纹、深灰蓝高阶指挥制服）',
].join('\n');

function pauseMessage(extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '是否确认按当前提示词启动批量生成 9 张关键元素设定图？',
    pauseId: 'pause_6666',
    confirmOptions: [{ label: '确认批量生成设定图', value: 'ok' }],
    ...extra,
  };
}

const toggle = (c: HTMLElement) =>
  c.querySelector('[data-testid="pause-detail-toggle"]') as HTMLButtonElement | null;

describe('pause-detail 纯函数判定（折叠口径唯一实现）', () => {
  it('空/空白说明不折叠（不渲染空块）', () => {
    expect(shouldCollapseDetail('')).toBe(false);
    expect(shouldCollapseDetail('   \n  ')).toBe(false);
    expect(detailSummary('')).toBe('');
  });

  it('短单行说明不折叠（保持内联，不白加一次点击）', () => {
    const short = '这会决定后续所有镜头的基调。';
    expect(short.length).toBeLessThan(PAUSE_DETAIL_MAX_INLINE);
    expect(shouldCollapseDetail(short)).toBe(false);
  });

  it('含换行即折叠（清单/多段 = 长说明）', () => {
    expect(shouldCollapseDetail('第一行\n第二行')).toBe(true);
  });

  it('无换行但超长同样折叠（防长墙漏网）', () => {
    const long = '甲'.repeat(PAUSE_DETAIL_MAX_INLINE + 1);
    expect(shouldCollapseDetail(long)).toBe(true);
  });

  it('摘要 = 首行（首行恒为「本次确认什么」的概括句）', () => {
    expect(detailSummary(LONG_DETAIL)).toBe(
      '本次拟生成关键元素（keyElement）设定图共 9 张，出图渠道按全局设置采用 custom-api-2 / gemini-3.1-flash-image（分辨率 2K，画幅 16:9）：',
    );
    // 首行若为空（说明以换行开头）则回落全文，不产出空摘要
    expect(detailSummary('\n\n正文')).toBe('正文');
  });

  it('规模计数 = 非空行数（口径同「共 N 行」，含首行概述）', () => {
    // 首行概述 + 空行 + 3 条清单 = 4 非空行（空行不计）
    expect(detailLineCount(LONG_DETAIL)).toBe(4);
    expect(detailLineCount('单行')).toBe(1);
    expect(detailLineCount('')).toBe(0);
  });
});

describe('暂停卡长说明折叠渲染（事故 6666）', () => {
  it('① 短说明仍内联渲染，且不出现折叠开关（体验基线不退化）', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseDetail: '影响全部后续镜头。' })} />
    ));
    expect(container.querySelector('.confirm-wizard-detail')?.textContent)
      .toBe('影响全部后续镜头。');
    expect(toggle(container)).toBeNull();
  });

  it('② 长清单默认折叠：只露首行摘要 + 展开提示，不顶全文', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseDetail: LONG_DETAIL })} />
    ));
    const btn = toggle(container);
    expect(btn).not.toBeNull();
    expect(btn!.getAttribute('aria-expanded')).toBe('false');
    const text = container.querySelector('.confirm-detail-text')?.textContent || '';
    expect(text).toBe(detailSummary(LONG_DETAIL));
    // 折叠态不展示清单条目（卡面不再被挤出视野）
    expect(text).not.toContain('3. 【角色三视图】曹彬');
    // 展开提示带真实规模（非空行数 = 4：首行概述 + 3 条清单）
    expect(container.querySelector('.confirm-detail-cue')?.textContent).toContain('展开全部（共 4 行）');
  });

  it('③ 点击展开后全文（含全部换行）完整可见，一条不少', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseDetail: LONG_DETAIL })} />
    ));
    fireEvent.click(toggle(container)!);
    expect(toggle(container)!.getAttribute('aria-expanded')).toBe('true');
    const text = container.querySelector('.confirm-detail-text')?.textContent || '';
    // 原文逐字还原（首行 + 3 条清单全部在内）
    expect(text).toBe(LONG_DETAIL);
    expect(text).toContain('1. 【角色三视图】程心_角色三视图设定图');
    expect(text).toContain('3. 【角色三视图】曹彬_角色三视图设定图');
    // 可再次收起
    fireEvent.click(toggle(container)!);
    expect(toggle(container)!.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.confirm-detail-text')?.textContent)
      .toBe(detailSummary(LONG_DETAIL));
  });

  it('④ 折叠只改呈现：说明永不进入选项区（dsh detail 语义不变）', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({ pauseDetail: LONG_DETAIL })} />
    ));
    const labels = Array.from(container.querySelectorAll('.confirm-option-label'))
      .map((el) => el.textContent);
    expect(labels).toEqual(['确认批量生成设定图']);
    fireEvent.click(toggle(container)!);
    const after = Array.from(container.querySelectorAll('.confirm-option-label'))
      .map((el) => el.textContent);
    expect(after).toEqual(['确认批量生成设定图']);
  });

  it('⑤ 多组向导分支同样走折叠（headerBlock/detail 单家复用）', () => {
    const { container } = render(() => (
      <ConfirmActions message={pauseMessage({
        pauseHeader: '确认生成设定图',
        pauseDetail: LONG_DETAIL,
        confirmOptions: [
          { label: '写实', value: 'a', group: '画风' },
          { label: '16:9', value: 'b', group: '画幅' },
        ],
      })} />
    ));
    expect(toggle(container)).not.toBeNull();
    expect(container.querySelector('.confirm-detail-text')?.textContent)
      .toBe(detailSummary(LONG_DETAIL));
  });
});
