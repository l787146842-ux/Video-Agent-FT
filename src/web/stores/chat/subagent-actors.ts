/** Chat store · 子代理 actor 归组域（流式二期，计划书 §四.2）。
 *
 * 一期观感缺口：子代理的工具事件以普通工具卡散落在主 Feed，无「这是子代理在干」
 * 的标识（flova 形态为具名 specialist actor 独立成行）。本域把同一子代理的全部
 * 活动折成一条 actor 状态（label / 阶段 / 实时态 / 步数 / 子工具名单），并在本轮
 * 账本占一个槽位条目（name=subagent_actor）——渲染层据槽位换 SubagentActorCard，
 * 位置紧随父自身 run_subagent 委派卡（委派锚点保留，计划书 §二.3）。
 *
 * 归组键：cid（子隐藏线程 id）；cid 为空（子会话创建失败降级不落流）时按
 * label#depth 兜底（计划书 §七风险 C）。
 * 收尾：父 run_subagent 的 tool_finished（委派独占串行、非 parallel_safe ⇒
 * 同时至多一个子在跑，收尾最近一个 running actor 即无歧义）。
 * 生命周期：live 期累积，随 settleLedger 相位翻转留在消息账本内（卡不闪失）；
 * 运行期不重置——键含 cid 天然唯一，清空会让已 settle 消息的卡失活。
 * 刷新后子活动由隐藏线程记录（SubagentRail）承载，本域不做重建（replay 不携标记）。
 */
import { createSignal } from 'solid-js';
import { createStore, produce } from 'solid-js/store';
import type { SseEvent, SseSubagentMeta } from '@/types';
import { SUBAGENT_ACTOR } from '@/lib/turn-ledger';
import { t } from '@/lib/locale';
import { setChatState } from '../chat-core';

/** 父委派工具名（后端 core/subagent.py::SUBAGENT_TOOL_NAME 同字面）：
 * 只有它的起止帧决定 actor 的收尾时机 */
export const SUBAGENT_DELEGATE_TOOL = 'run_subagent';

/** 账本槽位 id 前缀（渲染层据条目 id 反解 actor 键，约定单一出口） */
const SLOT_PREFIX = 'actor:';

export function actorSlotId(key: string): string {
  return `${SLOT_PREFIX}${key}`;
}

/** 槽位条目 id → actor 键（非槽位 id 返回空串） */
export function actorKeyFromSlotId(id: string): string {
  return id.startsWith(SLOT_PREFIX) ? id.slice(SLOT_PREFIX.length) : '';
}

/** 归组键：cid 优先；空 cid（降级不落流）按 label#depth 兜底 */
export function actorKeyOf(meta: SseSubagentMeta): string {
  const cid = (meta.cid || '').trim();
  if (cid) return cid;
  return `${(meta.label || '').trim() || 'subagent'}#${Number(meta.depth ?? 1) || 1}`;
}

/** actor 卡内的子工具条目（折叠区名单；不占主 Feed 卡位） */
export interface SubagentActorTool {
  id: string;
  name: string;
  summary: string;
  status: 'running' | 'done' | 'failed';
  resultSummary?: string;
  elapsedMs?: number;
}

/** 一个子代理的活动聚合（= 主 Feed 一张 actor 卡的数据源） */
export interface SubagentActor {
  key: string;
  /** 子隐藏线程 id（点击进只读执行记录的凭据；降级不落流时为空 = 不可点） */
  cid: string;
  stage: string;
  label: string;
  depth: number;
  status: 'running' | 'completed' | 'failed';
  /** 子级 state_refresh（actions_applied）累计步数 */
  steps: number;
  tools: SubagentActorTool[];
  startedAt: number;
  finishedAt?: number;
}

const [actorsState, setActorsState] = createStore<{ list: SubagentActor[] }>({ list: [] });

/** 全部 actor（顺序 = 首次出现序 = 委派序） */
export function subagentActors(): SubagentActor[] {
  return actorsState.list;
}

/** 按归组键取 actor（渲染层消费面） */
export function actorByKey(key: string): SubagentActor | undefined {
  return actorsState.list.find((a) => a.key === key);
}

/** 在途委派锚点（父 run_subagent 的 tool_started 帧 id；收尾帧按它认领） */
let pendingAnchor = '';

/** 本轮账本内为该 actor 占/更新一个槽位条目（幂等 upsert；不新增第二张卡） */
function syncSlot(key: string, label: string, status: SubagentActor['status']): void {
  const id = actorSlotId(key);
  const itemStatus = status === 'running' ? 'running' as const
    : status === 'failed' ? 'failed' as const : 'done' as const;
  setChatState(produce((s) => {
    const existing = s.turnLedger.items.find((it) => it.id === id);
    if (existing) {
      existing.summary = label;
      existing.status = itemStatus;
      return;
    }
    s.turnLedger.items.push({
      id,
      name: SUBAGENT_ACTOR,
      summary: label,
      status: itemStatus,
      started_at_ms: Date.now(),
    });
  }));
}

