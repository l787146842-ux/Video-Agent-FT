import { createSignal } from 'solid-js';
import {
  getSkillRefs, getSkillRef, saveSkillRef, deleteSkillRef,
  type SkillRefItem,
} from '@/api/docs';
import { selectedSlug } from '@/stores/skill-studio';
import { showToast } from '@/stores/toast';

/**
 * Skill 分册（references/）状态：可见、可读、可编辑。
 *
 * 分册承载模板类长细节，主文档只留路由。此前工作台完全看不到 references/，
 * 等于分册「存在但不可维护」（2026-11-11 裁决：工作台必须补入口）。
 *
 * 自 skill-studio.ts 拆出（前端 250 行红线），后者重导出保持调用方零改动。
 */

const [refs, setRefs] = createSignal<SkillRefItem[]>([]);
/** 当前选中 Skill 的分册清单（未选中/新建草稿时为空） */
export { refs };
/** '' = 收起；'' 以外 = 正在查看/编辑的分册文件名 */
const [refOpen, setRefOpen] = createSignal('');
export { refOpen, setRefOpen };
const [refContent, setRefContent] = createSignal('');
export { refContent, setRefContent };
const [refDirty, setRefDirty] = createSignal(false);
export { refDirty, setRefDirty };
const [refBusy, setRefBusy] = createSignal(false);
export { refBusy };

/** 清空分册面板状态（切换选中 Skill / 新建草稿时调用） */
export function resetSkillRefState(): void {
  setRefs([]);
  setRefOpen('');
  setRefContent('');
  setRefDirty(false);
}

/** 重新拉取当前 Skill 的分册清单（选中切换、保存/删除分册后调用） */
export async function loadSkillRefs(): Promise<void> {
  const slug = selectedSlug();
  if (!slug) { setRefs([]); return; }
  try {
    setRefs(await getSkillRefs(slug));
  } catch {
    setRefs([]);
  }
}

/** 打开某个分册查看/编辑（拉全文） */
export async function openSkillRef(name: string): Promise<void> {
  const slug = selectedSlug();
  if (!slug) return;
  setRefBusy(true);
  try {
    const r = await getSkillRef(slug, name);
    setRefOpen(name);
    setRefContent(r.content || '');
    setRefDirty(false);
  } catch (err) {
    showToast(`分册读取失败：${(err as Error).message}`, 'error');
  } finally {
    setRefBusy(false);
  }
}

/** 收起分册面板（有未保存改动时提示，不静默丢弃） */
export function closeSkillRef(): void {
  if (refDirty() && !window.confirm('分册有未保存的修改，确定放弃？')) return;
  setRefOpen('');
  setRefContent('');
  setRefDirty(false);
}

/** 保存当前分册：以 refOpen() 的文件名为准（新建时即用户在编辑器顶部的名字）。
 * 新建与覆盖同一条路径，后端按「不存在则创建」处理。 */
export async function saveSkillRefDraft(): Promise<void> {
  const slug = selectedSlug();
  const target = refOpen().trim();
  if (!slug || !target) return;
  setRefBusy(true);
  try {
    await saveSkillRef(slug, target, refContent());
    await loadSkillRefs();
    setRefDirty(false);
    showToast('分册已保存', 'success');
  } catch (err) {
    showToast(`分册保存失败：${(err as Error).message}`, 'error');
  } finally {
    setRefBusy(false);
  }
}

/** 新建空白分册：打开编辑器、填入骨架，等用户编辑后点保存落盘。
 * 不预先落盘（避免库里凭空多出空分册）。 */
export function newSkillRef(name?: string): void {
  if (!selectedSlug()) {
    showToast('请先保存 Skill，再新建分册', 'warning');
    return;
  }
  let target = (name || '').trim();
  if (!target) {
    const exists = new Set(refs().map((r) => r.name));
    target = '新分册.md';
    let n = 2;
    while (exists.has(target)) target = `新分册-${n++}.md`;
  }
  setRefOpen(target);
  setRefContent(`# ${target.replace(/\.md$/, '')}\n\n`);
  setRefDirty(true);
}

/** 删除分册（二次确认） */
export async function removeSkillRef(name: string): Promise<void> {
  const slug = selectedSlug();
  if (!slug) return;
  if (!window.confirm(`删除分册「${name}」？主文档里对它的引用会变成悬空指针。`)) return;
  try {
    await deleteSkillRef(slug, name);
    if (refOpen() === name) { setRefOpen(''); setRefContent(''); setRefDirty(false); }
    await loadSkillRefs();
    showToast('分册已删除', 'success');
  } catch (err) {
    showToast(`分册删除失败：${(err as Error).message}`, 'error');
  }
}
