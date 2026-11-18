import { createEffect, createSignal, onCleanup, Show } from 'solid-js';
import { FiChevronDown } from 'solid-icons/fi';
import { studioActions } from '@/stores/studio';
import type { DraftType } from '@/types';

/**
 * 分组描述编辑器。
 * 双击编辑；编辑框为多行 textarea，高度随内容自适应，与展示区同等占位，
 * 长文不被截断；失焦/点外部即保存退出。
 * 2026-10-26（用户裁决）：关键元素/音频 desc 与分镜同口径——默认折叠两行，
 * 点正文或「展开」看全文；拖选文字时不触发展开（保留可复制）。
 */
export function GroupDescEditor(props: {
  type: DraftType;
  groupId: string;
  /** accessor（描述保存后须响应式刷新） */
  desc: () => string;
}) {
  const [editingDesc, setEditingDesc] = createSignal(false);
  const [descVal, setDescVal] = createSignal('');
  const [expanded, setExpanded] = createSignal(false);
  /** 单击展开/收起的延迟计时器：给双击进编辑留配对窗口（同 ShotDescEditor 口径） */
  let clickTimer: ReturnType<typeof setTimeout> | undefined;
  onCleanup(() => clearTimeout(clickTimer));

  function enterEdit() {
    clearTimeout(clickTimer);
    setDescVal(props.desc());
    setEditingDesc(true);
  }

  /** 编辑退出兼容（Q3）：编辑态下点击输入框以外的任何地方 → 强制失焦
   *  （部分浏览器点 draggable 区域不会自然移焦，onBlur 不触发导致退不出编辑） */
  createEffect(() => {
    if (!editingDesc()) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.closest('.sb-desc-input')) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && active.matches('.sb-desc-input')) {
        active.blur(); // 触发 onBlur：保存并退出编辑
      }
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });


  return (
    <Show when={editingDesc()} fallback={
      <Show when={props.desc()} fallback={
        <p
          class="sb-desc"
          title="双击编辑描述"
          onDblClick={enterEdit}
        >
          双击添加描述...
        </p>
      }>
        <div class="sb-desc-wrap">
          <p
            class={`sb-desc${expanded() ? '' : ' sb-desc--collapsed'}`}
            title={expanded() ? '点击收起；双击编辑' : '点击展开；双击编辑'}
            onClick={() => {
              // 拖选文字优先复制：已有选区时不触发展开切换
              const sel = window.getSelection();
              if (sel && sel.type === 'Range') return;
              clearTimeout(clickTimer);
              clickTimer = setTimeout(() => setExpanded((v) => !v), 250);
            }}
            onDblClick={(e) => {
              e.preventDefault();
              enterEdit();
            }}
          >
            {props.desc()}
          </p>
          <button type="button" class="sb-design-toggle" onClick={() => setExpanded((v) => !v)}>
            {expanded() ? '收起' : '展开'}
            <FiChevronDown size={11} class={`sb-design-arrow${expanded() ? ' expanded' : ''}`} />
          </button>
        </div>
      </Show>
    }>
      <textarea
        ref={(el) => {
          // 挂载后按内容撑高（与展示文本同等占位）并聚焦
          requestAnimationFrame(() => {
            el.style.height = 'auto';
            el.style.height = `${Math.max(el.scrollHeight, 28)}px`;
            el.focus();
          });
        }}
        class="sb-desc-input"
        value={descVal()}
        rows={2}
        placeholder="输入描述..."
        onInput={(e) => {
          setDescVal(e.currentTarget.value);
          const el = e.currentTarget;
          el.style.height = 'auto';
          el.style.height = `${el.scrollHeight}px`;
        }}
        onBlur={() => { if (descVal() !== props.desc()) studioActions.renameGroupLocal(props.type, props.groupId, { desc: descVal() }); setEditingDesc(false); }}
        onKeyDown={(e) => {
          // Enter 保存退出，Shift+Enter 换行，Escape 放弃退出
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (descVal() !== props.desc()) studioActions.renameGroupLocal(props.type, props.groupId, { desc: descVal() }); setEditingDesc(false); }
          if (e.key === 'Escape') setEditingDesc(false);
        }}
      />
    </Show>
  );
}