/** 展示标签兜底（后端 label 空时不显空标题） */
function labelOf(actor: { label: string }): string {
  return (actor.label || '').trim() || t('rp.actor.fallbackLabel');
}

export const subagentActorActions = {
  /** 子事件入账（tool_started / tool_finished / actions_applied，均带 subagent 标记）：
   * 首帧建 actor + 占账本槽位，其后只更新该 actor（一条子活动流 = 一张卡） */
  applyChildEvent(meta: SseSubagentMeta, ev: SseEvent): void {
    const key = actorKeyOf(meta);
    let label = '';
    let status: SubagentActor['status'] = 'running';
    setActorsState(produce((s) => {
      let actor = s.list.find((a) => a.key === key);
      if (!actor) {
        actor = {
          key,
          cid: (meta.cid || '').trim(),
          stage: meta.stage || '',
          label: (meta.label || '').trim(),
          depth: Number(meta.depth ?? 1) || 1,
          status: 'running',
          steps: 0,
          tools: [],
          startedAt: Date.now(),
        };
        s.list.push(actor);
      }
      // 降级兜底键（label#depth）下后到帧可能带更完整的 label/cid：只补空不覆盖
      if (!actor.label && (meta.label || '').trim()) actor.label = (meta.label || '').trim();
      if (!actor.cid && (meta.cid || '').trim()) actor.cid = (meta.cid || '').trim();
      if (ev.type === 'tool_started') {
        actor.status = 'running';
        const hit = actor.tools.find((tl) => tl.id === ev.id);
        if (hit) {
          hit.name = ev.name;
          hit.summary = ev.summary;
          hit.status = 'running';
        } else {
          actor.tools.push({
            id: ev.id, name: ev.name, summary: ev.summary, status: 'running',
          });
        }
      } else if (ev.type === 'tool_finished') {
        const hit = actor.tools.find((tl) => tl.id === ev.id);
        if (hit) {
          hit.status = ev.ok ? 'done' : 'failed';
          hit.elapsedMs = ev.elapsed_ms;
          hit.resultSummary = ev.result_summary || undefined;
        }
      } else if (ev.type === 'actions_applied') {
        // 子级 state_refresh：故事板刷新腿保留一期语义（路由侧照旧同步快照），
        // 这里只把批次计数入 actor 步数
        const n = Number(ev.payload?.count ?? ev.count ?? 1) || 1;
        actor.steps += Math.max(1, n);
      }
      label = labelOf(actor);
      status = actor.status;
    }));
    syncSlot(key, label, status);
  },

  /** 父委派帧（未带 subagent 标记的 tool_started / tool_finished）：
   * started 记锚点 id，finished 命中锚点即收尾该 actor（其余工具帧忽略） */
  applyDelegateEvent(ev: SseEvent): void {
    if (ev.type === 'tool_started') {
      if (ev.name === SUBAGENT_DELEGATE_TOOL) pendingAnchor = ev.id;
      return;
    }
    if (ev.type !== 'tool_finished' || !pendingAnchor || ev.id !== pendingAnchor) return;
    pendingAnchor = '';
    const ok = ev.ok !== false;
    let key = '';
    let label = '';
    let status: SubagentActor['status'] = 'running';
    setActorsState(produce((s) => {
      // 委派独占串行 ⇒ 同时至多一个 running actor，倒序取最近一个即本次委派
      for (let i = s.list.length - 1; i >= 0; i -= 1) {
        const actor = s.list[i];
        if (actor.status !== 'running') continue;
        actor.status = ok ? 'completed' : 'failed';
        actor.finishedAt = Date.now();
        // 在途子工具随委派收尾定型（子级崩死时不留旋转图标）
        actor.tools.forEach((tl) => {
          if (tl.status === 'running') tl.status = ok ? 'done' : 'failed';
        });
        key = actor.key;
        label = labelOf(actor);
        status = actor.status;
        break;
      }
    }));
    if (key) syncSlot(key, label, status);
  },
};

// ---------- 只读执行记录的打开请求（actor 卡点击 → 中间面板子任务视图） ----------

const [pendingRecordCid, setPendingRecordCid] = createSignal('');

/** 待打开的子线程 id（SubagentRail 消费后清空；空 = 无请求） */
export function pendingSubagentRecord(): string {
  return pendingRecordCid();
}

/** 登记打开请求（视图切换由调用方组件执行，本域不碰 studio 状态） */
export function requestSubagentRecord(cid: string): void {
  if (cid) setPendingRecordCid(cid);
}

/** 消费完毕清请求（防重复打开） */
export function clearPendingSubagentRecord(): void {
  setPendingRecordCid('');
}

/** 清空全部 actor（测试隔离用；运行期不重置，理由见文件头生命周期段） */
export function resetSubagentActors(): void {
  setActorsState('list', []);
  pendingAnchor = '';
  setPendingRecordCid('');
}
