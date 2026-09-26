import { createEffect, createSignal, For, onCleanup, Show } from 'solid-js';
import { FiPlus, FiX } from 'solid-icons/fi';
import { state, studioActions } from '@/stores/studio';
import {
  normalizeDisplayTitle, resolveRefElement, stripTypePrefix,
} from '@/lib/desc-ref-utils';
import type { ShotGroup } from '@/types';

/**
 * 引用 chips（仅分镜组）。
 * 点击跳转；× 删除与 + 添加（为 LLM 写提示词提供依据，
 * 并决定出图/出视频时自动挂哪些元素概念图）。
 */
export function ShotRefsChips(props: { group: ShotGroup }) {
  const shotRefs = () => props.group.shotRefs || [];
  const [refPickerOpen, setRefPickerOpen] = createSignal(false);

  /** canonical 比对键（与后端 `storyboard_ops.canonical_ref_key` 同契约：
   *  剥容器类型前缀；裸名与 Element_ 全称算同一引用）。 */
  const canonicalRefKey = (ref: string) => stripTypePrefix(String(ref ?? '').trim());

  /** shotRefs 存储的是关键元素 id（ke-xxx）或标题（**落库形态 = 带前缀全称**，
   *  2026-09-25 用户裁决）；展示时经 canonical 单一入口解析
   *  （`resolveRefElement`），再经显示层归一单一事实源 normalizeDisplayTitle
   *  剥前缀——存量裸名数据同样命中（读时兼容）。 */
  const rawResolve = (ref: string) => resolveRefElement(ref, state.keyElements)?.title || String(ref);
  const refLabel = (ref: string) => normalizeDisplayTitle(rawResolve(ref));

  /** flova 对齐批（2026-09-17）：显示层兜底去重——存量 shotRefs 同元素裸名与
   *  Element_ 双份（K4 三源合并历史数据）按解析标签去重保序留首；
   *  写口去重已在后端同步落地，新数据不再产双份。 */
  const visibleRefs = () => {
    const seen = new Set<string>();
    return shotRefs().filter((r) => {
      const label = refLabel(String(r));
      if (seen.has(label)) return false;
      seen.add(label);
      return true;
    });
  };

  /** 添加候选的关键元素标题（**存储口径 = 元素原标题**，带 Element_ 前缀）。
   *  2026-09-25（用户裁决「不能传裸名，裸名只是 UI 视觉效果」）：候选值必须是
   *  落库全称（带前缀），显示层才剥前缀——此前候选直接复用 title 又未经
   *  normalizeDisplayTitle 渲染，前缀会漏进弹层 UI。去重按 canonical 比对
   *  （已引用的裸名与候选全称算同一元素，不重复列）。 */
  const availableElements = () => {
    // 已引用集合用 canonical 键：先把每条 ref 解析到元素（覆盖 ke-xxx 组 id 形态），
    // 再取其 canonical 键——否则「ke-1」与候选「Element_少女」键不同，同一元素会被重复列出。
    const have = new Set(
      shotRefs().map((r) => canonicalRefKey(resolveRefElement(String(r), state.keyElements)?.title || String(r))),
    );
    return state.keyElements
      .map((k) => k.title)
      .filter((t): t is string => !!t && !have.has(canonicalRefKey(t)));
  };

  function removeShotRef(ref: string) {
    studioActions.setShotRefsLocal(
      props.group.id,
      shotRefs().filter((r) => String(r) !== ref).map(String),
    );
  }

  function addShotRef(title: string) {
    studioActions.setShotRefsLocal(props.group.id, [...shotRefs().map(String), title]);
    setRefPickerOpen(false);
  }

  /** 点选单外区域关闭添加候选弹层 */
  createEffect(() => {
    if (!refPickerOpen()) return;
    const onDown = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && el.closest('.shot-ref-add-wrap')) return;
      setRefPickerOpen(false);
    };
    document.addEventListener('pointerdown', onDown, true);
    onCleanup(() => document.removeEventListener('pointerdown', onDown, true));
  });

  return (
    <div class="shot-refs">
      <Show when={visibleRefs().length > 0}>
        <span class="shot-refs-label">引用:</span>
        <For each={visibleRefs()}>
          {(ref) => (
            <span class="shot-ref-chip shot-ref-editable">
              <button
                type="button"
                class="shot-ref-jump"
                title="点击跳转到该关键元素"
                onClick={() => studioActions.jumpToElementByTitle(String(ref))}
              >
                {refLabel(String(ref))}
              </button>
              <button
                type="button"
                class="shot-ref-remove"
                title="移除引用（出视频时不再自动挂该元素概念图）"
                onClick={() => removeShotRef(String(ref))}
              >
                <FiX size={10} />
              </button>
            </span>
          )}
        </For>
      </Show>
      <span class="shot-ref-add-wrap">
        <button
          type="button"
          class="shot-ref-chip shot-ref-add"
          title="添加引用（本镜头出场的关键元素）"
          onClick={() => setRefPickerOpen((v) => !v)}
        >
          <FiPlus size={10} /> 添加
        </button>
        <Show when={refPickerOpen()}>
          <div class="shot-ref-picker">
            <Show when={availableElements().length} fallback={
              <div class="shot-ref-picker-empty">没有可添加的关键元素</div>
            }>
              <For each={availableElements()}>
                {(t) => (
                  <button type="button" class="shot-ref-picker-item" onClick={() => addShotRef(t)}>
                    {/* 候选值 = 元素原标题（带前缀，落库口径）；**显示剥前缀**
                        （裸名只是 UI 视觉效果——2026-09-25 用户裁决） */}
                    {normalizeDisplayTitle(t)}
                  </button>
                )}
              </For>
            </Show>
          </div>
        </Show>
      </span>
    </div>
  );
}
