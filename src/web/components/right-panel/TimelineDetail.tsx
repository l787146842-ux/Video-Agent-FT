import { For, Show, createSignal } from 'solid-js';
import { FiChevronDown } from 'solid-icons/fi';
import {
  approvalInteractionLabel,
  argsPreviewEntries, resultSummaryView, toolApprovalTier, toolDetailTier, type TimelineItem,
} from '@/lib/timeline';

/**
 * 时间线条目详情区（任务 #2 分级展开，分级判定见 lib/timeline.toolDetailTier）：
 * - expand 档：可折叠详情卡。折叠态 = 一句话结果摘要（一眼信息不变），
 *   展开后看「输入参数」截断预览 +「执行结果」全文；
 * - output / none 档：保持现状（结果摘要一行留痕，多句可展开全文，不显示输入）。
 * 任务 P2-5：审批分级正交轴映射——confirm/review 档工具挂交互档徽标，
 * 档位判定见 lib/timeline.toolApprovalTier（后端 approval_tier 元数据驱动）。
 */
export function TimelineDetail(props: { item: TimelineItem }) {
  const [open, setOpen] = createSignal(false);
  const [resultOpen, setResultOpen] = createSignal(false);
  const tier = () => toolDetailTier(props.item.name);
  const approval = () => toolApprovalTier(props.item.name);
  /* 徽标只在有工具名依据且登记了交互档时挂：无名条目与未登记工具名
   *（MCP 动态工具/历史改名）展示层返回 none，不误挂「需确认」；
   * 执行边界 deny-by-default 由后端持有，不靠徽标兜底 */
  const approvalLabel = () => (
    props.item.name ? approvalInteractionLabel(approval()) : ''
  );
  const entries = () => argsPreviewEntries(props.item.args);
  const result = () => props.item.result_summary || '';
  // 事件卡折叠区全文（对齐批：分析报告全文挂卡，detail_md 优先于单行摘要）
  const fullText = () => props.item.detail_md || result();
  const showResult = () => !!fullText() && fullText() !== props.item.summary;
  const hasDetail = () => entries().length > 0 || showResult();

  /** 审批档交互徽标（confirm=需确认 / review=需审批；none 档不渲染）；
   * 函数式：多个分支位点各自实例化（Solid JSX 节点不可多处复用） */
  const approvalBadge = () => (
    <Show when={approvalLabel()}>
      <span class={`tl-approval-badge tl-approval-${approval()}`}>{approvalLabel()}</span>
    </Show>
  );

  return (
    <Show when={props.item.status !== 'running'}>
      <Show
        when={tier() === 'expand' && hasDetail()}
        fallback={
          /* 中间/不展开档：仅输出留痕（与既有单行摘要形态一致）；
           * detail_md 存在（事件卡携全文）时折叠行=单行摘要、展开看全文 */
          <Show when={showResult()}>
            <Show
              when={resultSummaryView(result()).expandable || !!props.item.detail_md}
              fallback={
                <span class="tl-item-result" title={fullText()}>
                  ↳ {fullText()}
                  {approvalBadge()}
                </span>
              }
            >
              <button
                type="button"
                class={`tl-item-result tl-item-result-toggle${resultOpen() ? ' expanded' : ''}`}
                onClick={() => setResultOpen(!resultOpen())}
              >
                ↳ {resultOpen() ? fullText() : resultSummaryView(result()).collapsed || result()}
                <FiChevronDown size={11} class={`tl-item-toggle-arrow${resultOpen() ? ' expanded' : ''}`} />
                {approvalBadge()}
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
            {approvalBadge()}
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
                  <span class="tl-detail-result">{fullText()}</span>
                </div>
              </Show>
            </div>
          </Show>
        </div>
      </Show>
    </Show>
  );
}
