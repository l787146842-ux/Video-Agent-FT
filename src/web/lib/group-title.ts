/**
 * 分组标题归一 + 元素名形态 —— 前端**叶子模块**（无业务依赖，可被任意 lib 引用）。
 *
 * 为什么单独成文件（2026-09-26）：
 * ① `stripTypePrefix` 此前在 `desc-ref-utils.ts` 与 `prompt-mentions.ts` **各写一份**
 *    （P1 违规：同一规则两个表述源）；② 新增的「括注主名」形态两处都要用，
 *    而 `prompt-mentions` 导入 `desc-ref-utils` 会构成环（后者已依赖
 *    `prompt-ref-utils`，而 `prompt-ref-utils` 又依赖 `prompt-mentions`）。
 *    ⇒ 把「标题前缀 + 元素名形态」这一层下沉为叶子模块，两处 re-export
 *    （既有导入路径全部保持，测试 patch 目标不变）。
 *
 * 与后端同契约镜像：`state/storyboard_ops.py` 的 `strip_type_prefix` /
 * `element_alias_name` / `element_name_variants`。
 */
import type { DraftType } from '@/types';

/** 容器 ID 约定类型前缀（2026-09-17 裁决；后端 `_GROUP_TITLE_PREFIX` 同契约镜像） */
export const GROUP_TITLE_PREFIX: Record<DraftType, string> = {
  keyElement: 'Element_',
  shot: 'Shot_',
  audio: 'Audio_',
};

const TYPE_PREFIXES = Object.values(GROUP_TITLE_PREFIX);

/**
 * 前端归一单一事实源：剥容器类型前缀取名字（2026-09-17 裁决对齐 flova：
 * 纯结构性，只认 Element_/Shot_/Audio_ 三个前缀，无词表翻译）；
 * 显示/引用匹配共用，后端 strip_type_prefix 同契约。
 */
export function stripTypePrefix(title: string): string {
  const t = String(title || '').trim();
  for (const p of TYPE_PREFIXES) {
    if (t.startsWith(p)) return t.slice(p.length);
  }
  return t;
}

/** 写口归一（2026-09-17 裁决）：幂等补容器类型前缀，名字原样（后端 normalize_group_title 同契约） */
export function canonicalGroupTitle(title: string, type: DraftType): string {
  const t = String(title || '').trim();
  const prefix = GROUP_TITLE_PREFIX[type] || '';
  if (!prefix || !t || t.startsWith(prefix)) return t;
  return prefix + t;
}

/**
 * 元素标题的**括注主名**（别名形态）：取首个 `（`/`(` 之前的部分。
 * 返回 '' = 无括注，或主名过短（< 2 字符）——两种情况都不产出别名候选。
 *
 * 2026-09-26：模型把别名/关键特征写进组名括注（`艾AA（AA）`、`曹彬（老年）`、
 * `星环号球形舱（木星轨道）`），而正文/提示词写的是括注前的主名（`艾AA`）——
 * 候选名此前只有「完整标题 + 剥容器前缀」两形态，逐字子串比对 ⇒ 恒不命中，
 * 正文里的元素名渲染不出内联块、提示词里的 `<<<image_艾AA>>>` 也解析不到图。
 * （后端 `storyboard_ops.element_alias_name` 同契约镜像。）
 */
export function elementAliasName(title: string): string {
  const bare = stripTypePrefix(title);
  const parts = bare.split(/[（(]/, 2);
  if (parts.length < 2) return '';   // 无括注：不产别名（避免与「剥前缀」形态重复）
  const main = parts[0].trim();
  return main.length >= 2 ? main : '';
}

/**
 * 元素标题的**全部引用形态**（引用匹配候选名的唯一入口，去重保序）：
 * ① 完整标题 → ② 剥容器前缀 → ③ 括注主名。
 * 与后端 `storyboard_ops.element_name_variants` **同契约镜像**（P1 单一事实源）。
 */
export function elementNameVariants(title: string): string[] {
  const out: string[] = [];
  const full = String(title || '').trim();
  if (full) out.push(full);
  const bare = stripTypePrefix(full);
  if (bare && !out.includes(bare)) out.push(bare);
  const alias = elementAliasName(full);
  if (alias && !out.includes(alias)) out.push(alias);
  return out;
}
