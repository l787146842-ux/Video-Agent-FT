import { createSignal, For, Show } from 'solid-js';
import { FiPlus } from 'solid-icons/fi';
import { studioActions } from '@/stores/studio';
import { DraftCard } from './DraftCard';
import { GroupHeader } from './group-card/GroupHeader';
import { SceneRefsChips } from './group-card/SceneRefsChips';
import { GroupDescEditor } from './group-card/GroupDescEditor';
import { GroupAdjustBox } from './group-card/GroupAdjustBox';
import type {
  AnyGroup, AudioGroup, DraftType, KeyElementGroup, ShotGroup,
} from '@/types';

/**
 * 单个故事板分组卡片
 * 按类型渲染：关键元素（蓝）/ 分镜（紫，含场景引用 chips）/ 音频（绿）
 * 支持分组级拖拽排序（drag 事件由 StoryboardView 协调）。
 * 八轮 B7（T25）：分组头/场景引用/描述编辑/微调行切至 group-card/ 子组件。
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
  /** 当前悬停的草稿卡（微调输入行绑定目标；未悬停时默认第一张） */
  const [hoverDraftId, setHoverDraftId] = createSignal('');
  /** 卡片行悬停态（仅悬停在卡片/输入行上才展开微调行，悬停标题描述不触发） */
  const [cardsHover, setCardsHover] = createSignal(false);
  let adjustBoxRef: HTMLDivElement | undefined;

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
          adjustLabel: '分镜',
        };
      }
      default: {
        return {
          badge: (props.group as AudioGroup).timeRange || '音频',
          badgeStyle: {
            background: 'rgba(16, 185, 129, 0.15)',
            color: 'var(--accent-emerald)',
          },
          desc: (props.group as AudioGroup).prompt || '',
          addTitle: '上传或写提示词生成音频',
          adjustLabel: '音频',
        };
      }
    }
  };

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
      <GroupHeader
        type={props.type}
        groupId={props.group.id}
        title={() => props.group.title}
        titleSuffix={titleSuffix}
        index={() => props.index}
        badge={() => meta().badge}
        badgeStyle={() => meta().badgeStyle}
      />

      {/* 场景引用 chips（仅分镜）：子组件承载跳转/删除/添加（C4） */}
      <Show when={props.type === 'shot'}>
        <SceneRefsChips group={props.group as ShotGroup} />
      </Show>

      {/* 描述（双击编辑；子组件承载自适应编辑框） */}
      <GroupDescEditor type={props.type} groupId={props.group.id} desc={() => meta().desc} />

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

      {/* 组级微调输入行：子组件承载（悬停态/生效卡判定共享本组件信号） */}
      <GroupAdjustBox
        drafts={props.group.drafts || []}
        index={() => props.index}
        groupTitle={() => props.group.title}
        adjustLabel={meta().adjustLabel}
        hoverDraftId={hoverDraftId}
        cardsHover={cardsHover}
        setCardsHover={setCardsHover}
        registerRef={(el) => { adjustBoxRef = el; }}
      />
    </div>
  );
}
