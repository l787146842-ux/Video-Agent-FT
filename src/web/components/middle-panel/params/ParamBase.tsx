/**
 * 参数控件基础件：容器/通用下拉/按钮类名/保存动作。
 * ProviderModelSelects 与 ExportButton 已按职责切至同目录，
 * 消费方直接 import 新位置。
 */
import { For, createEffect, type ParentProps } from 'solid-js';
import { findDraftRecord, persistBoard, state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { studioImageSizeForRatio } from '@/lib/image-sizes';

/** 参数变更后防抖持久化（所有参数控件 onChange 统一走这里） */
export function persistParams() {
  persistBoard();
}

/** 参数组容器（旧版 .param-group + .param-label） */
export function ParamGroup(props: ParentProps<{ label: string }>) {
  return (
    <div class="param-group">
      <span class="param-label">{props.label}</span>
      {props.children}
    </div>
  );
}

/** 通用下拉（动态宽度：框宽随当前选中文本的实际长度变化——紧凑且不截断。
 * 原理：克隆只含当前选项的同样式 select，量浏览器算出的自然宽度（原生箭头
 * 占位已被计入，不同系统/浏览器都不会估错）再写回；widthPx：传入时强制固定宽度） */
export function ParamSelect(props: {
  value: string;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
  ariaLabel: string;
  onChange: (value: string) => void;
  widthPx?: number;
}) {
  let selectRef: HTMLSelectElement | undefined;
  const currentLabel = () =>
    props.options.find((o) => o.value === props.value)?.label || props.value || '';
  // 选中项变化时重新测量：短名字框就短，长名字框跟着变长，永不裁半截。
  // rAF 延后到下一帧再量：组件处于 <Show>/<Switch> 动态分支内时，effect 首跑时
  // 元素尚未插入文档，测得的宽度恒为 0（曾导致宽度永远落在 64px 下限，文字被裁）
  createEffect(() => {
    const txt = currentLabel(); // 跟踪选中项变化
    if (props.widthPx) return;
    requestAnimationFrame(() => {
      const el = selectRef;
      if (!el) return;
      // 克隆一个只含当前选项的同样式 select 量自然宽度：width:auto 时浏览器
      // 按文本 + 原生箭头占位自行计算（直接量原框会取最长选项宽度，不够紧凑；
      // 隐藏 span 测文本宽再手动加箭头位则各系统差异大，实测每框差十几像素）
      const probe = document.createElement('select');
      probe.className = el.className;
      probe.style.cssText = 'position:absolute;visibility:hidden;width:auto;';
      const opt = document.createElement('option');
      opt.textContent = txt;
      probe.appendChild(opt);
      document.body.appendChild(probe);
      const natural = probe.getBoundingClientRect().width;
      probe.remove();
      // 下限 64px：空值/超短值时保持最小可点击宽度
      el.style.width = `${Math.max(Math.ceil(natural), 64)}px`;
    });
  });
  return (
    <select
      ref={selectRef}
      class="param-select"
      aria-label={props.ariaLabel}
      value={props.value}
      style={props.widthPx ? { width: `${props.widthPx}px` } : undefined}
      onChange={(e) => props.onChange(e.currentTarget.value)}
    >
      <For each={props.options}>
        {(opt) => <option value={opt.value} disabled={opt.disabled}>{opt.label}</option>}
      </For>
    </select>
  );
}

/** 次要按钮（保存）：旧版 .btn-secondary */
export const btnSecondary = 'btn-secondary';

/** 主要按钮（生成）：旧版 .btn-primary（配色变体用 btn-purple/btn-emerald 复合类） */
export const btnPrimary = 'btn-primary';

/** 保存按钮动作：校正图片尺寸 + 立即冲刷防抖保存（不等 400ms） */
export function saveDraftParams() {
  const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
  if (!rec) return;
  const d = rec.draft;
  if (state.selectedType === 'keyElement') {
    d.size = studioImageSizeForRatio(
      d.aspectRatio || '1:1',
      d.customRatioWidth,
      d.customRatioHeight,
    );
  }
  persistBoard();
  persistBoard.flush();
  showToast('参数已保存到草稿卡片', 'success');
}
