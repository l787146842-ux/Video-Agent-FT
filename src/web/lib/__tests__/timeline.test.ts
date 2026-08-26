import { describe, it, expect } from 'vitest';
import {
  approvalInteractionLabel, argsPreviewEntries, consolidateTimeline, formatElapsed,
  resultSummaryView, timelineFromMessage, toolApprovalTier, toolDetailTier, type TimelineItem,
} from '../timeline';
import type { ChatMessage } from '@/types';

/** 时间线降噪：连续规划条目合并（纯函数钉死） */

const reasoning = (step: number, ms: number, status: TimelineItem['status'] = 'done'): TimelineItem => ({
  id: `llm-s${step}`,
  summary: `模型创作规划（节点内第 ${step} 轮）`,
  status,
  elapsed_ms: ms,
});
const tool = (id: string, ms: number): TimelineItem => ({
  id, summary: `工具 ${id}`, status: 'done', elapsed_ms: ms,
});

describe('consolidateTimeline 规划条目合并', () => {
  it('连续多条规划条目合并为单条（N 轮 + 累计耗时 + 明细保留）', () => {
    const out = consolidateTimeline([reasoning(1, 1200), reasoning(2, 800), reasoning(3, 1000)]);
    expect(out.length).toBe(1);
    expect(out[0].summary).toBe('模型创作 3 步 · 累计 3.0s');
    expect(out[0].elapsed_ms).toBe(3000);
    expect(out[0].details?.length).toBe(3);
  });

  it('工具条目不被合并且切断规划段', () => {
    const out = consolidateTimeline([
      reasoning(1, 500), tool('t1', 100), reasoning(2, 500), reasoning(3, 500),
    ]);
    expect(out.length).toBe(3);
    expect(out[0].id).toBe('llm-s1'); // 单条不合并
    expect(out[1].id).toBe('t1');
    expect(out[2].details?.length).toBe(2);
  });

  it('单条规划不合并（无信息增益）', () => {
    const out = consolidateTimeline([reasoning(1, 900)]);
    expect(out.length).toBe(1);
    expect(out[0].id).toBe('llm-s1');
    expect(out[0].details).toBeUndefined();
  });

  it('段内含 running 条目（流式中）不合并，保持实时逐条可见', () => {
    const out = consolidateTimeline([reasoning(1, 700), reasoning(2, 0, 'running')]);
    expect(out.length).toBe(2);
    expect(out[1].status).toBe('running');
  });

  it('空列表返回空列表', () => {
    expect(consolidateTimeline([])).toEqual([]);
  });
});

describe('formatElapsed', () => {
  it('<100ms 显示毫秒且至少 1ms', () => {
    expect(formatElapsed(0)).toBe('1ms');
    expect(formatElapsed(60)).toBe('60ms');
  });
  it('>=100ms 显示秒（一位小数）', () => {
    expect(formatElapsed(1200)).toBe('1.2s');
  });
});

describe('resultSummaryView 详情展开视图', () => {
  it('单句摘要（句末标点收尾）→ 不可展开，折叠即全文', () => {
    expect(resultSummaryView('分析完成。')).toEqual({ expandable: false, collapsed: '分析完成。' });
    expect(resultSummaryView('产出 3 张图')).toEqual({ expandable: false, collapsed: '产出 3 张图' });
  });

  it('多句摘要 → 可展开，折叠态只留首句（含句末标点）', () => {
    const view = resultSummaryView('已写入规格文档。含分镜与音色两节，待确认。');
    expect(view.expandable).toBe(true);
    expect(view.collapsed).toBe('已写入规格文档。');
  });

  it('换行切分：首行即折叠态，其余行展开可见', () => {
    const view = resultSummaryView('素材清单已生成\n- 图A\n- 图B');
    expect(view.expandable).toBe(true);
    expect(view.collapsed).toBe('素材清单已生成');
  });

  it('空文本 → 不可展开且折叠为空', () => {
    expect(resultSummaryView('')).toEqual({ expandable: false, collapsed: '' });
    expect(resultSummaryView('   ')).toEqual({ expandable: false, collapsed: '' });
  });
});

