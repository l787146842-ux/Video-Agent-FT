import { createSignal } from 'solid-js';
import {
  getSkillDocs, getSkillLoadFailures, saveSkillDoc, deleteSkillDoc,
  type SkillDoc, type SkillLoadFailure,
} from '@/api/docs';
import { loadSkillRefs, resetSkillRefState } from '@/stores/skill-refs';
import { wireAssistant } from '@/stores/skill-assistant';
import { refreshSkills } from '@/stores/studio';
import { showToast } from '@/stores/toast';
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
  // 分册清单随选中切换（新建草稿无分册）
  resetSkillRefState();
  void loadSkillRefs();
}

export function newDraft() {
  setSelectedSlug('');
  setDraftRaw(blankSkillTemplate());
  setDirty(true);
  setStudioEditing(false);
  resetStacks();
  resetSkillRefState();
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

// ---------- 分册（references/）状态已拆至 stores/skill-refs.ts ----------
// 分册清单/编辑/保存/删除的 signal 与动作见 skill-refs.ts（250 行红线拆分）；
// 原路径在此重导出，调用方零改动。
export {
  refs, refOpen, setRefOpen, refContent, setRefContent, refDirty, setRefDirty,
  refBusy, loadSkillRefs, openSkillRef, closeSkillRef, saveSkillRefDraft,
  newSkillRef, removeSkillRef, resetSkillRefState,
} from './skill-refs';

// ---------- 优化助手（会话级）已拆至 stores/skill-assistant.ts ----------
// 流式状态与发送动作见 skill-assistant.ts（250 行红线拆分）；
// 依赖注入 wireAssistant 由下方在模块初始化时完成。
export {
  assistantMessages, assistantBusy, assistantStream, assistantLiveDoc,
  resetAssistant, sendAssistant, wireAssistant,
  type AssistantMsg, type AssistantStream,
} from './skill-assistant';

wireAssistant({ draftRaw, selectedSlug, commitDraft });

