import { createSignal } from 'solid-js';
import {
  getSkillDocs, getSkillLoadFailures, saveSkillDoc, deleteSkillDoc,
  openSkillAssistantStream,
  type SkillDoc, type SkillLoadFailure, type SkillAssistantChecks,
} from '@/api/docs';
import {
  consumeSkillAssistantStream, type SkillAssistantFrame,
} from '@/lib/skill-assistant-stream';
import type { SkillAssistantMessage } from '@/types/api.generated';
import { refreshSkills } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { agentProvider, agentModel } from '@/stores/agent-prefs';
import {
  parseSkillStructure, serializeSkillStructure, sanitizeSkillSlug, blankSkillTemplate,
  frontmatterMeta,
} from '@/lib/skill-structure';

/**
 * Skill 工作台状态（/skills 路由）：
 * 左栏库列表 / 中间草稿（raw 单一数据源 + undo/redo）/ 右栏优化助手。
 * 助手会话级不持久化；草稿落盘一律显式点保存。
 */

// ---------- 库与选中 ----------
const [allDocs, setAllDocs] = createSignal<SkillDoc[]>([]);
const [loadFailures, setLoadFailures] = createSignal<SkillLoadFailure[]>([]);
const [selectedSlug, setSelectedSlug] = createSignal(''); // '' = 新建草稿
const [studioLoading, setStudioLoading] = createSignal(false);
export { allDocs, loadFailures, selectedSlug, studioLoading };

export async function loadAllDocs(): Promise<void> {
  setStudioLoading(true);
  try {
    setAllDocs(await getSkillDocs());
  } catch {
    setAllDocs([]);
  }
  // 坏包旁路：单独取失败清单，失败也不影响好包列表
  try {
    setLoadFailures(await getSkillLoadFailures());
  } catch {
    setLoadFailures([]);
  } finally {
    setStudioLoading(false);
  }
}

// ---------- 草稿与撤销栈 ----------
const [draftRaw, setDraftRaw] = createSignal('');
const [dirty, setDirty] = createSignal(false);
export { draftRaw, dirty };
// 编辑态（工作台受控）：只有「新建」与「编辑」两种状态才挂出优化助手右栏，
// 纯查看时保持两栏（左列表 + 中结构化视图）。
const [studioEditing, setStudioEditing] = createSignal(false);
export { studioEditing, setStudioEditing };
/** 右栏是否出现：新建草稿（未落盘）或正在编辑既有 Skill */
export function assistantVisible(): boolean {
  return studioEditing() || !selectedSlug();
}
let undoStack: string[] = [];
let redoStack: string[] = [];
const [stackTick, setStackTick] = createSignal(0);
const bumpStack = () => setStackTick((n) => n + 1);

function resetStacks() {
  undoStack = [];
  redoStack = [];
  bumpStack();
}

export function selectSkill(slug: string) {
  const doc = allDocs().find((d) => d.slug === slug);
  if (!doc) return;
  setSelectedSlug(slug);
  setDraftRaw(doc.content || '');
  setDirty(false);
  setStudioEditing(false);
  resetStacks();
}

export function newDraft() {
  setSelectedSlug('');
  setDraftRaw(blankSkillTemplate());
  setDirty(true);
  setStudioEditing(false);
  resetStacks();
}

/** 与落盘内容比对计算 dirty：新建草稿恒脏；undo 回原文自动清脏 */
function computeDirty(raw: string): boolean {
  const slug = selectedSlug();
  if (!slug) return true;
  const saved = allDocs().find((d) => d.slug === slug)?.content;
  return saved === undefined ? true : saved !== raw;
}

/** 覆盖草稿（助手改写/行内更新共用）：入撤销栈、重算 dirty */
export function commitDraft(next: string) {
  if (next === draftRaw()) return;
  undoStack.push(draftRaw());
  if (undoStack.length > 50) undoStack.shift();
  redoStack = [];
  setDraftRaw(next);
  setDirty(computeDirty(next));
  bumpStack();
}

export function canUndo(): boolean { void stackTick(); return undoStack.length > 0; }
export function canRedo(): boolean { void stackTick(); return redoStack.length > 0; }

