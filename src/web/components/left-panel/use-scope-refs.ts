/**
 * 微调浮窗参考素材钩子（二期子对话批 3，自 AdjustDialog 拆出，行数红线 250）。
 *
 * 素材绑子对话线程（用户裁决）：上传/粘贴经 uploadScopeRefs 摄取（文档类入口
 * 即拒），入线程 pendingRefs 暂存；发送随消息携带，后端绑线程 scopeRefs（不进
 * 全局 assets，主对话零污染）。清单 = 已绑 + 待发合并；移除只删引用不删物理
 * 文件。数量上限唯一事实源 /api/config ← settings.max_attachments（只拉一次）。
 */
import { createSignal, createEffect } from 'solid-js';
import { adjustScopeActions } from '@/stores/adjust-scopes';
import { getAppConfig } from '@/api/providers';
import { uploadScopeRefs, pasteScopeRefs } from '@/lib/chat/adjust-scope-media';
import type { ScopeRef, ScopeThread } from '@/stores/adjust-scopes';

/** 附件数量上限只拉一次（浮窗生命周期内不变；失败下次打开重试） */
let limitLoaded = false;

export function useScopeRefs(scopeKey: () => string, thread: () => ScopeThread | undefined) {
  const [maxAtt, setMaxAtt] = createSignal(5);
  createEffect(() => {
    if (!scopeKey() || limitLoaded) return;
    limitLoaded = true;
    void getAppConfig().then((c) => { if (c?.max_attachments) setMaxAtt(c.max_attachments); })
      .catch(() => { limitLoaded = false; });
  });

  let fileEl: HTMLInputElement | undefined;
  /** 已绑 + 待发合并清单（已绑在前；移除分流见 removeRef） */
  const refs = () => [...(thread()?.scopeRefs || []), ...(thread()?.pendingRefs || [])];

  const tryAdd = (r: ScopeRef) => {
    const k = scopeKey();
    if (k) adjustScopeActions.addPendingRef(k, r, maxAtt());
  };
  /** 选择文件上传入暂存（仅图片/视频/音频；上限与类型拒收提示在摄取/入队层） */
  async function onPick(list: FileList | null) {
    if (!list?.length) return;
    (await uploadScopeRefs(Array.from(list))).forEach(tryAdd);
  }
  /** 粘贴图片上传入暂存（输入框 onPaste 直挂） */
  function onPaste(e: ClipboardEvent) {
    void pasteScopeRefs(e).then((rs) => rs.forEach(tryAdd));
  }
  /** 移除：待发仅删暂存；已绑调后端解绑（只删引用，物理文件不清） */
  function removeRef(r: ScopeRef) {
    const k = scopeKey();
    if (!k) return;
    if ((thread()?.pendingRefs || []).some((p) => p.id === r.id)) adjustScopeActions.removePendingRef(k, r.id);
    else adjustScopeActions.removeScopeRef(k, r.id);
  }

  return { maxAtt, refs, fileEl, setFileEl: (el: HTMLInputElement) => { fileEl = el; },
    openPicker: () => fileEl?.click(), onPick, onPaste, removeRef };
}
