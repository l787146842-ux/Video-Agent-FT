/**
 * api 模块参数拼装测试（任务 #30）：sse.ts 任务式传输端点 + agent.ts 关键端点。
 * 钉死路径/查询串/body 拼装与容错（tasks 缺省回落空数组等）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  startAgentTask, fetchAgentTaskEvents, listAgentTasks, stopAgentTask, postAgentTaskGuidance,
} from '../sse';
import {
  canvasLlm, getSkills, getContextUsage, getRuntimeSettings, setRuntimeSettings,
  getAgentMetrics,
} from '../agent';
import type { AgentChatRequest } from '@/types';

const fetchMock = vi.fn();

function res(body: unknown, status = 200): Response {
  return {
    ok: status < 300, status, statusText: 'OK',
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

describe('sse.ts 任务式传输端点', () => {
  it('startAgentTask：POST /api/agent/tasks 原样携带聊天请求体', async () => {
    fetchMock.mockResolvedValue(res({ task_id: 't1', project_id: 'p1' }));
    const req = { message: '你好', provider: 'mock', model: 'm' } as AgentChatRequest;
    const info = await startAgentTask(req);
    expect(info).toEqual({ task_id: 't1', project_id: 'p1' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/agent/tasks');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual(req);
  });

  it('fetchAgentTaskEvents：taskId 编码进路径并透传 AbortSignal', async () => {
    const ctrl = new AbortController();
    fetchMock.mockResolvedValue(res({}));
    await fetchAgentTaskEvents('task/空格', ctrl.signal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/agent/tasks/task%2F%E7%A9%BA%E6%A0%BC/events');
    expect(init.signal).toBe(ctrl.signal);
  });

  it('listAgentTasks：project_id 进查询串；缺 tasks 回落空数组', async () => {
    fetchMock.mockResolvedValueOnce(res({ tasks: [{ task_id: 't1' }] }));
    expect(await listAgentTasks('项目 A')).toEqual([{ task_id: 't1' }]);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/tasks?project_id=%E9%A1%B9%E7%9B%AE%20A');
    fetchMock.mockResolvedValueOnce(res({}));
    expect(await listAgentTasks('p')).toEqual([]);
  });

  it('stopAgentTask：POST /stop（任务 #17 响应可携 inflight）', async () => {
    fetchMock.mockResolvedValue(res({ ok: true, cancelled: 1, inflight: [{ task_id: 'g1' }] }));
    const r = await stopAgentTask('t1');
    expect(r.inflight).toEqual([{ task_id: 'g1' }]);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/tasks/t1/stop');
  });

  it('postAgentTaskGuidance：body 仅 {id,text}（轮间注入登记）', async () => {
    fetchMock.mockResolvedValue(res({ ok: true }));
    await postAgentTaskGuidance('t1', 'q9', '换个风格');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/agent/tasks/t1/guidance');
    expect(JSON.parse(init.body)).toEqual({ id: 'q9', text: '换个风格' });
  });
});

describe('agent.ts 关键端点拼装', () => {
  it('canvasLlm：非流式 POST /api/agent/chat', async () => {
    fetchMock.mockResolvedValue(res({ text: 'ok' }));
    const req = { message: '规划' } as AgentChatRequest;
    await canvasLlm(req);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/agent/chat');
    expect(JSON.parse(init.body)).toEqual(req);
  });

  it('getSkills：skills 缺省回落空数组（新建项目无技能不崩）', async () => {
    fetchMock.mockResolvedValueOnce(res({ skills: [{ id: 'doc:s1', name: 'S1' }] }));
    expect(await getSkills()).toHaveLength(1);
    fetchMock.mockResolvedValueOnce(res({}));
    expect(await getSkills()).toEqual([]);
  });

  it('getContextUsage：model 编码进查询串；无 model 不带查询串', async () => {
    fetchMock.mockResolvedValue(res({ chars: 1 }));
    await getContextUsage('模型 A');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/context-usage?model=%E6%A8%A1%E5%9E%8B%20A');
    await getContextUsage();
    expect(fetchMock.mock.calls[1][0]).toBe('/api/agent/context-usage');
  });

  it('运行时设置：GET/PUT /api/settings/runtime', async () => {
    fetchMock.mockResolvedValue(res({ model_fallback_enabled: true }));
    await getRuntimeSettings();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/runtime');
    await setRuntimeSettings({ model_fallback_enabled: false } as never);
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe('/api/settings/runtime');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ model_fallback_enabled: false });
  });

  it('看板指标端点：GET /api/agent/metrics', async () => {
    fetchMock.mockResolvedValue(res({ traces_count: 0 }));
    await getAgentMetrics();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/metrics');
  });
});
