/**
 * 生成日志 store — 顶部导航「生成日志」面板数据与开关（照搬画布日志语义）。
 * 图/视频/音频每次生成（无论成败）由后端记录，前端拉取展示。
 */
import { createSignal } from 'solid-js';
import { getGenerationLogs, type GenerationLogEntry } from '@/api/generate';

const [genLogs, setGenLogs] = createSignal<GenerationLogEntry[]>([]);
const [genLogOpen, setGenLogOpen] = createSignal(false);
const [genLogUnread, setGenLogUnread] = createSignal(0);

/** 拉取最新日志（静默失败：后端未就绪不打扰用户） */
export async function refreshGenLogs(): Promise<void> {
  try {
    const data = await getGenerationLogs(100);
    setGenLogs(Array.isArray(data.logs) ? data.logs : []);
  } catch { /* 静默 */ }
}

export function openGenLog(): void {
  setGenLogOpen(true);
  setGenLogUnread(0);
  void refreshGenLogs();
}

export function closeGenLog(): void {
  setGenLogOpen(false);
}

export function toggleGenLog(): void {
  if (genLogOpen()) closeGenLog();
  else openGenLog();
}

/** 新日志到达：面板未打开时累加未读角标 */
export function bumpGenLogUnread(): void {
  if (!genLogOpen()) setGenLogUnread((n) => n + 1);
}

export { genLogs, genLogOpen, genLogUnread };
