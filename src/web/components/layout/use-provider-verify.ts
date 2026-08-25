/**
 * 验证地址/验证协议域状态与动作 hook—— 自 SettingsView 切出。
 * 承载 verifyResult 内联结果与 test-connection/probe-async 动作
 * （画布同款：点击验证后直接在卡片底部展示，不用 toast）。
 */
import { createSignal } from 'solid-js';
import { apiPost } from '@/api/client';
import type { ProviderProbeRequest } from '@/types/api.generated';
import { imageModeLabel, type EditableProvider } from './settings-meta';

export function useProviderVerify(
  current: () => EditableProvider | undefined,
  keyInput: () => string,
  imageMode: () => string,
  patch: (field: string, value: unknown) => void,
) {
  // 验证结果内联显示（画布同款：点击验证后直接在卡片底部展示，不用 toast）
  const [verifyResult, setVerifyResult] = createSignal<{ ok: boolean; text: string } | null>(null);

  /** test-connection / probe-async / fetch-models 三端点同构请求体（生成物唯一来源） */
  function probeBody(): ProviderProbeRequest {
    const p = current();
    return {
      base_url: p?.base_url, api_key: keyInput() || '', provider_id: p?.id,
      protocol: p?.protocol, image_request_mode: imageMode(),
    };
  }

  async function verifyAddress() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean; status: number; message: string; model_count: number; image_request_mode?: string }>(
        '/api/providers/test-connection',
        probeBody(),
      );
      if (r.ok) {
        setVerifyResult({
          ok: true,
          text: `地址验证通过 - 找到 ${r.model_count} 个模型 - 图片接口: ${imageModeLabel(r.image_request_mode || imageMode())}`,
        });
      } else {
        setVerifyResult({ ok: false, text: `地址验证失败: ${r.message}` });
      }
    } catch (e) {
      setVerifyResult({ ok: false, text: `地址验证失败: ${(e as Error).message}` });
    }
  }

  async function verifyProtocol() {
    const p = current();
    if (!p) return;
    try {
      const r = await apiPost<{ ok: boolean | null; protocol: string; message: string }>(
        '/api/providers/probe-async',
        probeBody(),
      );
      setVerifyResult({ ok: r.ok !== false, text: r.message || `协议识别：${r.protocol}` });
      if (r.ok && r.protocol && r.protocol !== p.protocol) patch('protocol', r.protocol);
    } catch (e) {
      setVerifyResult({ ok: false, text: `协议验证失败: ${(e as Error).message}` });
    }
  }

  return { verifyResult, resetVerify: () => setVerifyResult(null), verifyAddress, verifyProtocol };
}
