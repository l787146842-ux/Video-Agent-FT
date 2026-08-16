/**
 * CLI 域状态与动作 hook——七轮 S1/T23 自 SettingsView 切出。
 * 承载 CLI 安装状态检测、帮助/积分弹窗、即梦扫码登录轮询；
 * 对外只暴露 SettingsApi 所需片段，行为与切出前逐字一致。
 */
import { createSignal, onCleanup } from 'solid-js';
import { apiFetch, apiPost } from '@/api/client';
import { showToast } from '@/stores/toast';
import { CLI_ENTRIES, type CliStatusMap } from './settings-meta';
import type { CliModalData } from './settings/CliModal';

export function useCliOps() {
  const [cliStatus, setCliStatus] = createSignal<CliStatusMap>({});
  // CLI 弹窗（帮助/积分/登录输出）
  const [cliModal, setCliModal] = createSignal<CliModalData | null>(null);
  let loginTimer: ReturnType<typeof setInterval> | undefined;

  /** 页面加载时并发探测各 CLI 安装状态 */
  async function loadCliStatuses() {
    const statuses: CliStatusMap = {};
    await Promise.all(CLI_ENTRIES.map(async (c) => {
      try {
        const s = await apiFetch<{ installed?: boolean; message?: string }>(c.statusPath);
        statuses[c.key] = { installed: !!s.installed, message: s.message || '' };
      } catch {
        statuses[c.key] = { installed: false, message: '检测失败' };
      }
    }));
    setCliStatus(statuses);
  }

  async function refreshCliStatus(key: string, statusPath: string): Promise<boolean> {
    try {
      const s = await apiFetch<{ installed?: boolean; message?: string }>(statusPath);
      setCliStatus((prev) => ({ ...prev, [key]: { installed: !!s.installed, message: s.message || '' } }));
      return !!s.installed;
    } catch {
      return false;
    }
  }

  async function cliHelp(title: string, helpPath: string) {
    try {
      const r = await apiPost<{ ok?: boolean; output?: string }>(helpPath, { command: '' });
      setCliModal({ title: `${title} · 帮助`, text: r.output || '(无输出)' });
    } catch (e) {
      showToast(`帮助获取失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengCredit() {
    try {
      const r = await apiFetch<{ ok: boolean; text?: string; message?: string }>('/api/jimeng/credit');
      if (r.ok) setCliModal({ title: '即梦账户积分', text: r.text || '(无输出)' });
      else showToast(r.message || '查询失败', 'error');
    } catch (e) {
      showToast(`查询积分失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengLogout() {
    try {
      const r = await apiPost<{ ok: boolean; message: string }>('/api/jimeng/logout', {});
      showToast(r.message, r.ok ? 'success' : 'error');
      await refreshCliStatus('jimeng', '/api/jimeng/status');
    } catch (e) {
      showToast(`登出失败：${(e as Error).message}`, 'error');
    }
  }

  async function jimengLogin() {
    try {
      const r = await apiPost<{ ok: boolean; message: string }>('/api/jimeng/login/start', {});
      if (!r.ok) {
        showToast(r.message, 'error');
        return;
      }
      setCliModal({ title: '即梦扫码登录', text: '正在启动 dreamina login…' });
      if (loginTimer) clearInterval(loginTimer);
      loginTimer = setInterval(async () => {
        try {
          const s = await apiFetch<{ running: boolean; text: string; qr_url?: string }>('/api/jimeng/login/status');
          setCliModal({
            title: '即梦扫码登录',
            text: s.text || '等待输出…（按终端提示扫码）',
            qr_url: s.qr_url,
          });
          if (!s.running) {
            clearInterval(loginTimer);
            loginTimer = undefined;
            await refreshCliStatus('jimeng', '/api/jimeng/status');
          }
        } catch { /* 轮询静默 */ }
      }, 1500);
    } catch (e) {
      showToast(`启动登录失败：${(e as Error).message}`, 'error');
    }
  }

  onCleanup(() => { if (loginTimer) clearInterval(loginTimer); });

  return {
    cliStatus, cliModal, setCliModal,
    loadCliStatuses, refreshCliStatus, cliHelp,
    jimengCredit, jimengLogout, jimengLogin,
  };
}