export function undoDraft() {
  const prev = undoStack.pop();
  if (prev === undefined) return;
  redoStack.push(draftRaw());
  setDraftRaw(prev);
  setDirty(computeDirty(prev));
  bumpStack();
}

export function redoDraft() {
  const next = redoStack.pop();
  if (next === undefined) return;
  undoStack.push(draftRaw());
  setDraftRaw(next);
  setDirty(computeDirty(next));
  bumpStack();
}

function uniqueSlug(base: string): string {
  let slug = base;
  let n = 2;
  while (allDocs().some((d) => d.slug === slug)) slug = `${base}-${n++}`;
  return slug;
}

/** 保存草稿：新建草稿按标题生成 slug（重名自动 -2 后缀） */
export async function saveDraft(): Promise<void> {
  const raw = draftRaw();
  let slug = selectedSlug();
  if (!slug) {
    // 名称权威：正文 `# ` 标题优先，无则回落 frontmatter 元数据（批 C）
    const base = sanitizeSkillSlug(parseSkillStructure(raw).name || frontmatterMeta(raw).name);
    if (!base) {
      showToast('Skill 名称不合法，无法生成标识', 'error');
      return;
    }
    slug = uniqueSlug(base);
  }
  try {
    const res = await saveSkillDoc(slug, raw);
    (res?.lint?.warnings || []).forEach((w) => showToast(`⚠ ${w}`, 'warning'));
    await refreshSkills();
    await loadAllDocs();
    setSelectedSlug(slug);
    setDirty(false);
    showToast('已保存', 'success');
  } catch (err) {
    showToast(`保存失败：${(err as Error).message}`, 'error');
  }
}

/** 另存为副本：标题追加（副本）后存为新 Skill */
export async function saveSkillCopy(raw: string): Promise<void> {
  const s = parseSkillStructure(raw);
  // 原名：正文标题优先，无则回落 frontmatter 元数据（批 C）
  const originName = s.name || frontmatterMeta(raw).name || '未命名 Skill';
  const baseName = `${originName}（副本）`;
  s.name = baseName;
  // 副本 frontmatter name 同步改名，保证元数据权威口径与副本标题一致
  if (s.frontmatter && /^\s*name\s*:/m.test(s.frontmatter)) {
    s.frontmatter = s.frontmatter.replace(/^(\s*name\s*:\s*).*/m, `$1${baseName}`);
  }
  const slug = uniqueSlug(sanitizeSkillSlug(baseName) || 'skill-copy');
  try {
    await saveSkillDoc(slug, serializeSkillStructure(s));
    await refreshSkills();
    await loadAllDocs();
    showToast(`已另存为副本「${baseName}」`, 'success');
  } catch (err) {
    showToast(`另存失败：${(err as Error).message}`, 'error');
  }
}

export async function removeSkill(slug: string): Promise<void> {
  try {
    await deleteSkillDoc(slug);
    await refreshSkills();
    await loadAllDocs();
    if (selectedSlug() === slug) newDraft();
    showToast('已删除', 'success');
  } catch (err) {
    showToast(`删除失败：${(err as Error).message}`, 'error');
  }
}

// ---------- 优化助手（会话级） ----------
export interface AssistantMsg {
  role: 'user' | 'assistant';
  text: string;
  /** 推理模型思考全文（流式累积，done 后固化可折叠回看） */
  reasoning?: string;
  /** 本轮请求模式（决定自检徽标的检查口径文案） */
  mode?: 'create' | 'optimize';
  /** 创作/优化后端的项目规范自检结果（无全文可查时为空） */
  checks?: SkillAssistantChecks | null;
}

/** 流式中的助手回合：与已完成消息分开，避免逐帧重建历史气泡 */
export interface AssistantStream {
  reasoning: string;
  text: string;
  /** 文档正文增量（中间预览实时跟随；done 后由 content 权威覆盖） */
  doc: string;
  /** 过程状态（自检/自修复等，非正文） */
  status: string;
}

