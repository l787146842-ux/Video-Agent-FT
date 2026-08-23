import { For, Show, createSignal } from 'solid-js';
import { FiChevronDown } from 'solid-icons/fi';
import {
  argsPreviewEntries, resultSummaryView, toolDetailTier, type TimelineItem,
} from '@/lib/timeline';

/**
 * 时间线条目详情区（任务 #2 分级展开，分级判定见 lib/timeline.toolDetailTier）：
 * - expand 档：可折叠详情卡。折叠态 = 一句话结果摘要（一眼信息不变），
 *   展开后看「输入参数」截断预览 +「执行结果」全文；
 * - output / none 档：保持现状（结果摘要一行留痕，多句可展开全文，不显示输入）。
 */
export function TimelineDetail(props: { item: TimelineItem }) {
  const [open, setOpen] = createSignal(false);
  const [resultOpen, setResultOpen] = createSignal(false);
  const tier = () => toolDetailTier(props.item.name);
  const entries = () => argsPreviewEntries(props.item.args);
  const result = () => props.item.result_summary || '';
  const showResult = () => !!result() && result() !== props.item.summary;
  const hasDetail = () => entries().length > 0 || showResult();

  return (
    <Show when={props.item.status !== 'running'}>
      <Show
        when={tier() === 'expand' && hasDetail()}
        fallback={
          /* 中间/不展开档：仅输出留痕（与既有单行摘要形态一致） */
          <Show when={showResult()}>
            <Show
              when={resultSummaryView(result()).expandable}
              fallback={
                <span class="tl-item-result" title={result()}>
                  ↳ {result()}
                </span>
              }
            >
              <button
                type="button"
                class={`tl-item-result tl-item-result-toggle${resultOpen() ? ' expanded' : ''}`}
                onClick={() => setResultOpen(!resultOpen())}
              >
                ↳ {resultOpen() ? result() : resultSummaryView(result()).collapsed}
                <FiChevronDown size={11} class={`tl-item-toggle-arrow${resultOpen() ? ' expanded' : ''}`} />
              </button>
            </Show>
          </Show>
        }
      >
        {/* expand 档：详情卡（输入参数截断预览 + 执行结果全文） */}
        <div class="tl-detail">
          <button
            type="button"
            class="tl-detail-toggle"
            aria-expanded={open()}
            onClick={() => setOpen(!open())}
          >
            ↳ {showResult() ? resultSummaryView(result()).collapsed : '输入参数'}
            <FiChevronDown size={11} class={`tl-item-toggle-arrow${open() ? ' expanded' : ''}`} />
          </button>
          <Show when={open()}>
            <div class="tl-detail-body">
              <Show when={entries().length > 0}>
                <div class="tl-detail-section">
                  <span class="tl-detail-label">输入参数</span>
                  <For each={entries()}>
                    {(e) => (
                      <div class="tl-detail-kv">
                        <span class="tl-detail-key">{e.key}</span>
                        <span class="tl-detail-val">{e.value}</span>
                      </div>
                    )}
                  </For>
                </div>
              </Show>
              <Show when={showResult()}>
                <div class="tl-detail-section">
                  <span class="tl-detail-label">执行结果</span>
                  <span class="tl-detail-result">{result()}</span>
                </div>
              </Show>
            </div>
          </Show>
        </div>
      </Show>
    </Show>
  );
}
