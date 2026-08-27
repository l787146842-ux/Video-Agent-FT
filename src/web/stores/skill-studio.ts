import { createSignal } from 'solid-js';
import {
  getSkillDocs, saveSkillDoc, deleteSkillDoc, assistantSkillChat, type SkillDoc,
} from '@/api/docs';
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
const [selectedSlug, setSelectedSlug] = createSignal(''); // '' = 新建草稿
const [studioLoading, setStudioLoading] = createSignal(false);
export { allDocs, selectedSlug, studioLoading };

export async function loadAllDocs(): Promise<void> {
  setStudioLoading(true);
  try {
    setAllDocs(await getSkillDocs());
  } catch {
    setAllDocs([]);
  } finally {
    setStudioLoading(false);
  }
}

// ---------- 草稿与撤销栈 ----------
const [draftRaw, setDraftRaw] = createSignal('');
const [dirty, setDirty] = createSignal(false);
export { draftRaw, dirty };
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
  resetStacks();
}

export function newDraft() {
  setSelectedSlug('');
  setDraftRaw(blankSkillTemplate());
  setDirty(true);
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
export interface AssistantMsg { role: 'user' | 'assistant'; text: string; }

const [assistantMessages, setAssistantMessages] = createSignal<AssistantMsg[]>([]);
const [assistantBusy, setAssistantBusy] = createSignal(false);
export { assistantMessages, assistantBusy };

export function resetAssistant() {
  setAssistantMessages([]);
}

/** 发送用户请求：回复入列；解析出全文则覆盖草稿（入撤销栈） */
export async function sendAssistant(text: string): Promise<void> {
  const msg = text.trim();
  if (!msg || assistantBusy()) return;
  setAssistantMessages((m) => [...m, { role: 'user', text: msg }]);
  setAssistantBusy(true);
  try {
    const history: SkillAssistantMessage[] = assistantMessages().slice(-10)
      .map((m) => ({ role: m.role, content: m.text }));
    const res = await assistantSkillChat({
      content: draftRaw(),
      messages: history,
      provider: agentProvider(),
      model: agentModel(),
    });
    setAssistantMessages((m) => [...m, { role: 'assistant', text: res.reply || '（空回复）' }]);
    if (res.content) commitDraft(res.content);
  } catch (err) {
    setAssistantMessages((m) => [...m, {
      role: 'assistant', text: `请求失败：${(err as Error).message}`,
    }]);
  } finally {
    setAssistantBusy(false);
  }
}
