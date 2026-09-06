/**
 * 执行模式四档（2026-09-06 用户裁决，Flova 对齐批）——自 GlobalSettingsView 切出。
 * 管流程推进的暂停策略：由 AI 判断（默认=现状）/ 自动执行全流程 /
 * 关键步骤手动确认（平台机械拦停六个里程碑）/ 全部暂停确认（每阶段拦停）。
 * 与「执行偏好」（花钱生成是否先弹确认卡）正交；枚举白名单与默认档以
 * sidecar 契约导出为唯一来源（不硬编码档位）。
 */
import { ParamGroup, ParamSelect } from '@/components/middle-panel/params/ParamBase';
import {
  EXECUTION_MODE_DEFAULT,
  EXECUTION_MODE_VALUES,
} from '@/types/api.generated';
import type { RuntimeSettings } from '@/api/agent';

/** 四档中文文案（前端体验规范 §三：界面文案中文唯一） */
const MODE_LABELS: Record<string, string> = {
  ai_decide: '由 AI 判断（默认）',
  auto_full: '自动执行全流程',
  key_steps_confirm: '关键步骤手动确认',
  pause_all: '全部暂停确认',
};
const MODE_HINTS: Record<string, string> = {
  ai_decide:
    '停不停由 Agent 按 Skill 流程与当场情况判断（现状行为）：Skill 声明的暂停点照常停，信息缺口照常问。',
  auto_full:
    '整条流程直通不打断：Agent 不发起阶段暂停确认，Skill 声明的暂停点按直通处理；仅信息缺口必答时才会停下。',
  key_steps_confirm:
    '制作规格、故事板、关键元素、镜头视频、音频、成片六个里程碑完成后，平台强制暂停等你确认——即使 Skill 声明直通。',
  pause_all:
    '每个阶段完成后平台强制暂停等你确认，逐步审阅推进。',
};

export function ExecutionModeSection(props: {
  gs: () => RuntimeSettings | null;
  set: (patch: Partial<RuntimeSettings>) => void;
}) {
  /** 当前档（脏值回落默认档，与后端清洗同口径） */
  const current = () => {
    const v = props.gs()?.execution_mode || '';
    return (EXECUTION_MODE_VALUES as readonly string[]).includes(v)
      ? v
      : EXECUTION_MODE_DEFAULT;
  };
  return (
    <section class="gs-section">
      <h3>执行模式</h3>
      <div class="gs-row">
        <ParamGroup label="默认执行模式:">
          <ParamSelect
            ariaLabel="执行模式（流程推进的暂停策略）"
            value={current()}
            options={EXECUTION_MODE_VALUES.map((v) => ({
              value: v,
              label: MODE_LABELS[v] ?? v,
            }))}
            onChange={(v) => props.set({ execution_mode: v })}
          />
        </ParamGroup>
      </div>
      <p class="gs-hint">{MODE_HINTS[current()]}</p>
      <p class="gs-hint">
        本档位管流程推进的暂停策略；花钱生成是否先弹确认卡由「执行偏好」单独控制，两档互不影响。
      </p>
    </section>
  );
}
