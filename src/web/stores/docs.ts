import { createSignal } from 'solid-js';
import { state, setState } from '@/stores/studio';
import { saveProjectDocument, deleteProjectDocument } from '@/api/project';
import { getSkillDocs, saveSkillDoc, type SkillDoc } from '@/api/docs';
import { fetchResourceText } from '@/api/client';
import { showToast } from '@/stores/toast';
import type { DocRecord } from '@/types';

/**
 * 文档面板状态：项目文档 / 上传素材 / Skill 文档
 * read（渲染）↔ md（源码）视图切换 + 编辑/保存。
 */

export interface DocCurrent {
  kind: 'project' | 'skill';
  key: string;
}

const [docsPanelOpen, setDocsPanelOpen] = createSignal(false);
const [skillDocs, setSkillDocs] = createSignal<SkillDoc[]>([]);
const [current, setCurrent] = createSignal<DocCurrent | null>(null);
const [editing, setEditing] = createSignal(false);
const [viewMode, setViewMode] = createSignal<'read' | 'md'>('read');
const [draftContent, setDraftContent] = createSignal('');
const [assetContent, setAssetContent] = createSignal('');

/**
 * 当前项目可展示的 Skill 文档：仅限已随消息发送给 Agent 的（state.usedSkills）。
 * 新建项目 usedSkills 为空 → 文档面板 Skill 分区为空；
 * 只有 Skill 引用块随消息发出后才写入展示，模型据此记住流程规则。
 */
export function visibleSkillDocs(): SkillDoc[] {
  const used = state.usedSkills || [];
  return skillDocs().filter((d) => used.includes(d.slug));
}

export async function openDocsPanel(targetName = ''): Promise<void> {
  setDocsPanelOpen(true);
  // 仅当项目已有发送过的 Skill（或指定了目标）时才加载 Skill 文档；
  // 新建项目 usedSkills 为空 → 不加载，文档面板 Skill 分区保持空。
  if (targetName || (state.usedSkills || []).length > 0) {
    try {
      setSkillDocs(await getSkillDocs());
    } catch {
      setSkillDocs([]);
    }
  } else {
    setSkillDocs([]);
  }
  // 定位：优先项目文档，其次上传素材文档，再其次指定的 Skill 文档（仅限已发送过的）
  if (targetName) {
    if ((state.documents || []).some((d) => d.name === targetName)) {
      selectDoc('project', targetName);
      return;
    }
    // 上传素材文档（消息里的文档块点击进来）：拉取全文在面板内展示
    const asset = (state.assets || []).find(
      (a) => a.name === targetName && /\.(md|txt|pdf)$/i.test(a.name || '') && a.url,
    );
    if (asset) {
      try {
        setAssetContent(await fetchResourceText(asset.url));
        selectDoc('project', `__asset__:${targetName}`);
      } catch {
        window.open(asset.url, '_blank');
      }
      return;
    }
    const sd = visibleSkillDocs().find((d) => d.slug === targetName || d.name === targetName);
    if (sd) {
      selectDoc('skill', sd.slug);
      return;
    }
  }
  // 默认选中第一个项目文档（不自动加载/选中 Skill 文档）
  const first = (state.documents || [])[0];
  if (first) selectDoc('project', first.name);
}

export function closeDocsPanel() {
  setDocsPanelOpen(false);
  setEditing(false);
}

export function selectDoc(kind: 'project' | 'skill', key: string) {
  setCurrent({ kind, key });
  setEditing(false);
}

/** 当前文档内容（只读） */
export function currentContent(): string {
  const cur = current();
  if (!cur) return '';
  // 素材文档（__asset__ 前缀）
  if (cur.kind === 'project' && cur.key.startsWith('__asset__:')) {
    return assetContent();
  }
  if (cur.kind === 'project') {
    return (state.documents || []).find((d) => d.name === cur.key)?.content || '';
  }
  return skillDocs().find((d) => d.slug === cur.key)?.content || '';
}

