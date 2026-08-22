import { createEffect, createSignal, onCleanup, Show } from 'solid-js';
import { studioActions } from '@/stores/studio';
import type { DraftType } from '@/types';

/**
 * 分组描述编辑器。
 * 双击编辑；编辑框为多行 textarea，高度随内容自适应，与展示区同等占位，
 * 长文不被截断；失焦/点外部即保存退出。
 */
export function GroupDescEditor(props: {
  type: DraftType;
  groupId: string;
  /** accessor（描述保存后须响应式刷新） */
  desc: () => string;
}) {
  const [editingDesc, setEditingDesc] = createSignal(false);
  const [descVal, setDescVal] = createSignal('');

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
      <p
        class="sb-desc"
        title="双击编辑描述"
        onDblClick={() => { setDescVal(props.desc()); setEditingDesc(true); }}
      >
        {props.desc() || '双击添加描述...'}
      </p>
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
