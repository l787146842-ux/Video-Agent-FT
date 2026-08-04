/* eslint-disable max-lines -- 新增拖拽门控/卡片排序后超行，待后续拆分；新增代码仍受规则约束 */
import { createSignal, For, Show, Switch, Match } from 'solid-js';
import { FiImage, FiMusic, FiPlus, FiVideo } from 'solid-icons/fi';
import { studioActions } from '@/stores/studio';
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
  const [adjustText, setAdjustText] = createSignal('');
  const [editingTitle, setEditingTitle] = createSignal(false);
  const [editingDesc, setEditingDesc] = createSignal(false);
  const [editingBadge, setEditingBadge] = createSignal(false);
  const [titleVal, setTitleVal] = createSignal('');
  const [descVal, setDescVal] = createSignal('');
  const [badgeVal, setBadgeVal] = createSignal('');

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

  function sendAdjust() {
    const text = adjustText().trim();
    if (!text) return;
    // 用分组标题 + 编号，让 Agent 能准确定位
    sendUserMessage(
      `对${meta().adjustLabel}列表${props.index}「${props.group.title}」的当前草稿提出微调意见：${text}`,
    );
    setAdjustText('');
  }

  function saveBadge(val: string) {
    const v = val.trim();
    if (!v) { setEditingBadge(false); return; }
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

  const titleSuffix = () =>
    props.type === 'shot' && (props.group as ShotGroup).duration
      ? ` (${(props.group as ShotGroup).duration})`
      : '';

  return (
    <div
      class={`sb-group ${props.dragOver ? 'border-accent-blue' : ''}`}
      draggable={dragEnabled()}
      onMouseDown={(e) => setDragEnabled(isBlankDragArea(e.target))}
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
              autofocus
              onInput={(e) => setTitleVal(e.currentTarget.value)}
              onBlur={() => { studioActions.renameGroupLocal(props.type, props.group.id, { title: titleVal().trim() || props.group.title }); setEditingTitle(false); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { studioActions.renameGroupLocal(props.type, props.group.id, { title: titleVal().trim() || props.group.title }); setEditingTitle(false); } if (e.key === 'Escape') setEditingTitle(false); }}
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
                autofocus
                onInput={(e) => setBadgeVal(e.currentTarget.value)}
                onBlur={() => saveBadge(badgeVal())}
                onKeyDown={(e) => { if (e.key === 'Enter') saveBadge(badgeVal()); if (e.key === 'Escape') setEditingBadge(false); }}
              />
            </Show>
            <span class="sb-index">{props.index}</span>
          </span>
        </Show>
      </div>

      {/* 场景引用 chips（仅分镜） */}
      <Show when={sceneRefs().length > 0}>
        <div class="scene-refs">
          场景:
          <For each={sceneRefs()}>
            {(ref) => (
              <button
                type="button"
                class="scene-ref-chip"
                title="点击跳转到该关键元素"
                onClick={() => studioActions.jumpToElementByTitle(String(ref))}
              >
                {ref}
              </button>
            )}
          </For>
        </div>
      </Show>

      {/* 描述（双击编辑） */}
      <Show when={editingDesc()} fallback={
        <p
          class="sb-desc"
          title="双击编辑描述"
          onDblClick={() => { setDescVal(meta().desc); setEditingDesc(true); }}
        >
          {meta().desc || '双击添加描述...'}
        </p>
      }>
        <input
          class="sb-desc-input"
          value={descVal()}
          autofocus
          placeholder="输入描述..."
          onInput={(e) => setDescVal(e.currentTarget.value)}
          onBlur={() => { studioActions.renameGroupLocal(props.type, props.group.id, { desc: descVal() }); setEditingDesc(false); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { studioActions.renameGroupLocal(props.type, props.group.id, { desc: descVal() }); setEditingDesc(false); } if (e.key === 'Escape') setEditingDesc(false); }}
        />
      </Show>

      {/* 草稿卡片行（小标编号：组号-卡序号，可拖动排序） */}
      <div class="draft-cards-row">
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
          )}
        </For>
      </div>

      {/* 微调输入框（旧版 card-adjust-box） */}
      <div class="card-adjust-box">
        <input
          type="text"
          class="card-adjust-input"
          placeholder={meta().placeholder}
          value={adjustText()}
          onInput={(e) => setAdjustText(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendAdjust()}
        />
        <button
          type="button"
          class="card-adjust-btn"
          onClick={sendAdjust}
        >
          微调
        </button>
      </div>
    </div>
  );
}