/** 当前文档显示名（项目文档带更新时间） */
export function currentDisplayName(): string {
  const cur = current();
  if (!cur) return '';
  if (cur.kind === 'project' && cur.key.startsWith('__asset__:')) {
    return cur.key.replace('__asset__:', '') + ' · 上传素材';
  }
  if (cur.kind === 'project') {
    const d = (state.documents || []).find((x) => x.name === cur.key);
    return cur.key + (d?.updated_at ? ` · ${String(d.updated_at).replace('T', ' ')}` : '');
  }
  return skillDocs().find((d) => d.slug === cur.key)?.name || cur.key;
}

export function startEdit() {
  setDraftContent(currentContent());
  setEditing(true);
}

export function cancelEdit() {
  setEditing(false);
}

export async function saveCurrentDoc(): Promise<void> {
  const cur = current();
  if (!cur || !editing()) return;
  const content = draftContent();
  try {
    if (cur.kind === 'project') {
      const data = await saveProjectDocument(cur.key, content);
      if (Array.isArray(data.documents)) {
        setState('documents', data.documents as DocRecord[]);
      }
    } else {
      const res = await saveSkillDoc(cur.key, content);
      setSkillDocs((prev) =>
        prev.map((d) => (d.slug === cur.key ? { ...d, content } : d)),
      );
      // 同步技能 system_prompt（doc:slug 关联）
      const sk = state.skills.find((s) => s.id === `doc:${cur.key}`);
      if (sk) sk.system_prompt = content;
      // 保存时 lint 回显（体量/组成/sidecar 声明缺失编辑期可见）
      (res?.lint?.warnings || []).forEach((w) => showToast(`⚠ ${w}`, 'warning'));
    }
    showToast('文档已保存', 'success');
    setEditing(false);
  } catch (e) {
    showToast((e as Error).message || '保存失败', 'error');
  }
}

/** 回滚 Skill 文档到指定历史版本：以历史内容重新保存（后端自动再备份当前版） */
export async function rollbackSkillDoc(slug: string, content: string): Promise<void> {
  try {
    await saveSkillDoc(slug, content);
    setSkillDocs((prev) =>
      prev.map((d) => (d.slug === slug ? { ...d, content } : d)),
    );
    const sk = state.skills.find((s) => s.id === `doc:${slug}`);
    if (sk) sk.system_prompt = content;
    showToast('已回滚到该历史版本', 'success');
  } catch (e) {
    showToast((e as Error).message || '回滚失败', 'error');
  }
}

export async function createDoc(name: string): Promise<void> {
  const trimmed = name.trim();
  if (!trimmed) return;
  const docName = trimmed.endsWith('.md') ? trimmed : `${trimmed}.md`;
  try {
    const data = await saveProjectDocument(docName, '');
    if (Array.isArray(data.documents)) {
      setState('documents', data.documents as DocRecord[]);
    }
    selectDoc('project', docName);
    startEdit();
  } catch (e) {
    showToast((e as Error).message || '新建文档失败', 'error');
  }
}

export async function deleteDoc(name: string): Promise<void> {
  try {
    const data = await deleteProjectDocument(name);
    if (Array.isArray(data.documents)) {
      setState('documents', data.documents as DocRecord[]);
    } else {
      setState('documents', (prev: DocRecord[]) => prev.filter((d) => d.name !== name));
    }
  } catch {
    // 后端接口失败时本地删除
    setState('documents', (prev: DocRecord[]) => prev.filter((d) => d.name !== name));
  }
  // 如果删除的是当前文档，清空选中
  if (current()?.key === name) {
    setCurrent(null);
    setEditing(false);
  }
  showToast(`已删除文档：${name}`, 'success');
}

export {
  docsPanelOpen, skillDocs, current, editing, viewMode,
  setViewMode, draftContent, setDraftContent, assetContent, setAssetContent,
};
