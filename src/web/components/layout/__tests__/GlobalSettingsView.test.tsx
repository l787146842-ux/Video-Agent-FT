/**
 * GlobalSettingsView 执行偏好三档（批 B）：
 * 三档选择器渲染（当前档随 settings）、切档即时 PUT execution_preference、
 * 乐观更新（先本地生效，失败回滚并 toast）。
 * store 为模块级单例，用例按状态迁移顺序编排（默认档 → 直接生成 → 回滚）。
 */
import { render, fireEvent, waitFor } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { JSX } from 'solid-js';

const agentMock = vi.hoisted(() => ({
  getRuntimeSettings: vi.fn(),
  setRuntimeSettings: vi.fn(),
  getAgentMetrics: vi.fn(),
}));
vi.mock('@/api/agent', () => agentMock);

vi.mock('@/lib/providers', () => ({
  apiProvidersFor: vi.fn(() => []),
  providerModels: vi.fn(() => []),
}));

const toastMock = vi.hoisted(() => vi.fn());
vi.mock('@/stores/toast', () => ({
  showToast: (...args: unknown[]) => toastMock(...args),
  dismissToast: vi.fn(),
  toasts: [],
}));

vi.mock('@solidjs/router', () => ({
  A: (props: { href: string; children?: JSX.Element }) => <a href={props.href}>{props.children}</a>,
}));

vi.mock('@/stores/studio', () => ({
  findDraftRecord: vi.fn(),
  persistBoard: Object.assign(vi.fn(), { flush: vi.fn() }),
  state: { selectedDraftId: '', selectedType: '' },
}));

import GlobalSettingsView from '../GlobalSettingsView';

const SETTINGS = {
  model_fallback_enabled: true,
  chat_image_enabled: true,
  default_image_provider_id: '',
  default_image_model: '',
  default_video_provider_id: '',
  default_video_model: '',
  default_image_resolution: '2K',
  default_video_resolution: '720p',
  max_shot_duration: 5,
  max_steps: 6,
  skills_disabled: [],
  script_inject_limit: 20000,
  execution_preference: 'confirm_before_gen',
  execution_mode: 'ai_decide',
  model_policy: {},
};

const PREF_ARIA = '执行偏好（花钱生成是否先弹确认卡）';
const MODE_ARIA = '执行模式（流程推进的暂停策略）';
const STEPS_ARIA = 'Agent 多步循环最大步数';

function prefSelect(container: HTMLElement): HTMLSelectElement {
  const el = container.querySelector<HTMLSelectElement>(`select[aria-label="${PREF_ARIA}"]`);
  expect(el, '执行偏好选择器应渲染').toBeTruthy();
  return el!;
}

beforeEach(() => {
  vi.clearAllMocks();
  agentMock.getRuntimeSettings.mockResolvedValue({ ...SETTINGS });
  agentMock.setRuntimeSettings.mockImplementation(
    async (patch: Record<string, unknown>) => ({ ...SETTINGS, ...patch }),
  );
  agentMock.getAgentMetrics.mockResolvedValue({
    traces_count: 0, avg_turn_ms: 0, avg_turn_scope: 'llm_rounds', total_steps: 0, total_actions: 0,
    gate_total: 0, gate_intercepts: 0, gate_intercept_rate: 0, fallback_count: 0,
    recent_fallbacks: [], unlogged_llm_calls: 0,
  });
});

