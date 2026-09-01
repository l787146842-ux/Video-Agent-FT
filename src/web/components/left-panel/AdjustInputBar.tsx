/**
 * 微调浮窗底部区：参考素材清单 + 附件入口 + 输入行（二期子对话批 3）。
 *
 * 自 AdjustDialog 拆出并经 lazy 惰性装载（浮窗打开才加载，入口体积预算）：
 * 素材摄取库/钩子/图标随本块走，首包不预付。行为契约不变：
 * 素材绑线程（清单 = 已绑 + 待发；移除只删引用不删物理文件）、
 * 上限读 /api/config ← settings.max_attachments、文档类入口即拒。
 */
import { For, Show, type Accessor, type Setter } from 'solid-js';
import { FiSend, FiSquare, FiX, FiPaperclip } from 'solid-icons/fi';
import { adjustScopeActions, type ScopeThread } from '@/stores/adjust-scopes';
import { stopAgentTask } from '@/api/sse';
import { useScopeRefs } from './use-scope-refs';
import { t } from '@/lib/locale';

/** 浮窗底部区。keyed Show 内装载：浮窗关闭即卸载；text 信号由浮窗外层持有（关窗不丢草稿） */
export default function AdjustInputBar(props: {
  scopeKey: () => string; thread: () => ScopeThread | undefined;
  text: Accessor<string>; setText: Setter<string>;
}) {
  const text = props.text;
  const setText = props.setText;
  // 参考素材：摄取/清单/上限/移除拆在 use-scope-refs 钩子
  const scopeRefsHook = useScopeRefs(props.scopeKey, props.thread);
  /** 续聊提交（走 sendAdjust：拒重复守卫/用户气泡落线程/定向线程任务） */
  function doSend() {
    const th = props.thread();
    const v = text().trim();
    if (!th || !v) return;
    if (adjustScopeActions.sendAdjust(th.scope, v)) setText('');
  }
  /** 停止：复用既有 task 停止通道（按 taskId）；终态事件经 scope fx 落线程 */
  function doStop() {
    const tid = props.thread()?.taskId || '';
    if (tid) void stopAgentTask(tid);
  }

  return (
    <>
      <Show when={scopeRefsHook.refs().length > 0}>
        <div class="adjust-refs">
          <span class="adjust-refs-count">
            {t('rp.adjust.refsTitle')}：{scopeRefsHook.refs().length} / {scopeRefsHook.maxAtt()}
          </span>
          <For each={scopeRefsHook.refs()}>{(r) => (
            <span class="adjust-ref-chip" title={r.name}>
              <Show when={r.kind === 'image'} fallback={<span class="adjust-ref-name">{r.name}</span>}>
                <img class="adjust-ref-thumb" src={r.url} alt={r.name} />
              </Show>
              <button type="button" class="adjust-ref-x" title={t('rp.adjust.refRemove')} onClick={() => scopeRefsHook.removeRef(r)}>
                <FiX size={11} />
              </button>
            </span>
          )}</For>
        </div>
      </Show>
      <div class="adjust-input-row">
        <input
          type="file" ref={scopeRefsHook.setFileEl} accept="image/*,video/*,audio/*" multiple style="display:none"
          onChange={(e) => { void scopeRefsHook.onPick(e.currentTarget.files); e.currentTarget.value = ''; }}
        />
        <button type="button" class="adjust-dialog-attach" title={t('rp.adjust.attach')} onClick={scopeRefsHook.openPicker}>
          <FiPaperclip size={13} />
        </button>
        <input
          type="text"
          class="adjust-dialog-input"
          placeholder={t('rp.adjust.inputPlaceholder')}
          value={text()}
          onInput={(e) => setText(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') doSend(); }}
          onPaste={scopeRefsHook.onPaste}
        />
        <Show
          when={!!props.thread()?.taskId}
          fallback={
            <button type="button" class="adjust-dialog-send" title={t('rp.adjust.send')} onClick={doSend}>
              <FiSend size={13} />
            </button>
          }
        >
          <button type="button" class="adjust-dialog-stop" title={t('rp.adjust.stop')} onClick={doStop}>
            <FiSquare size={13} />
          </button>
        </Show>
      </div>
    </>
  );
}
