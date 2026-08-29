/**
 * 执行偏好三档（2026-08-30 用户裁决，Skill 系统修复批 B）——自 GlobalSettingsView 切出。
 * 管花钱生成动作（生成图片/生成视频）要不要先弹确认卡：
 * 自动决定（有活跃 Skill 指导免逐次确认）/ 生成前确认（默认=现状）/ 直接生成。
 * 枚举白名单与默认档以 sidecar 契约导出为唯一来源（不硬编码档位）。
 */
import { ParamGroup, ParamSelect } from '@/components/middle-panel/params/ParamBase';
import {
  EXECUTION_PREFERENCE_DEFAULT,
  EXECUTION_PREFERENCE_VALUES,
} from '@/types/api.generated';
import type { RuntimeSettings } from '@/api/agent';

/** 三档中文文案（前端体验规范 §三：界面文案中文唯一） */
const PREF_LABELS: Record<string, string> = {
  auto_decide: '自动决定',
  confirm_before_gen: '生成前确认（默认）',
  generate_directly: '直接生成',
};
const PREF_HINTS: Record<string, string> = {
  auto_decide:
    '有活跃 Skill 指导时，常规生成图片/视频免逐次确认（系统代发同意并留痕）；无 Skill 指导时仍按现状弹确认卡。',
  confirm_before_gen:
    '每次花钱生成（生成图片/生成视频）前都先弹确认卡，确认后才执行（与现状一致）。',
  generate_directly:
    '生成图片/视频不再弹确认卡，直接执行（留痕）。注意：该档位花钱操作无逐次确认，请谨慎使用。',
};

export function ExecutionPreferenceSection(props: {
  gs: () => RuntimeSettings | null;
  set: (patch: Partial<RuntimeSettings>) => void;
}) {
  /** 当前档（脏值回落默认档，与后端清洗同口径） */
  const current = () => {
    const v = props.gs()?.execution_preference || '';
    return (EXECUTION_PREFERENCE_VALUES as readonly string[]).includes(v)
      ? v
      : EXECUTION_PREFERENCE_DEFAULT;
  };
  return (
    <section class="gs-section">
      <h3>执行偏好</h3>
      <div class="gs-row">
        <ParamGroup label="花钱生成确认:">
          <ParamSelect
            ariaLabel="执行偏好（花钱生成是否先弹确认卡）"
            value={current()}
            options={EXECUTION_PREFERENCE_VALUES.map((v) => ({
              value: v,
              label: PREF_LABELS[v] ?? v,
            }))}
            onChange={(v) => props.set({ execution_preference: v })}
          />
        </ParamGroup>
      </div>
      <p class="gs-hint">{PREF_HINTS[current()]}</p>
      <p class="gs-hint">
        任何档位下：未注册工具、文档写入与画布操作等高危动作照常拦截，Skill 声明的暂停点不可被跳过。
      </p>
    </section>
  );
}
