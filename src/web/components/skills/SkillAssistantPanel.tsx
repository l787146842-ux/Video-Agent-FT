import { createEffect, createSignal, For, Show } from 'solid-js';
import {
  FiArrowUp, FiCpu, FiGlobe, FiMessageSquare, FiPaperclip,
} from 'solid-icons/fi';
import {
  assistantMessages, assistantBusy, sendAssistant,
} from '@/stores/skill-studio';
import { renderMarkdown } from '@/lib/markdown';
import { useSplitter } from '@/hooks/use-splitter';
import { PillDropdown } from '@/components/right-panel/PillDropdown';
import {
  agentProvider, setAgentProvider, agentModel, setAgentModel,
} from '@/stores/agent-prefs';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { getContextUsage, type ContextUsage } from '@/api/agent';

/**
 * Skill 工作台右栏：优化助手对话（会话级，不持久化）。
 * 输入区对齐影视工作台聊天输入：上传 / 厂商-模型级联 / 发送 / 上下文用量；
 * 消息区与输入区分界线可上下拖拽调输入区高度（100-400px，持久化）。
 */
export function SkillAssistantPanel() {
  const [input, setInput] = createSignal('');
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  let scrollEl: HTMLDivElement | undefined;
  let fileRef: HTMLInputElement | undefined;

  const inputSplit = useSplitter(150, {
    axis: 'y', min: 100, max: 400, invert: true, storageKey: 'splitSkillAssistantInput',
  });

  // 新消息/思考态自动滚底
  createEffect(() => {
    void assistantMessages().length;
    void assistantBusy();
    scrollEl?.scrollTo({ top: scrollEl.scrollHeight });
  });

  // 上下文用量：首轮 + 每轮回复后 + 切模型后刷新
  function refreshUsage() {
    void getContextUsage(agentModel(), agentProvider()).then(setUsage).catch(() => { /* 后端未就绪静默 */ });
  }
  createEffect(() => { void assistantMessages().length; refreshUsage(); });
  createEffect(() => { void agentModel(); refreshUsage(); });

  const providerOptions = () => apiProvidersFor('chat').map((p) => ({
    value: p.id, label: p.name || p.id, hint: p.protocol,
  }));
  const modelOptions = () => providerModels(agentProvider(), 'chat').map((m) => ({
    value: m, label: m,
  }));

  const usageLabel = () => {
    const u = usage();
    if (!u) return '…';
    return `${(u.est_tokens / 1024).toFixed(1)}K`;
  };
  const ringClass = () => {
    const u = usage();
    if (!u || !u.window_tokens) return '';
    const r = Math.min(1, u.est_tokens / u.window_tokens);
    return r >= 0.85 ? 'hot' : r >= 0.6 ? 'warn' : 'ok';
  };

  function send() {
    const text = input();
    if (!text.trim() || assistantBusy()) return;
    setInput('');
    void sendAssistant(text);
  }

  /** 上传 .md/.txt：文件正文追加进输入框作为助手上下文 */
  function onFileSelect(e: Event) {
    const el = e.currentTarget as HTMLInputElement;
    const file = el.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      setInput((v) => (v.trim() ? `${v}\n\n${text}` : text));
    };
    reader.readAsText(file);
    el.value = '';
  }

  return (
    <>
      <div class="skst-assistant-header">
        <FiMessageSquare size={13} /> Skill优化助手
      </div>
      <div class="skst-assistant-body" ref={scrollEl}>
        <Show when={!assistantMessages().length}>
          <div class="skst-assistant-empty">
            说出你的想法，我帮你定制/优化左侧的 Skill 文档；
            改动会实时覆盖到预览（未保存），是否落盘由你决定。
          </div>
        </Show>
        <For each={assistantMessages()}>
          {(m) => (
            <div class={`skst-msg ${m.role}`}>
              <Show
                when={m.role === 'assistant'}
                fallback={<div class="skst-msg-text">{m.text}</div>}
              >
                <div class="chat-markdown" innerHTML={renderMarkdown(m.text)} />
              </Show>
            </div>
          )}
        </For>
        <Show when={assistantBusy()}>
          <div class="skst-msg assistant">
            <div class="skst-msg-text dim">思考中…</div>
          </div>
        </Show>
      </div>

      {/* 消息区与输入区拖拽分界（同影视工作台把手） */}
      <div
        class={`chat-resize-handle ${inputSplit.dragging() ? 'dragging' : ''}`}
        title="拖拽调整输入区高度"
        onMouseDown={(e) => inputSplit.onMouseDown(e)}
      />
      <div class="chat-input-shell" style={{ height: `${inputSplit.size()}px` }}>
        <div class="chat-input-area">
          <div class="chat-input-box">
            <textarea
              value={input()}
              placeholder="请输入你想创建的Skill想法…"
              onInput={(e) => setInput(e.currentTarget.value)}
              onKeyDown={(e) => {
                // 中文输入法选词期间的 Enter 不触发发送
                if (e.isComposing || e.keyCode === 229) return;
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt,.markdown"
              class="hidden"
              onChange={onFileSelect}
            />
            <div class="chat-input-toolbar">
              <div class="toolbar-left">
                <button
                  type="button"
                  class="toolbar-pill-btn"
                  title="上传文档（.md/.txt，正文追加为上下文）"
                  onClick={() => fileRef?.click()}
                >
                  <FiPaperclip size={13} />
                </button>
                {/* 厂商-模型级联：模型选项随厂商联动 */}
                <PillDropdown
                  icon={FiGlobe}
                  value={agentProvider()}
                  options={providerOptions()}
                  title="API 厂商"
                  onSelect={setAgentProvider}
                />
                <PillDropdown
                  icon={FiCpu}
                  value={agentModel()}
                  options={modelOptions()}
                  title="模型"
                  onSelect={setAgentModel}
                />
              </div>
              <div class="toolbar-right">
                <div class="context-usage-wrap">
                  <button
                    type="button"
                    class="context-usage-btn"
                    aria-label="上下文用量"
                    onClick={refreshUsage}
                  >
                    <svg class={`ctx-ring ${ringClass()}`} width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                      <circle class="ctx-ring-bg" cx="7" cy="7" r="5.5" />
                      <circle class="ctx-ring-fg" cx="7" cy="7" r="5.5" />
                    </svg>
                    <span class="context-usage-value">{usageLabel()}</span>
                  </button>
                  <div class="context-usage-tip" role="tooltip">
                    {usage()
                      ? `上下文已用 ${(usage()!.est_tokens / 1024).toFixed(1)}K`
                      : '加载中…'}
                  </div>
                </div>
                <button
                  type="button"
                  class="send-btn"
                  title="发送"
                  disabled={assistantBusy() || !input().trim()}
                  onClick={send}
                >
                  <FiArrowUp size={15} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