describe('GlobalSettingsView 执行偏好三档（批 B）', () => {
  it('渲染三档选择器：当前档随设置下发（默认档），选项恰为三档', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    await waitFor(() => expect(prefSelect(container)).toBeTruthy());
    const sel = prefSelect(container);
    await waitFor(() => expect(sel.value).toBe('confirm_before_gen'));
    const values = Array.from(sel.querySelectorAll('option')).map((o) => o.value);
    expect(values).toEqual(['auto_decide', 'confirm_before_gen', 'generate_directly']);
  });

  it('切档发 PUT execution_preference，本地即时反映（乐观更新）', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    const sel = prefSelect(container);
    await waitFor(() => expect(sel.value).toBe('confirm_before_gen'));
    fireEvent.change(sel, { target: { value: 'generate_directly' } });
    expect(agentMock.setRuntimeSettings).toHaveBeenCalledWith({
      execution_preference: 'generate_directly',
    });
    await waitFor(() => expect(sel.value).toBe('generate_directly'));
  });

  it('档位说明只声明真实存在的机制（不承诺 Skill 暂停点不可跳过）', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    await waitFor(() => expect(prefSelect(container)).toBeTruthy());
    // 失真文案清偿：frontmatter pause 声明无运行时消费者，界面不得再承诺它
    expect(container.textContent ?? '').not.toContain('暂停点不可被跳过');
  });

  it('保存失败回滚到原档并 toast 报错', async () => {
    agentMock.setRuntimeSettings.mockRejectedValueOnce(new Error('boom'));
    const { container } = render(() => <GlobalSettingsView />);
    const sel = prefSelect(container);
    // 承接上一用例迁移后的状态（直接生成档）
    await waitFor(() => expect(sel.value).toBe('generate_directly'));
    fireEvent.change(sel, { target: { value: 'auto_decide' } });
    // 乐观更新先行生效
    expect(sel.value).toBe('auto_decide');
    // 失败后回滚并提示
    await waitFor(() => expect(sel.value).toBe('generate_directly'));
    expect(toastMock).toHaveBeenCalled();
  });
});

describe('GlobalSettingsView 执行模式四档（2026-09-06 对齐批）', () => {
  function modeSelect(container: HTMLElement): HTMLSelectElement {
    const el = container.querySelector<HTMLSelectElement>(`select[aria-label="${MODE_ARIA}"]`);
    expect(el, '执行模式选择器应渲染').toBeTruthy();
    return el!;
  }

  it('渲染四档选择器：当前档随设置下发（默认档），选项恰为四档', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    await waitFor(() => expect(modeSelect(container)).toBeTruthy());
    const sel = modeSelect(container);
    await waitFor(() => expect(sel.value).toBe('ai_decide'));
    const values = Array.from(sel.querySelectorAll('option')).map((o) => o.value);
    expect(values).toEqual(['ai_decide', 'auto_full', 'key_steps_confirm', 'pause_all']);
  });

  it('切档发 PUT execution_mode，本地即时反映（乐观更新）', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    const sel = modeSelect(container);
    await waitFor(() => expect(sel.value).toBe('ai_decide'));
    fireEvent.change(sel, { target: { value: 'key_steps_confirm' } });
    expect(agentMock.setRuntimeSettings).toHaveBeenCalledWith({
      execution_mode: 'key_steps_confirm',
    });
    await waitFor(() => expect(sel.value).toBe('key_steps_confirm'));
  });
});

describe('GlobalSettingsView 最大步数（Q3）', () => {
  function stepsInput(container: HTMLElement): HTMLInputElement {
    const el = container.querySelector<HTMLInputElement>(`input[aria-label="${STEPS_ARIA}"]`);
    expect(el, '最大步数输入框应渲染').toBeTruthy();
    return el!;
  }

  it('渲染最大步数输入框：当前值随设置下发', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    const inp = stepsInput(container);
    await waitFor(() => expect(inp.value).toBe('6'));
  });

  it('改动发 PUT max_steps（钳制 1-30）', async () => {
    const { container } = render(() => <GlobalSettingsView />);
    const inp = stepsInput(container);
    await waitFor(() => expect(inp.value).toBe('6'));
    fireEvent.change(inp, { target: { value: '12' } });
    expect(agentMock.setRuntimeSettings).toHaveBeenCalledWith({ max_steps: 12 });
    // 超界值钳制回 1-30 区间（与后端 MAX_STEPS_RANGE 同口径）
    fireEvent.change(inp, { target: { value: '99' } });
    expect(agentMock.setRuntimeSettings).toHaveBeenCalledWith({ max_steps: 30 });
  });
});