/** 工具详情分级（后端 detail_tier 元数据驱动，纯函数钉死） */
describe('toolDetailTier 工具详情分级', () => {
  it('值得展开档：产出/关键交互类工具（后端 detail_tier=expand 声明生成）', () => {
    [
      'document_write', 'storyboard_create_group', 'storyboard_add_draft',
      'storyboard_patch_draft', 'generate_image', 'generate_video',
      'image_generate', 'workflow_pause', 'canvas_add_node',
      'canvas_update_node', 'canvas_batch_add_nodes',
    ].forEach((n) => expect(toolDetailTier(n)).toBe('expand'));
  });

  it('输出留痕档：读取/平台闸口类工具（后端 detail_tier=output 声明生成）', () => {
    [
      'storyboard_delete_group', 'canvas_delete_node', 'storyboard_confirm_draft',
      'storyboard_media_to_chat', 'read_draft', 'read_project_doc',
      'read_uploaded_doc', 'flow_directive', 'view_storyboard_media',
      'canvas_list', 'canvas_read_nodes', 'canvas_list_assets', 'read_skill',
      'mcp_tool_catalog',
    ].forEach((n) => expect(toolDetailTier(n)).toBe('output'));
  });

  it('默认档：未知工具/无名条目至少留输出痕迹（不再静默 none）', () => {
    expect(toolDetailTier('unknown_tool')).toBe('output');
    expect(toolDetailTier(undefined)).toBe('output');
  });

  it('内部条目恒定 none（TOOL_DETAIL_INTERNAL_NONE 名单登记）', () => {
    expect(toolDetailTier('model_reasoning')).toBe('none');
  });
});

/** 工具审批分级正交轴（任务 P2-5；后端 approval_tier 元数据驱动，纯函数钉死） */
describe('toolApprovalTier 工具审批分级', () => {
  it('confirm 档：生成族首批显式声明 + high 风险推导档（后端生效档生成）', () => {
    [
      'generate_image', 'generate_video', 'image_generate',
      'document_write', 'canvas_add_node', 'canvas_update_node',
      'canvas_delete_node', 'canvas_batch_add_nodes',
    ].forEach((n) => expect(toolApprovalTier(n)).toBe('confirm'));
  });

  it('none 档：只读/可撤销写状态类工具（后端推导档生成）', () => {
    [
      'read_skill', 'read_draft', 'read_uploaded_doc', 'read_project_doc',
      'view_storyboard_media', 'storyboard_media_to_chat', 'canvas_list',
      'canvas_read_nodes', 'canvas_list_assets', 'workflow_pause',
      'flow_directive', 'mcp_tool_catalog',
    ].forEach((n) => expect(toolApprovalTier(n)).toBe('none'));
  });

  it('默认档：未登记工具/无名条目按 high 口径 deny-by-default 一律 confirm', () => {
    expect(toolApprovalTier('unknown_tool')).toBe('confirm');
    expect(toolApprovalTier(undefined)).toBe('confirm');
  });

  it('approvalInteractionLabel 确认卡/审批交互档位映射', () => {
    expect(approvalInteractionLabel('confirm')).toBe('需确认');
    expect(approvalInteractionLabel('review')).toBe('需审批');
    expect(approvalInteractionLabel('none')).toBe('');
  });
});

describe('argsPreviewEntries 输入参数预览', () => {
  it('无 args → 空条目', () => {
    expect(argsPreviewEntries(undefined)).toEqual([]);
    expect(argsPreviewEntries({})).toEqual([]);
  });

  it('字符串值原样；非字符串值 JSON 化', () => {
    const out = argsPreviewEntries({ name: '剧本.md', shots: [1, 2], meta: { k: 'v' } });
    expect(out[0]).toEqual({ key: 'name', value: '剧本.md' });
    expect(out[1]).toEqual({ key: 'shots', value: '[1,2]' });
    expect(out[2].value).toBe('{"k":"v"}');
  });

  it('超长值显示级截断加省略号', () => {
    const out = argsPreviewEntries({ content: 'x'.repeat(200) });
    expect(out[0].value.length).toBe(121);
    expect(out[0].value.endsWith('…')).toBe(true);
  });
});

describe('timelineFromMessage 历史重建（携带 name/args）', () => {
  it('trace 条目的 name/args/result_summary 同步重建', () => {
    const msg = {
      trace: {
        steps: [{
          step: 1,
          actions: [{
            name: 'document_write', summary: '写入文档 剧本.md', elapsed_ms: 120,
            ok: true, result_summary: '已写入。待确认。', args: { content: '预览' },
          }],
        }],
      },
    } as unknown as ChatMessage;
    const { items } = timelineFromMessage(msg);
    expect(items[0].name).toBe('document_write');
    expect(items[0].args).toEqual({ content: '预览' });
    expect(items[0].result_summary).toBe('已写入。待确认。');
    expect(items[0].id).toBe('t-1-0');
  });

  it('model_reasoning 条目重建为 llm-s{step} 同构 id', () => {
    const msg = {
      trace: {
        steps: [{ step: 2, actions: [{ name: 'model_reasoning', summary: '规划', elapsed_ms: 5, ok: true }] }],
      },
    } as unknown as ChatMessage;
    expect(timelineFromMessage(msg).items[0].id).toBe('llm-s2');
  });
});
