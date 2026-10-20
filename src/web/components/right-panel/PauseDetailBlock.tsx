import { Show, createSignal } from 'solid-js';
import { FiChevronDown } from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { detailLineCount, detailSummary, shouldCollapseDetail } from '@/lib/pause-detail';

/**
 * 暂停卡辅助说明区（dsh `detail`）——短说明内联，长说明/清单折叠。
 *
 * 2026-10-09（事故 6666，用户裁决「改成折叠展示」）：契约要求确认批次产出时
 * 逐条列出被确认对象（4444/P2-1，防止用户批准看不见的东西），但 9 条清单会
 * 把题面和选项挤出视野。本组件把**呈现**改为：默认只露首行摘要 + 「展开全部
 * N 条」，点击展开全文（内容一字不少）。判定见 lib/pause-detail（纯函数）。
 *
 * 收放状态留在组件内（每张卡各自独立，卡被取代/回看时互不影响）。
 */
export function PauseDetailBlock(props: { text: string }) {
  const body = () => (props.text || '').trim();
  const collapsible = () => shouldCollapseDetail(body());
  const [open, setOpen] = createSignal(false);
  /** 规模计数（非空行数，口径同「共 N 行」；见 lib/pause-detail.detailLineCount） */
  const lineCount = () => detailLineCount(body());

  return (
    <Show when={body()}>
      <Show
        when={collapsible()}
        fallback={<div class="confirm-wizard-detail">{body()}</div>}
      >
        <div class="confirm-wizard-detail collapsible">
          <button
            type="button"
            class="confirm-detail-toggle"
            data-testid="pause-detail-toggle"
            aria-expanded={open()}
            onClick={() => setOpen(!open())}
          >
            {/* 折叠态：首行摘要；展开态：完整正文（含换行由 pre-wrap 呈现） */}
            <span class="confirm-detail-text">
              {open() ? body() : detailSummary(body())}
            </span>
            <span class="confirm-detail-cue">
              {open()
                ? t('rp.confirm.detailCollapse')
                : t('rp.confirm.detailExpand', { n: lineCount() })}
              <FiChevronDown size={11} class={`confirm-detail-arrow${open() ? ' expanded' : ''}`} />
            </span>
          </button>
        </div>
      </Show>
    </Show>
  );
}
