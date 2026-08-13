/* eslint-disable max-lines -- 新增拖拽门控/卡片排序后超行，待后续拆分；新增代码仍受规则约束 */
import { createSignal, createEffect, onCleanup, For, Show, Switch, Match } from 'solid-js';
import { FiImage, FiMusic, FiPlus, FiVideo, FiX } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import { sendUserMessage } from '@/lib/agent-actions';
import { DraftCard } from './DraftCard';
import type {
  AnyGroup, AudioGroup, DraftType, KeyElementGroup, ShotGroup,
} from '@/types';

/**
 * 单个故事板分组卡片
 * 按类型渲染：关键元素（蓝）/ 分镜（紫，含场景引用 chips）/ 音频（绿）
 * 支持分组级拖拽排序（drag 事件由 StoryboardView 协调）。
 */
export function GroupCard(props: {
  group: AnyGroup;
  type: DraftType;
  index: number;
  dragOver: boolean;
  onDragStart: (e: DragEvent) => void;
  onDragOver: (e: DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: DragEvent) => void;
  onDragEnd: () => void;
  /** 右键菜单（向上/向下插入、删除），由 StoryboardView 统一提供 */
  onContextMenu: (e: MouseEvent) => void;
}) {
  /** 每张草稿卡独立的微调输入内容（7777 三轮：组内多卡各自微调互不干扰） */
  const [adjustTexts, setAdjustTexts] = createSignal<Record<string, string>>({});
  /** 当前悬停的草稿卡（微调输入行绑定目标；未悬停时默认第一张） */
  const [hoverDraftId, setHoverDraftId] = createSignal('');
  /** 卡片行悬停态（仅悬停在卡片/输入行上才展开微调行，悬停标题描述不触发） */
  const [cardsHover, setCardsHover] = createSignal(false);
  let adjustBoxRef: HTMLDivElement | undefined;
  const [editingTitle, setEditingTitle] = createSignal(false);
  const [editingDesc, setEditingDesc] = createSignal(false);
  const [editingBadge, setEditingBadge] = createSignal(false);
  const [titleVal, setTitleVal] = createSignal('');
  const [descVal, setDescVal] = createSignal('');
  const [badgeVal, setBadgeVal] = createSignal('');

  /** 编辑退出兼容（Q3）：任一编辑态下点击输入框以外的任何地方 → 强制失焦
   *  （部分浏览器点 draggable 区域不会自然移焦，onBlur 不触发导致退不出编辑） */
  createEffect(() => {
    if (!editingTitle() && !editingDesc() && !editingBadge()) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.closest('.sb-title-input, .sb-desc-input, .sb-badge-input')) return;
      const active = document.activeElement as HTMLElement | null;
      if (active && active.matches('.sb-title-input, .sb-desc-input, .sb-badge-input')) {
        active.blur(); // 触发对应 onBlur：保存并退出编辑
      }
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  /** 分组拖拽门控：仅当按下点在空白区域（非文字/按钮/卡片等）才允许拖动整个分组，
   * 其他区域（尤其文字）保留鼠标选中复制能力 */
  const [dragEnabled, setDragEnabled] = createSignal(false);
  function isBlankDragArea(t: EventTarget | null): boolean {
    const el = t as HTMLElement | null;
    if (!el || typeof el.closest !== 'function') return false;
    // 文字/徽标/按钮/卡片/输入框等交互与内容区域不可拖（用于选中复制与各自交互）
    if (el.closest('input, textarea, button, a, select, video, audio, img, .sb-title, .sb-desc, .sb-badge-wrap, .sb-index, .draft-card-col, .scene-refs, .card-adjust-box')) return false;
    // 已有选中文字时优先复制
    const sel = window.getSelection();
    if (sel && sel.type === 'Range') return false;
    return true;
  }

  // ===== 组内草稿卡片拖拽排序（小标编号随位置重排） =====
  const [dragDraftId, setDragDraftId] = createSignal('');
  const [dragOverDraftId, setDragOverDraftId] = createSignal('');

  function handleDraftDrop(targetDraftId: string) {
    const srcId = dragDraftId();
    if (srcId && srcId !== targetDraftId) {
      studioActions.reorderDraftLocal(props.type, props.group.id, srcId, targetDraftId);
    }
    setDragDraftId('');
    setDragOverDraftId('');
  }

  const meta = () => {
    switch (props.type) {
      case 'keyElement': {
        const g = props.group as KeyElementGroup;
        return {
          badge: g.badgeLabel || '关键元素',
          badgeStyle: undefined as Record<string, string> | undefined,
          desc: g.desc || '',
          addTitle: '手动新建/上传草稿',
          placeholder: '对选中的画面卡片提出修改意见...',
          adjustLabel: '关键元素',
        };
      }
      case 'shot': {
        const g = props.group as ShotGroup;
        return {
          badge: g.shotType || '分镜',
          badgeStyle: {
            background: 'rgba(139, 92, 246, 0.15)',
            color: 'var(--accent-purple)',
          },
          desc: g.roughDesc || '',
          addTitle: '手动生成视频分镜',
          placeholder: '调整此段分镜镜头、运镜或动作描述...',
          adjustLabel: '分镜',
        };
      }
      default: {
        const g = props.group as AudioGroup;
        return {
          badge: g.timeRange || '音频',
          badgeStyle: {
            background: 'rgba(16, 185, 129, 0.15)',
            color: 'var(--accent-emerald)',
          },
          desc: (props.group as AudioGroup).prompt || '',
          addTitle: '上传或写提示词生成音频',
          placeholder: '调整配乐语气、台词或旁白细节...',
          adjustLabel: '音频',
        };
      }
    }
  };

  /** 对指定草稿卡发送微调意见（7777 三轮：定位到卡而非「当前草稿」，
   * 组内多卡时不会改错卡） */
  function sendAdjustFor(draftId: string, code: string) {
    const text = (adjustTexts()[draftId] || '').trim();
    if (!text) return;
    // 用分组标题 + 卡编号，让 Agent 能准确定位
    sendUserMessage(
      `对${meta().adjustLabel}列表${props.index}「${props.group.title}」的第 ${code} 卡提出微调意见：${text}`,
    );
    setAdjustTexts((prev) => ({ ...prev, [draftId]: '' }));
  }

  /** 当前生效的微调目标卡：跟随悬停的卡（悬停切换时输入内容随之切换），
   * 未悬停过默认第一张 */
  const activeDraft = () => {
    const drafts = props.group.drafts || [];
    return drafts.find((d) => d.id === hoverDraftId()) || drafts[0];
  };
  /** 生效卡的小标编号（组号-卡序号，与 Agent 上下文对齐） */
  const activeCode = () => {
    const drafts = props.group.drafts || [];
    const d = activeDraft();
    const idx = d ? drafts.findIndex((x) => x.id === d.id) : -1;
    return idx >= 0 ? `${props.index}-${idx + 1}` : '';
  };

  function saveBadge(val: string) {
    const v = val.trim();
    if (!v || v === meta().badge) { setEditingBadge(false); return; }
    // 根据类型存储到对应字段
    if (props.type === 'keyElement') {
      studioActions.renameGroupLocal(props.type, props.group.id, { badgeLabel: v } as never);
    } else if (props.type === 'shot') {
      studioActions.renameGroupLocal(props.type, props.group.id, { shotType: v } as never);
    } else {
      studioActions.renameGroupLocal(props.type, props.group.id, { timeRange: v } as never);
    }
    setEditingBadge(false);
  }

  const sceneRefs = () =>
    props.type === 'shot' ? (props.group as ShotGroup).sceneRefs || [] : [];

  /** sceneRefs 存储的是关键元素 id（ke-xxx）或标题；展示时解析为元素标题，
   * 解析不到才显示原值（888 反馈：卡片上直接显示 ke-xxx 看不懂） */
  const refLabel = (ref: string) => {
    const el = state.keyElements.find((k) => k.id === ref || k.title === ref);
    return el?.title || String(ref);
  };

  // ===== 场景引用增删（C4）：chips 保留跳转，新增 × 删除与 + 添加 =====
  const [refPickerOpen, setRefPickerOpen] = createSignal(false);

  /** 尚未引用的关键元素标题（添加候选） */
  const availableElements = () => {
    const have = new Set(sceneRefs().map((r) => refLabel(String(r))));
    return state.keyElements
      .map((k) => k.title)
      .filter((t): t is string => !!t && !have.has(t));
  };

  function removeSceneRef(ref: string) {
    studioActions.setSceneRefsLocal(
      props.group.id,
      sceneRefs().filter((r) => String(r) !== ref).map(String),
    );
  }

  function addSceneRef(title: string) {
    studioActions.setSceneRefsLocal(props.group.id, [...sceneRefs().map(String), title]);
    setRefPickerOpen(false);
  }

  /** 点选单外区域关闭添加候选弹层 */
  createEffect(() => {
    if (!refPickerOpen()) return;
    const onDown = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && el.closest('.scene-ref-add-wrap')) return;
      setRefPickerOpen(false);
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  const titleSuffix = () =>
    props.type === 'shot' && (props.group as ShotGroup).duration
      ? ` (${(props.group as ShotGroup).duration})`
      : '';

  return (
    <div
      class={`sb-group ${props.dragOver ? 'border-accent-blue' : ''}`}
      data-group-id={props.group.id}
      draggable={dragEnabled()}
      onMouseDown={(e) => setDragEnabled(isBlankDragArea(e.target))}
      onMouseLeave={() => setCardsHover(false)}
      onContextMenu={(e) => props.onContextMenu(e)}
      onDragStart={(e) => { e.dataTransfer!.setData('text/plain', props.group.id); e.dataTransfer!.effectAllowed = 'move'; props.onDragStart(e); }}
      onDragOver={(e) => props.onDragOver(e)}
      onDragLeave={() => props.onDragLeave()}
      onDrop={(e) => props.onDrop(e)}
      onDragEnd={() => { setDragEnabled(false); props.onDragEnd(); }}
    >
      {/* 分组头：标题 + 徽标编号 */}
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
              onDblClick={() => { setTitleVal(props.group.title); setEditingTitle(true); }}
            >
              {props.group.title}
              {titleSuffix()}
            </span>
          }>
            <input
              class="sb-title-input"
              value={titleVal()}
              ref={(el) => requestAnimationFrame(() => { el.focus(); el.select(); })}
              onInput={(e) => setTitleVal(e.currentTarget.value)}
              onBlur={() => { const v = titleVal().trim() || props.group.title; if (v !== props.group.title) studioActions.renameGroupLocal(props.type, props.group.id, { title: v }); setEditingTitle(false); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { const v = titleVal().trim() || props.group.title; if (v !== props.group.title) studioActions.renameGroupLocal(props.type, props.group.id, { title: v }); setEditingTitle(false); } if (e.key === 'Escape') setEditingTitle(false); }}
            />
          </Show>
        </div>
        <Show when={meta().badge}>
          <span class="sb-badge-wrap">
            <Show when={editingBadge()} fallback={
              <span
                class="sb-badge"
                style={meta().badgeStyle}
                title="双击编辑标签"
                onDblClick={() => { setBadgeVal(meta().badge); setEditingBadge(true); }}
              >
                {meta().badge}
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
            <span class="sb-index">{props.index}</span>
          </span>
        </Show>
      </div>

      {/* 场景引用 chips（仅分镜）：点击跳转；C4 新增 × 删除与 + 添加（为 LLM 写提示词提供依据，
          并决定出图/出视频时自动挂哪些元素概念图） */}
      <Show when={props.type === 'shot'}>
        <div class="scene-refs">
          <Show when={sceneRefs().length > 0}>
            <span class="scene-refs-label">场景:</span>
            <For each={sceneRefs()}>
              {(ref) => (
                <span class="scene-ref-chip scene-ref-editable">
                  <button
                    type="button"
                    class="scene-ref-jump"
                    title="点击跳转到该关键元素"
                    onClick={() => studioActions.jumpToElementByTitle(String(ref))}
                  >
                    {refLabel(String(ref))}
                  </button>
                  <button
                    type="button"
                    class="scene-ref-remove"
                    title="移除场景引用（出视频时不再自动挂该元素概念图）"
                    onClick={() => removeSceneRef(String(ref))}
                  >
                    <FiX size={10} />
                  </button>
                </span>
              )}
            </For>
          </Show>
          <span class="scene-ref-add-wrap">
            <button
              type="button"
              class="scene-ref-chip scene-ref-add"
              title="添加场景引用（本镜头出场的关键元素）"
              onClick={() => setRefPickerOpen((v) => !v)}
            >
              <FiPlus size={10} /> 添加
            </button>
            <Show when={refPickerOpen()}>
              <div class="scene-ref-picker">
                <Show when={availableElements().length} fallback={
                  <div class="scene-ref-picker-empty">没有可添加的关键元素</div>
                }>
                  <For each={availableElements()}>
                    {(t) => (
                      <button type="button" class="scene-ref-picker-item" onClick={() => addSceneRef(t)}>
                        {t}
                      </button>
                    )}
                  </For>
                </Show>
              </div>
            </Show>
          </span>
        </div>
      </Show>

      {/* 描述（双击编辑；编辑框为多行 textarea，高度随内容自适应，
          与展示区同等占位，长文不被截断；失焦/点外部即保存退出） */}
      <Show when={editingDesc()} fallback={
        <p
          class="sb-desc"
          title="双击编辑描述"
          onDblClick={() => { setDescVal(meta().desc); setEditingDesc(true); }}
        >
          {meta().desc || '双击添加描述...'}
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
          onBlur={() => { if (descVal() !== meta().desc) studioActions.renameGroupLocal(props.type, props.group.id, { desc: descVal() }); setEditingDesc(false); }}
          onKeyDown={(e) => {
            // Enter 保存退出，Shift+Enter 换行，Escape 放弃退出
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (descVal() !== meta().desc) studioActions.renameGroupLocal(props.type, props.group.id, { desc: descVal() }); setEditingDesc(false); }
            if (e.key === 'Escape') setEditingDesc(false);
          }}
        />
      </Show>

      {/* 草稿卡片行（小标编号：组号-卡序号，可拖动排序） */}
      <div
        class="draft-cards-row"
        onMouseLeave={(e) => {
          // 移向下方微调输入行时不清除（保持展开），移出卡片区域才收起
          const rt = e.relatedTarget as HTMLElement | null;
          if (rt && adjustBoxRef && adjustBoxRef.contains(rt)) return;
          setCardsHover(false);
        }}
      >
        <button
          type="button"
          class="add-card-btn"
          title={meta().addTitle}
          onClick={() => studioActions.addDraftLocal(props.type, props.group.id)}
        >
          <FiPlus size={15} />
        </button>
        <For each={props.group.drafts || []}>
          {(draft, di) => (
            <div
              class="draft-card-wrap"
              onMouseEnter={() => { setHoverDraftId(draft.id); setCardsHover(true); }}
            >
              <DraftCard
                draft={draft}
                type={props.type}
                groupId={props.group.id}
                cardCode={`${props.index}-${di() + 1}`}
                dragOver={dragOverDraftId() === draft.id}
                onDragStart={() => setDragDraftId(draft.id)}
                onDragOver={(e) => {
                  if (!dragDraftId() || dragDraftId() === draft.id) return;
                  e.preventDefault();
                  e.stopPropagation();
                  setDragOverDraftId(draft.id);
                }}
                onDragLeave={() => {
                  if (dragOverDraftId() === draft.id) setDragOverDraftId('');
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleDraftDrop(draft.id);
                }}
                onDragEnd={() => { setDragDraftId(''); setDragOverDraftId(''); }}
              />
            </div>
          )}
        </For>
      </div>

      {/* 组级微调输入行（7777 四轮）：挂在分组底部占满组宽，不再绑在单张卡下
          擑高卡片行；仅悬停卡片时原位展开（悬停底部占位区不触发，收起态
          pointer-events:none），内容跟随当前悬停的卡（每张卡的
          输入各自保存互不干扰）；聚焦输入期间保持可见 */}
      <Show when={(props.group.drafts || []).length > 0}>
        <div
          ref={adjustBoxRef}
          class={`card-adjust-box ${cardsHover() ? 'open' : ''}`}
          onMouseEnter={() => setCardsHover(true)}
        >
          <input
            type="text"
            class="card-adjust-input"
            placeholder={`对第 ${activeCode()} 卡提出修改意见…`}
            value={adjustTexts()[activeDraft()?.id || ''] || ''}
            onInput={(e) => {
              const id = activeDraft()?.id || '';
              setAdjustTexts((prev) => ({ ...prev, [id]: e.currentTarget.value }));
            }}
            onKeyDown={(e) => {
              const d = activeDraft();
              if (e.key === 'Enter' && d) sendAdjustFor(d.id, activeCode());
            }}
          />
          <button
            type="button"
            class="card-adjust-btn"
            onClick={() => { const d = activeDraft(); if (d) sendAdjustFor(d.id, activeCode()); }}
          >
            微调
          </button>
        </div>
      </Show>
    </div>
  );
}