const [assistantMessages, setAssistantMessages] = createSignal<AssistantMsg[]>([]);
const [assistantBusy, setAssistantBusy] = createSignal(false);
const [assistantStream, setAssistantStream] = createSignal<AssistantStream | null>(null);
export { assistantMessages, assistantBusy, assistantStream };
/** 中间预览的实时草稿（空 = 未在生成，预览显示已提交草稿） */
export function assistantLiveDoc(): string { return assistantStream()?.doc || ''; }
/** 在途请求：离页/重置即中断，不在后台空烧 token */
let assistantAbort: AbortController | null = null;

export function resetAssistant() {
  assistantAbort?.abort();
  assistantAbort = null;
  setAssistantMessages([]);
  setAssistantStream(null);
  setAssistantBusy(false);
}

/** 发送用户请求（SSE 流式）：思考/正文实时入流式气泡；done 帧收口为正式消息
 * （reply 覆盖正文展示，content 覆盖草稿入撤销栈）。流断时保留已收内容。 */
export async function sendAssistant(text: string): Promise<void> {
  const msg = text.trim();
  if (!msg || assistantBusy()) return;
  setAssistantMessages((m) => [...m, { role: 'user', text: msg }]); setAssistantBusy(true);
  setAssistantStream({ reasoning: '', text: '', doc: '', status: '' });
  const mode = selectedSlug() ? 'optimize' : 'create';
  const history: SkillAssistantMessage[] = assistantMessages().slice(-10).map((m) => ({ role: m.role, content: m.text }));
  const abort = new AbortController();
  assistantAbort = abort;
  // 容器持有 done 帧：闭包赋值 + TS 控制流不追踪局部变量（会窄化为 never）
  const collected: { done: Extract<SkillAssistantFrame, { type: 'done' }> | null } = { done: null };
  let failure = '';
  try {
    const body = await openSkillAssistantStream({
      content: draftRaw(),
      messages: history,
      provider: agentProvider(),
      model: agentModel(),
      mode,
    }, abort.signal);
    await consumeSkillAssistantStream(body, (frame) => {
      if (frame.type === 'reasoning_delta') {
        setAssistantStream((s) => (s ? { ...s, reasoning: s.reasoning + frame.text } : s));
      } else if (frame.type === 'delta') {
        setAssistantStream((s) => (s ? { ...s, text: s.text + frame.text } : s));
      } else if (frame.type === 'doc_delta') {
        setAssistantStream((s) => (s ? { ...s, doc: s.doc + frame.text } : s));
      } else if (frame.type === 'status') {
        setAssistantStream((s) => (s ? { ...s, status: frame.text } : s));
      } else if (frame.type === 'done') {
        collected.done = frame;
      } else if (frame.type === 'error') {
        failure = frame.message;
      }
    }, abort.signal);
  } catch (err) {
    failure = (err as Error).message;
  } finally {
    // 离页/重置已中断：不留残留消息（流式气泡已由 resetAssistant 清空）
    if (assistantAbort === abort) {
      const streamed = assistantStream();
      const reasoning = streamed?.reasoning || undefined;
      const partialText = streamed?.text.trim() || '';
      if (collected.done) {
        const fin = collected.done;
        setAssistantMessages((m) => [...m, {
          role: 'assistant',
          text: fin.reply || '（空回复）',
          reasoning,
          mode,
          checks: fin.checks ?? null,
        }]);
        if (fin.content) commitDraft(fin.content);
        else {
          // 模型未产出可解析的全文：明确告知预览未动（避免「以为改好了」）
          showToast('本轮未解析到完整 Skill 全文，左侧预览未更新', 'warning');
        }
      } else {
        const reasonNote = failure || '流式连接中断，回复可能不完整';
        setAssistantMessages((m) => [...m, {
          role: 'assistant',
          text: partialText ? `${partialText}\n\n（${reasonNote}）` : `请求失败：${reasonNote}`,
          reasoning,
          mode,
        }]);
        // 中断的文档不落草稿：清空实时预览，避免半成品被误当成已保存内容
        if (streamed?.doc) showToast('生成中断，本轮预览未更新', 'warning');
      }
      assistantAbort = null;
      setAssistantStream(null);
      setAssistantBusy(false);
    }
  }
}
