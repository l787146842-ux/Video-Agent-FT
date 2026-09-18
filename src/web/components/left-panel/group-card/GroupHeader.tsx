import { createSignal, createEffect, onCleanup, Show, Switch, Match } from 'solid-js';
import { FiImage, FiMusic, FiVideo } from 'solid-icons/fi';
import { studioActions } from '@/stores/studio';
import { normalizeDisplayGroupTitle } from '@/lib/desc-ref-utils';
import type { DraftType } from '@/types';

/**
 * 分组头：图标 + 标题（双击编辑）+ 徽标（双击编辑）+ 序号。
 */
export function GroupHeader(props: {
  type: DraftType;
  groupId: string;
  /** 以下均为 accessor（store 字段可变：改名/换徽标后须响应式刷新） */
  title: () => string;
  durationBadge: () => string;
  index: () => number;
  badge: () => string;
  badgeStyle: () => Record<string, string> | undefined;
  /** flova 对齐批（2026-09-17）：标题旁徽标位（summary 摘要）双击可编辑；
   *  仅 shot 且提供 onSaveSummary 时生效（空值保存=清空摘要，显示回落 duration） */
  summaryEditable?: boolean;
  onSaveSummary?: (val: string) => void;
}) {
  const [editingTitle, setEditingTitle] = createSignal(false);
  const [editingBadge, setEditingBadge] = createSignal(false);
  const [editingSummary, setEditingSummary] = createSignal(false);
  const [titleVal, setTitleVal] = createSignal('');
  const [badgeVal, setBadgeVal] = createSignal('');
  const [summaryVal, setSummaryVal] = createSignal('');

  /** 左上角标题：显示层归一单一事实源 = lib/desc-ref-utils normalizeDisplayGroupTitle
   * （组标题专用：剥容器前缀 + 剥存量镜号/场号 leading 令牌；
   * K7 批收敛，本地副本删除）；数据层标题（如新建组的 `Element_未命名`）
   * 原样存储（台账 #10）。 */
  const displayTitle = () => normalizeDisplayGroupTitle(props.title());

  function saveSummary(val: string) {
    setEditingSummary(false);
    props.onSaveSummary?.(val.trim());
  }

  /** 编辑退出兼容（Q3）：任一编辑态下点击输入框以外的任何地方 → 强制失焦
   *  （部分浏览器点 draggable 区域不会自然移焦，onBlur 不触发导致退不出编辑） */
  createEffect(() => {
    if (!editingTitle() && !editingBadge() && !editingSummary()) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.closest('.sb-title-input, .sb-badge-input, .sb-duration-input')) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && active.matches('.sb-title-input, .sb-badge-input, .sb-duration-input')) {
        active.blur(); // 触发对应 onBlur：保存并退出编辑
      }
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  function saveBadge(val: string) {
    const v = val.trim();
    if (!v || v === props.badge()) { setEditingBadge(false); return; }
    if (props.type === 'shot') {
      // 分镜角标为固定类别名「分镜」，不可编辑（shotType 已摘除，镜头语言唯一载体 = desc）
      setEditingBadge(false);
      return;
    }
    // audio: 时段编辑（keyElement 无角标，不会进入此路径）
    studioActions.renameGroupLocal(props.type, props.groupId, { timeRange: v } as never);
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
      <span class="sb-badge-wrap">
        {/* summary 摘要徽标移至右上角（2026-09-18 批 D：删「分镜」角标、摘要占右上位）；
            仅 shot 有 durationBadge，双击可编辑 */}
        <Show when={props.durationBadge()}>
          <Show when={editingSummary()} fallback={
            <span
              class="sb-duration"
              title={props.summaryEditable ? '双击编辑摘要徽标' : undefined}
              onDblClick={() => {
                if (!props.summaryEditable) return;
                setSummaryVal(props.durationBadge());
                setEditingSummary(true);
              }}
            >
              {props.durationBadge()}
            </span>
          }>
            <input
              class="sb-duration-input"
              value={summaryVal()}
              ref={(el) => requestAnimationFrame(() => { el.focus(); el.select(); })}
              onInput={(e) => setSummaryVal(e.currentTarget.value)}
              onBlur={() => saveSummary(summaryVal())}
              onKeyDown={(e) => { if (e.key === 'Enter') saveSummary(summaryVal()); if (e.key === 'Escape') setEditingSummary(false); }}
            />
          </Show>
        </Show>
        <Show when={props.badge()}>
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
        </Show>
        <span class="sb-index">{props.index()}</span>
      </span>
    </div>
  );
}
