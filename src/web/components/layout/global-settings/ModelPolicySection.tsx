/**
 * 模型分层策略表（四角色自动路由；空 = 跟随主模型）——自 GlobalSettingsView 切出。
 * 「推理档位」卡退役——子代理/摘要档位归入本表「推理」列
 * （通用搭配默认：摘要 = 低；子代理缺省跟随主模型，防思考吃预算）。
 */
import { For } from 'solid-js';
import { apiProvidersFor, providerModels } from '@/lib/providers';
import { ParamGroup, ParamSelect } from '@/components/middle-panel/params/ParamBase';
import type { RuntimeSettings } from '@/api/agent';
import type { PolicyRow } from '@/types/api.generated';

/** ：模型分层策略表四角色（编排/生成/摘要/子代理） */
const MODEL_POLICY_ROLES = [
  { key: 'orchestration', label: '编排规划' },
  { key: 'generation_strong', label: '生成' },
  { key: 'summary', label: '摘要' },
  { key: 'subagent', label: '子代理' },
] as const;

/**  推理档位四档：默认=模型原生 */
const thinkingOpts = () => [
  { value: '', label: '默认（原生）' },
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
];

export function ModelPolicySection(props: {
  gs: () => RuntimeSettings | null;
  set: (patch: Partial<RuntimeSettings>) => void;
}) {
  /** ：单角色策略局部更新（保留其他角色与其他键） */
  function setPolicyRole(roleKey: string, patch: Partial<PolicyRow>) {
    const policy = { ...(props.gs()?.model_policy || {}) };
    const cur = { ...(policy[roleKey] || { provider: '', model: '', thinking_level: '' }) };
    policy[roleKey] = { ...cur, ...patch };
    props.set({ model_policy: policy });
  }

  return (
    <section class="gs-section">
      <h3>模型分层策略</h3>
      <div class="gs-role-list">
        <For each={MODEL_POLICY_ROLES}>
          {(role) => (
            <div class="gs-row">
              <ParamGroup label={role.label + ':'}>
                <ParamSelect
                  ariaLabel={`${role.label}供应商`}
                  value={props.gs()!.model_policy?.[role.key]?.provider || ''}
                  options={[
                    { value: '', label: '跟随主模型' },
                    ...apiProvidersFor('chat').map((p) => ({ value: p.id, label: p.name || p.id })),
                  ]}
                  onChange={(v) => setPolicyRole(role.key, { provider: v, model: '' })}
                />
              </ParamGroup>
              <ParamGroup label="模型:">
                <ParamSelect
                  ariaLabel={`${role.label}模型`}
                  value={props.gs()!.model_policy?.[role.key]?.model || ''}
                  options={[
                    { value: '', label: '默认' },
                    ...providerModels(props.gs()!.model_policy?.[role.key]?.provider || '', 'chat')
                      .map((m) => ({ value: m, label: m })),
                  ]}
                  onChange={(v) => setPolicyRole(role.key, { model: v })}
                />
              </ParamGroup>
              <ParamGroup label="推理:">
                <ParamSelect
                  ariaLabel={`${role.label}推理档位`}
                  value={props.gs()!.model_policy?.[role.key]?.thinking_level || ''}
                  options={thinkingOpts()}
                  onChange={(v) => setPolicyRole(role.key, { thinking_level: v })}
                />
              </ParamGroup>
            </div>
          )}
        </For>
      </div>
      <p class="gs-hint">
        编排规划 = 主对话/规划轮；生成 = 长文生成与纠正重试；摘要 = 记忆摘要与会话压缩；
        子代理 = run_subagent 委派出的隔离子级（缺省跟随主模型，配了就接管子级模型）。
        「跟随主模型」= 不覆盖（沿用对话栏所选模型与既有回落链）；
        推理档通用搭配默认：摘要 = 低（照章办事不需深推理，防思考吃光输出预算），子代理/编排/生成 = 原生；改动即时生效。
      </p>
    </section>
  );
}
