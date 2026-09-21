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
import type { ChatMessage, SseEvent, SseSubagentMeta, SubagentThread } from '@/types';
import { SUBAGENT_ACTOR, settledLedgerForMessage, type LedgerItem } from '@/lib/turn-ledger';
import { getSubagentRecord, getSubagentThreads } from '@/api/conversations';
import { t } from '@/lib/locale';
import { chatState, setChatState } from '../chat-core';

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
  /** 子代理思考累计（2026-09-21 批G，事故 4444/Q4）：执行中即可展开查看；
   *  超上限按**尾部**截断（保留最新进展） */
  reasoning?: string;
  startedAt: number;
  finishedAt?: number;
  /** 收尾时绑定的轮次 id（切回/刷新后按轮次把卡重新挂回消息） */
  turnId?: string;
  /** 刷新后由服务端子线程清单重建（步数/状态取服务端口径，子工具名单懒加载） */
  staticSource?: boolean;
  /** 子工具名单是否已懒加载完成（防重复拉只读记录） */
  toolsLoaded?: boolean;
}

/** 子代理思考保留上限（字符）：超出按尾部截断（最新进展优先），
 *  防一次委派数千字思考拖垮渲染（批G）。 */
export const SUBAGENT_REASONING_CAP = 6000;

/** 思考增量入账（带截断）：超上限保留尾部并加省略前缀标记。 */
function capReasoning(text: string): string {
  const s = text || '';
  if (s.length <= SUBAGENT_REASONING_CAP) return s;
  return `…${s.slice(s.length - SUBAGENT_REASONING_CAP)}`;
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

/** 子会话 id 内嵌创建时刻（conv-<epoch秒>-<hex>）→ ms；解析失败返回 0 */
export function cidCreatedAtMs(cid: string): number {
  const m = /^conv-(\d{10,})-/.exec(cid || '');
  return m ? Number(m[1]) * 1000 : 0;
}

/** 把 actors 的槽位插回消息账本（锚定父委派行之后；无委派行则追加尾部）。
 * 已有槽位的消息（live 翻转入库者）不重复插。 */
function insertSlots(m: ChatMessage, actors: SubagentActor[]): void {
  const led = m.ledger || settledLedgerForMessage(m);
  const missing = actors.filter((a) => !led.items.some((it) => it.id === actorSlotId(a.key)));
  if (!missing.length) return;
  const items = [...led.items];
  const anchor = items.map((it) => it.name).lastIndexOf(SUBAGENT_DELEGATE_TOOL);
  let at = anchor >= 0 ? anchor + 1 : items.length;
  for (const a of missing) {
    const slot: LedgerItem = {
      id: actorSlotId(a.key),
      name: SUBAGENT_ACTOR,
      summary: labelOf(a),
      status: a.status === 'running' ? 'running' : a.status === 'failed' ? 'failed' : 'done',
      started_at_ms: a.startedAt,
    };
    items.splice(at, 0, slot);
    at += 1;
  }
  m.ledger = { ...led, items, phase: 'settled' };
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
      } else if (ev.type === 'reasoning_delta') {
        // 2026-09-21 批G（事故 4444/Q4）：子代理思考累计（执行中即可展开查看，
        // 不再「只有做完了才能看到」）。**必须截断**：一次委派思考可达数千字，
        // 不设上限会拖垮渲染（保留**尾部**——最新进展比开头更有信息量）。
        actor.reasoning = capReasoning((actor.reasoning || '') + (ev.text || ''));
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

  /** done 收尾：把尚未绑定轮次的 actor 绑到本轮 turn_id
   * （切走再切回 / 刷新后按轮次把卡重新挂回对应消息） */
  bindTurn(turnId: string): void {
    if (!turnId) return;
    setActorsState(produce((s) => {
      s.list.forEach((a) => { if (!a.turnId) a.turnId = turnId; });
    }));
  },

  /** 切回对话/切项目后：消息从服务端重拉（不带前端账本），按 turnId 把 actor
   *  槽位重新插回各消息的 settled 账本（同页面会话内全保真：步数/子工具名单都在） */
  reattachToMessages(): void {
    const byTurn = new Map<string, SubagentActor[]>();
    for (const a of actorsState.list) {
      if (!a.turnId) continue;
      const arr = byTurn.get(a.turnId) || [];
      arr.push(a);
      byTurn.set(a.turnId, arr);
    }
    if (!byTurn.size) return;
    setChatState(produce((s) => {
      for (const m of s.messages) {
        const actors = m.turnId ? byTurn.get(m.turnId) : undefined;
        if (m.sender !== 'agent' || !actors || !actors.length) continue;
        insertSlots(m, actors);
      }
    }));
  },

  /** 刷新后重建（页面内存已清空）：拉服务端子线程清单造 static actor，按子会话 id
   *  内嵌创建时刻落到「首个 ts ≥ 创建时刻」的 agent 消息轮次；步数/状态取服务端口径，
   *  子工具名单留空、展开时 loadTools 懒加载。失败静默（重建是增强腿非主链） */
  async hydrateFromServer(): Promise<void> {
    try {
      const resp = await getSubagentThreads();
      const threads: SubagentThread[] = resp.subagents || [];
      if (!threads.length) return;
      setActorsState(produce((s) => {
        for (const th of threads) {
          const cid = th.conversation_id || '';
          if (!cid || s.list.some((a) => a.key === cid)) continue;
          s.list.push({
            key: cid,
            cid,
            stage: '',
            label: th.label || th.title || '',
            depth: 1,
            status: th.status === 'running' ? 'running'
              : th.status === 'failed' ? 'failed' : 'completed',
            steps: Number(th.steps || 0) || 0,
            tools: [],
            startedAt: cidCreatedAtMs(cid) || Date.now(),
            staticSource: true,
          });
        }
      }));
      const agents = chatState.messages.filter((m) => m.sender === 'agent' && m.turnId);
      if (!agents.length) return;
      setActorsState(produce((s) => {
        for (const a of s.list) {
          if (a.turnId || !a.cid) continue;
          a.turnId = (agents.find((m) => (m.ts || 0) >= a.startedAt)
            || agents[agents.length - 1]).turnId;
        }
      }));
      subagentActorActions.reattachToMessages();
    } catch { /* 重建腿失败静默：历史消息主链不受影响 */ }
  },

  /** 展开子工具名单时懒加载（static actor 刷新后无名单）：读只读记录的 actionLog */
  async loadTools(cid: string): Promise<void> {
    const actor = actorByKey(cid);
    if (!cid || !actor || actor.toolsLoaded) return;
    setActorsState(produce((s) => {
      const a = s.list.find((x) => x.key === cid);
      if (a) a.toolsLoaded = true;   // 先置位防并发重复拉
    }));
    try {
      const resp = await getSubagentRecord(cid);
      const tools: SubagentActorTool[] = [];
      (resp.messages || []).forEach((m) => {
        (m.actionLog || []).forEach((op, i) => {
          tools.push({
            id: `${cid}-r${i}-${tools.length}`, name: '', summary: op, status: 'done',
          });
        });
      });
      setActorsState(produce((s) => {
        const a = s.list.find((x) => x.key === cid);
        if (a && !a.tools.length) a.tools = tools;
      }));
    } catch { /* 名单拉取失败：卡保留、名单空（不阻断） */ }
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
