import { createSignal } from 'solid-js';

/**
 * Skill 全局「加入」可用集（Skill 工作台左栏 加入/移除 控制）。
 * localStorage 持久化；null（无记录）= 全部可用（兼容现状：
 * 旧版本所有文档 Skill 都出现在输入框选择器）。
 * 首次 加入/移除 操作时以当前全量列表实体化默认。
 */

const KEY_ENABLED = 'ftdyb.enabledSkills';

function load(): string[] | null {
  try {
    const raw = localStorage.getItem(KEY_ENABLED);
    if (!raw) return null;
    const arr = JSON.parse(raw) as unknown;
    return Array.isArray(arr) ? (arr as string[]) : null;
  } catch {
    return null;
  }
}

const [enabled, setEnabled] = createSignal<string[] | null>(load());

/** 响应式信号：null = 全部可用 */
export function enabledSkillSlugs(): string[] | null {
  return enabled();
}

/** 某 slug 是否已加入可用集（无记录时全部可用） */
export function isSkillEnabled(slug: string): boolean {
  const e = enabled();
  return e === null ? true : e.includes(slug);
}

function persist(next: string[]) {
  try {
    localStorage.setItem(KEY_ENABLED, JSON.stringify(next));
  } catch {
    /* localStorage 不可用时仅会话内生效 */
  }
  setEnabled(next);
}

/** 加入/移除切换（allSlugs 供首次操作实体化「默认全部」） */
export function toggleSkillEnabled(slug: string, allSlugs: string[]) {
  const cur = enabled() ?? allSlugs;
  persist(cur.includes(slug) ? cur.filter((s) => s !== slug) : [...cur, slug]);
}

/** 显式设置加入状态（幂等） */
export function setSkillEnabled(slug: string, on: boolean, allSlugs: string[]) {
  const cur = enabled() ?? allSlugs;
  if (on === cur.includes(slug)) return;
  persist(on ? [...cur, slug] : cur.filter((s) => s !== slug));
}
