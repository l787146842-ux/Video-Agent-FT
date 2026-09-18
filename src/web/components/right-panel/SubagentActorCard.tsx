/**
 * SubagentActorCard — 子代理 actor 卡（流式二期，计划书 §四.3）。
 *
 * 主 Feed 内把一个子代理的全部活动归组为一张具名卡（flova specialist 形态）：
 * 标签（阶段名/任务摘要）+ 实时态（执行中/已完成/已中断）+ 步数 +
 * 子工具名单（折叠，信息不丢只换载体，计划书 §七风险 A）。
 * 点击卡 → 中间面板切「子任务」视图并选中该子线程（只读执行记录复用 SubagentRail）；
 * cid 为空（子会话创建失败降级不落流）时无记录可看 → 据实禁用，不给死链。
 * 状态语义色复用 .subagent-status 三态（--color-info/--color-success/--color-danger），
 * 卡体排版另立 .actor-* 类，均走 token（scripts/check_semantic_colors.py 闸）。
 */
import { For, Show, createSignal } from 'solid-js';
import {
  FiCheckCircle, FiChevronDown, FiLoader, FiXCircle,
} from 'solid-icons/fi';
import { t } from '@/lib/locale';
import { formatElapsed } from '@/lib/timeline';
import { studioActions } from '@/stores/studio';
import {
  requestSubagentRecord, type SubagentActor,
} from '@/stores/chat/subagent-actors';

/** 三态 → 药丸类名（与 SubagentRail 同口径；actor 域不产 unknown 态） */
function statusClass(s: SubagentActor['status']): string {
  return s === 'running' ? 'running' : s === 'completed' ? 'completed' : 'failed';
}

/** 三态 → 文案（走 i18n 字典，不硬编码） */
function statusText(s: SubagentActor['status']): string {
  if (s === 'running') return t('rp.actor.running');
  return s === 'completed' ? t('rp.actor.completed') : t('rp.actor.failed');
}

export function SubagentActorCard(props: { actor: () => SubagentActor | undefined }) {
  const [open, setOpen] = createSignal(false);
  /** 有子线程 id 才可点进只读记录（降级不落流的 actor 无记录可看） */
  const clickable = () => !!props.actor()?.cid;

  function openRecord(): void {
    const cid = props.actor()?.cid || '';
    if (!cid) return;
    requestSubagentRecord(cid);
    studioActions.setMiddleView('subagents');
  }

  return (
    <Show when={props.actor()}>
      {(actor) => (
        <div class="actor-card" data-testid="subagent-actor-card">
          <button
            type="button"
            class="actor-card-head"
            onClick={openRecord}
            disabled={!clickable()}
            title={clickable() ? t('rp.actor.openRecord') : actor().label}
            data-testid="subagent-actor-head"
          >
            <span class={`subagent-status ${statusClass(actor().status)}`}>
              <span class="subagent-status-dot" />
              {statusText(actor().status)}
            </span>
            <span class="actor-badge">{t('rp.actor.badge')}</span>
            <span class="actor-card-label">{actor().label || t('rp.actor.fallbackLabel')}</span>
            <span class="actor-card-steps">{t('rp.actor.steps', { count: actor().steps })}</span>
          </button>

          {/* 子工具名单（折叠）：归组后父 Feed 不显子工具细节，此处保留全名单 */}
          <Show when={actor().tools.length > 0}>
            <button
              type="button"
              class="actor-tools-toggle"
              aria-expanded={open()}
              onClick={() => setOpen(!open())}
            >
              {t('rp.actor.tools', { count: actor().tools.length })}
              <FiChevronDown size={11} class={`tl-item-toggle-arrow${open() ? ' expanded' : ''}`} />
            </button>
            <Show when={open()}>
              <ul class="actor-tools">
                <For each={actor().tools}>
                  {(tl) => (
                    <li class="actor-tool">
                      <Show
                        when={tl.status !== 'running'}
                        fallback={<FiLoader size={11} class="actor-tool-mark spin" />}
                      >
                        <Show
                          when={tl.status === 'done'}
                          fallback={<FiXCircle size={11} class="actor-tool-mark failed" />}
                        >
                          <FiCheckCircle size={11} class="actor-tool-mark ok" />
                        </Show>
                      </Show>
                      <span class="actor-tool-summary" title={tl.resultSummary || tl.summary}>
                        {tl.summary || tl.name}
                      </span>
                      <Show when={tl.status !== 'running' && tl.elapsedMs != null}>
                        <span class="actor-tool-elapsed">· {formatElapsed(tl.elapsedMs || 0)}</span>
                      </Show>
                    </li>
                  )}
                </For>
              </ul>
            </Show>
          </Show>
        </div>
      )}
    </Show>
  );
}
