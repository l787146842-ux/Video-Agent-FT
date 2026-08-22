/**
 * api 旁路模块端点拼装测试（任务 #30 E6 覆盖率补洼地：canvas/conversations/docs/project）。
 *
 * 四模块均为 client 薄封装，测试钉死 URL 路径、查询串编码与 body 契约，
 * 防止端点字符串在组件侧漂移（后端 routes 契约对齐）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  dropImageToCanvas, fetchCanvasNodeImages, fetchAllCanvasNodeImages, fetchCanvasList,
} from '../canvas';
import {
  getConversations, createConversation, activateConversation, deleteConversation,
  createSnapshot, branchSnapshot,
} from '../conversations';
import {
  getSkillDocs, getSkillDocHistory, saveSkillDoc, formatSkillContent, deleteSkillDoc,
} from '../docs';
import {
  getProjects, getProjectState, createProject, switchProject, deleteProject,
  saveProjectDocument, deleteProjectDocument, putProjectState,
  undoAction, redoAction, getUndoStatus, checkpointUndo,
} from '../project';

const fetchMock = vi.fn();

function res(body: unknown, status = 200): Response {
  return {
    ok: status < 300, status, statusText: 'OK',
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset().mockResolvedValue(res({}));
  vi.stubGlobal('fetch', fetchMock);
});

const lastCall = () => fetchMock.mock.calls[fetchMock.mock.calls.length - 1];

describe('canvas.ts 画布交互端点', () => {
  it('dropImageToCanvas：POST /api/canvas/drop-image 原样携带 payload', async () => {
    const payload = { image_url: '/a.png', drop: { x: 1, y: 2 } };
    await dropImageToCanvas(payload as never);
    const [url, init] = lastCall();
    expect(url).toBe('/api/canvas/drop-image');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual(payload);
  });

  it('fetchCanvasNodeImages / fetchCanvasList：只读 GET', async () => {
    await fetchCanvasNodeImages();
    expect(lastCall()[0]).toBe('/api/canvas/node-images');
    await fetchCanvasList();
    expect(lastCall()[0]).toBe('/api/canvas/list');
  });

  it('fetchAllCanvasNodeImages：canvas_id 编码进查询串；缺省不带', async () => {
    await fetchAllCanvasNodeImages('画布 A');
    expect(lastCall()[0]).toBe('/api/canvas/all-node-images?canvas_id=%E7%94%BB%E5%B8%83%20A');
    await fetchAllCanvasNodeImages();
    expect(lastCall()[0]).toBe('/api/canvas/all-node-images');
  });
});

describe('conversations.ts 多对话管理端点', () => {
  it('getConversations / createConversation：GET 列表 + POST 新建带 title', async () => {
    await getConversations();
    expect(lastCall()[0]).toBe('/api/conversations');
    await createConversation('新对话');
    const [url, init] = lastCall();
    expect(url).toBe('/api/conversations');
    expect(JSON.parse(init.body)).toEqual({ title: '新对话' });
  });

  it('activateConversation / deleteConversation：id 编码进路径', async () => {
    await activateConversation('c/1');
    expect(lastCall()[0]).toBe('/api/conversations/c%2F1/activate');
    await deleteConversation('c 2');
    const [url, init] = lastCall();
    expect(url).toBe('/api/conversations/c%202');
    expect(init.method).toBe('DELETE');
  });

  it('快照与分支（B11）：snapshot POST + branch 路径携 snap_id', async () => {
    await createSnapshot();
    expect(lastCall()[0]).toBe('/api/conversations/snapshot');
    await branchSnapshot('s 1', '分支');
    const [url, init] = lastCall();
    expect(url).toBe('/api/conversations/snapshots/s%201/branch');
    expect(JSON.parse(init.body)).toEqual({ title: '分支' });
  });
});

describe('docs.ts Skill 文档端点', () => {
  it('getSkillDocs：docs 缺省回落空数组', async () => {
    fetchMock.mockResolvedValueOnce(res({ docs: [{ slug: 's', name: 'S' }] }));
    expect(await getSkillDocs()).toHaveLength(1);
    fetchMock.mockResolvedValueOnce(res({}));
    expect(await getSkillDocs()).toEqual([]);
  });

  it('getSkillDocHistory：slug 编码进路径；versions 缺省回落空数组', async () => {
    fetchMock.mockResolvedValueOnce(res({ versions: [{ version: 'v1', content: 'c' }] }));
    expect(await getSkillDocHistory('技能 A')).toHaveLength(1);
    expect(lastCall()[0]).toBe('/api/skills/docs/%E6%8A%80%E8%83%BD%20A/history');
    fetchMock.mockResolvedValueOnce(res({}));
    expect(await getSkillDocHistory('s')).toEqual([]);
  });

  it('saveSkillDoc：PUT 携 content；formatSkillContent：POST /format；deleteSkillDoc：DELETE', async () => {
    await saveSkillDoc('s1', '# 正文');
    let [url, init] = lastCall();
    expect(url).toBe('/api/skills/docs/s1');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ content: '# 正文' });

    await formatSkillContent('草稿');
    [url, init] = lastCall();
    expect(url).toBe('/api/skills/format');
    expect(JSON.parse(init.body)).toEqual({ content: '草稿' });

    await deleteSkillDoc('s1');
    [url, init] = lastCall();
    expect(url).toBe('/api/skills/docs/s1');
    expect(init.method).toBe('DELETE');
  });
});

describe('project.ts 项目管理端点', () => {
  it('列表/状态读取：GET /list 与 /state', async () => {
    await getProjects();
    expect(lastCall()[0]).toBe('/api/project/list');
    await getProjectState();
    expect(lastCall()[0]).toBe('/api/project/state');
  });

  it('新建/切换/删除：POST 携 project_id 或 name', async () => {
    await createProject('项目X');
    expect(JSON.parse(lastCall()[1].body)).toEqual({ name: '项目X' });
    expect(lastCall()[0]).toBe('/api/project/new');
    await switchProject('p1');
    expect(lastCall()[0]).toBe('/api/project/switch');
    expect(JSON.parse(lastCall()[1].body)).toEqual({ project_id: 'p1' });
    await deleteProject('p1');
    expect(lastCall()[0]).toBe('/api/project/delete');
  });

  it('项目文档保存/删除：PUT upsert + POST delete', async () => {
    await saveProjectDocument('大纲', 'v2');
    let [url, init] = lastCall();
    expect(url).toBe('/api/project/document');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ name: '大纲', content: 'v2' });
    await deleteProjectDocument('大纲');
    [url, init] = lastCall();
    expect(url).toBe('/api/project/document/delete');
    expect(JSON.parse(init.body)).toEqual({ name: '大纲' });
  });

  it('状态整体 PUT 与撤销栈端点族', async () => {
    await putProjectState({ project_id: 'p1', assets: [] });
    const [url, init] = lastCall();
    expect(url).toBe('/api/project/state');
    expect(init.method).toBe('PUT');
    await undoAction();
    expect(lastCall()[0]).toBe('/api/project/undo');
    await redoAction();
    expect(lastCall()[0]).toBe('/api/project/redo');
    await getUndoStatus();
    expect(lastCall()[0]).toBe('/api/project/undo-status');
    await checkpointUndo();
    expect(lastCall()[0]).toBe('/api/project/undo-checkpoint');
  });
});
