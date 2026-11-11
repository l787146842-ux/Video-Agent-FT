import { createEffect, createSignal, For, Show } from 'solid-js';
import {
  FiArrowUp, FiGlobe, FiMessageSquare, FiPaperclip,
} from 'solid-icons/fi';
import {
  assistantMessages, assistantBusy, assistantStream, sendAssistant, selectedSlug,
} from '@/stores/skill-studio';
import { renderMarkdown } from '@/lib/markdown';
import { useSplitter } from '@/hooks/use-splitter';
import { PillDropdown } from '@/components/right-panel/PillDropdown';
import { ModelThinkingPill } from '@/components/right-panel/ModelThinkingPill';
import {
  agentProvider, setAgentProvider, agentModel,
} from '@/stores/agent-prefs';
import { apiProvidersFor } from '@/lib/providers';
import { getContextUsage, type ContextUsage } from '@/api/agent';
import { SkillReasoningDone, SkillReasoningLive } from './SkillReasoning';

/**
 * Skill 工作台右栏：优化助手对话（会话级，不持久化）。
 * 新建草稿 = 创作模式（后端按通用契约生成标题式草稿并自检）；
 * 编辑既有 Skill = 优化模式。输入区对齐影视工作台聊天输入：
 * 上传 / 厂商-模型级联 / 发送 / 上下文用量；
 * 消息区与输入区分界线可上下拖拽调输入区高度（100-400px，持久化）。
 */
export function SkillAssistantPanel() {
  const [input, setInput] = createSignal('');
  const [usage, setUsage] = createSignal<ContextUsage | null>(null);
  let scrollEl: HTMLDivElement | undefined;
  let fileRef: HTMLInputElement | undefined;
  // 未落盘草稿 = 新建态 = 创作模式（后端通用标题式契约 + 自检/自修复）
  const createMode = () => !selectedSlug();

  const inputSplit = useSplitter(150, {
    axis: 'y', min: 100, max: 400, invert: true, storageKey: 'splitSkillAssistantInput',
  });

  // 新消息/思考态/流式增量自动滚底
  createEffect(() => {
    void assistantMessages().length;
    void assistantBusy();
    void assistantStream()?.reasoning;
    void assistantStream()?.text;
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
        <Show when={createMode()}>
          <span class="skst-mode-tag">创作模式</span>
        </Show>
      </div>
      <div class="skst-assistant-body" ref={scrollEl}>
        <Show when={!assistantMessages().length}>
          <Show
            when={createMode()}
            fallback={(
              <div class="skst-assistant-empty">
                说出你的想法，我帮你定制/优化左侧的 Skill 文档；
                改动会实时覆盖到预览（未保存），是否落盘由你决定。
              </div>
            )}
          >
            <div class="skst-assistant-empty">
              描述你想做的片子或制作流程，我按通用规范生成一版标题式草稿
              （目标 / 开工前确认 / 制作流程 / 结构与素材 / 专业方法 / 参考资料）。
              生成后左侧预览自动更新，确认无误再点「保存」落盘。
            </div>
          </Show>
        </Show>
        <For each={assistantMessages()}>
          {(m) => (
            <div class={`skst-msg ${m.role}`}>
              <Show
                when={m.role === 'assistant'}
                fallback={<div class="skst-msg-text">{m.text}</div>}
              >
                <Show when={m.reasoning}>
                  {(r) => <SkillReasoningDone reasoning={r()} />}
                </Show>
                <div class="chat-markdown" innerHTML={renderMarkdown(m.text)} />
                <Show when={m.checks}>
                  <div class={`skst-checks ${m.checks!.passed ? 'ok' : 'warn'}`}>
                    <Show
                      when={m.checks!.passed}
                      fallback={(
                        <>
                          <div class="skst-checks-title">
                            ⚠ 自检未通过（{m.checks!.issues.length} 项）
                          </div>
                          <For each={m.checks!.issues.slice(0, 4)}>
                            {(issue) => <div class="skst-checks-item">· {issue}</div>}
                          </For>
                          <Show when={m.checks!.issues.length > 4}>
                            <div class="skst-checks-item">
                              …还有 {m.checks!.issues.length - 4} 项，保存时会再提示
                            </div>
                          </Show>
                        </>
                      )}
                    >
                      <div class="skst-checks-title">
                        ✓ 已通过项目规范自检
                        {m.mode === 'create' ? '（通用骨架 / 工具名 / 参数纪律）' : '（工具名 / 参数纪律）'}
                      </div>
                    </Show>
                  </div>
                </Show>
              </Show>
            </div>
          )}
        </For>
        <Show when={assistantStream()}>
          {(st) => (
            <div class="skst-msg assistant">
              {/* 思考流：标题行兼作阶段状态（思考中 / 自检修复中） */}
              <SkillReasoningLive reasoning={st().reasoning} status={st().status} />
              <Show when={st().text}>
                <pre class="skst-stream-text">{st().text}</pre>
              </Show>
              {/* 文档正文不进聊天：只报进度，正文实时进中间预览 */}
              <Show when={st().doc}>
                <div class="skst-stream-progress">
                  正在生成 Skill 文档… 已 {st().doc.length.toLocaleString()} 字（见中间预览）
                </div>
              </Show>
            </div>
          )}
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
              placeholder={createMode()
                ? '描述你想做的片子/流程，我生成一版标题式草稿…'
                : '请输入你想创建的Skill想法…'}
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
                {/* 模型 + 思考开关/推理档位：与主对话同一胶囊（chat_models_meta 一处管） */}
                <ModelThinkingPill />
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
