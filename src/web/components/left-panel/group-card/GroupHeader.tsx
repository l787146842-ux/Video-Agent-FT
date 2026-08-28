import { createSignal, createEffect, onCleanup, Show, Switch, Match } from 'solid-js';
import { FiImage, FiMusic, FiVideo } from 'solid-icons/fi';
import { studioActions } from '@/stores/studio';
import type { DraftType } from '@/types';

/**
 * 分组头：图标 + 标题（双击编辑）+ 徽标（双击编辑）+ 序号。
 */
export function GroupHeader(props: {
  type: DraftType;
  groupId: string;
  /** 以下均为 accessor（store 字段可变：改名/换徽标后须响应式刷新） */
  title: () => string;
  titleSuffix: () => string;
  index: () => number;
  badge: () => string;
  badgeStyle: () => Record<string, string> | undefined;
}) {
  const [editingTitle, setEditingTitle] = createSignal(false);
  const [editingBadge, setEditingBadge] = createSignal(false);
  const [titleVal, setTitleVal] = createSignal('');
  const [badgeVal, setBadgeVal] = createSignal('');

  /** 左上角标题：剥离 Element_/Shot_ 等英文前缀与非中文字符，纯中文展示（无中文时回退原文）；
   * 仅显示层剥离，数据层标题（如新建组的 `Element_未命名`）原样存储（台账 #10，口径同 b6011a5） */
  const displayTitle = () => {
    const raw = props.title() || '';
    const stripped = raw.replace(/^[A-Za-z]+[_\-\s]?/, '').trim();
    const chineseOnly = stripped.replace(/[A-Za-z0-9_\-.\s]+/g, '').trim();
    return chineseOnly || stripped || raw;
  };

  /** 编辑退出兼容（Q3）：任一编辑态下点击输入框以外的任何地方 → 强制失焦
   *  （部分浏览器点 draggable 区域不会自然移焦，onBlur 不触发导致退不出编辑） */
  createEffect(() => {
    if (!editingTitle() && !editingBadge()) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.closest('.sb-title-input, .sb-badge-input')) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && active.matches('.sb-title-input, .sb-badge-input')) {
        active.blur(); // 触发对应 onBlur：保存并退出编辑
      }
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  function saveBadge(val: string) {
    const v = val.trim();
    if (!v || v === props.badge()) { setEditingBadge(false); return; }
    // 根据类型存储到对应字段
    if (props.type === 'keyElement') {
      studioActions.renameGroupLocal(props.type, props.groupId, { badgeLabel: v } as never);
    } else if (props.type === 'shot') {
      studioActions.renameGroupLocal(props.type, props.groupId, { shotType: v } as never);
    } else {
      studioActions.renameGroupLocal(props.type, props.groupId, { timeRange: v } as never);
    }
    setEditingBadge(false);
  }

  return (
    <div class="sb-group-header">
      <div class="sb-title">
        <Switch>
          <Match when={props.type === 'keyElement'}>
            <FiImage size={15} class="icon-accent-blue" />
          </Match>
          <Match when={props.type === 'shot'}>
            <FiVideo size={15} class="icon-accent-purple" />
          </Match>
          <Match when={props.type === 'audio'}>
            <FiMusic size={15} class="icon-accent-emerald" />
          </Match>
        </Switch>
        <Show when={editingTitle()} fallback={
          <span
            title="双击编辑标题"
            onDblClick={() => { setTitleVal(props.title()); setEditingTitle(true); }}
          >
            {displayTitle()}
            {props.titleSuffix()}
          </span>
        }>
          <input
            class="sb-title-input"
            value={titleVal()}
            ref={(el) => requestAnimationFrame(() => { el.focus(); el.select(); })}
            onInput={(e) => setTitleVal(e.currentTarget.value)}
            onBlur={() => { const v = titleVal().trim() || props.title(); if (v !== props.title()) studioActions.renameGroupLocal(props.type, props.groupId, { title: v }); setEditingTitle(false); }}
            onKeyDown={(e) => { if (e.key === 'Enter') { const v = titleVal().trim() || props.title(); if (v !== props.title()) studioActions.renameGroupLocal(props.type, props.groupId, { title: v }); setEditingTitle(false); } if (e.key === 'Escape') setEditingTitle(false); }}
          />
        </Show>
      </div>
      <Show when={props.badge()}>
        <span class="sb-badge-wrap">
          <Show when={editingBadge()} fallback={
            <span
              class="sb-badge"
              style={props.badgeStyle()}
              title="双击编辑标签"
              onDblClick={() => { setBadgeVal(props.badge()); setEditingBadge(true); }}
            >
              {props.badge()}
            </span>
          }>
            <input
              class="sb-badge-input"
              value={badgeVal()}
              ref={(el) => requestAnimationFrame(() => { el.focus(); el.select(); })}
              onInput={(e) => setBadgeVal(e.currentTarget.value)}
              onBlur={() => saveBadge(badgeVal())}
              onKeyDown={(e) => { if (e.key === 'Enter') saveBadge(badgeVal()); if (e.key === 'Escape') setEditingBadge(false); }}
            />
          </Show>
          <span class="sb-index">{props.index()}</span>
        </span>
      </Show>
    </div>
  );
}
