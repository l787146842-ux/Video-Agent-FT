/**
 * 提示词 @引用解析（前端版，与后端 prompt_refs.py 规则对齐）
 *
 * 生成（出图/出视频）时把提示词里的 @名称 映射为实际媒体素材：
 * 1. 从故事板构建 名称 → {url, kind} 映射（关键元素分组标题 / 草稿 label / 文件名）；
 * 2. @名称 命中的素材若不在参考列表且未满上限则自动纳入；
 * 3. @名称 重写为位置标记（如 [参考图2：Element_月球]），
 *    让多模态模型精确知道第 N 张参考图对应提示词中的哪个元素。
 *
 * 2026-09-23 批3（Q4/Q6）：与后端同批修三条根因 + 补方言识别——
 *   R1 方括号：原 `[^\s@＠]+` 会把 `@[程心]` 的方括号吞进名字 → 现排除 `[ ]` 并容许可选包络；
 *   R2 转义下划线：Skill 模板原文 `<<<image\_场景>>>`（反斜杠转义）此前**前端完全不认**该方言；
 *   R3 裸名：媒体映射补登分组标题的剥前缀裸名（模型实际写法）。
 */
import { state } from '@/stores/studio';
import { elementNameVariants, stripTypePrefix } from '@/lib/group-title';
import type { AnyGroup, MediaType } from '@/types';

// 标题前缀归一 + 元素名形态下沉叶子模块（2026-09-26）；re-export 保持既有导入路径。
export { stripTypePrefix };

/**
 * 引用记号（与后端 _MENTION_RE 对齐，两式同义）：
 * 1) `<<<image_名称>>>`（Skill 模板方言；容许 `image\_名称` 的 Markdown 转义形态）；
 * 2) `@名称` / `＠名称`，容许可选的 `[ ]` 包络（`@[程心]` 与 `@程心` 等价）。
 */
const MENTION_RE = /<<<\s*image\\?_([^<>]+?)\s*>>>|[@＠]\[?([^\s@＠[\]]+)\]?/g;

/**
 * 从提示词里解析 `@名称` / `<<<image_名称>>>`，交给 `resolve` 决定替换文本。
 *
 * 2026-10-19 音色引用批（用户裁决「参考栏要能看见音频」）：
 * `@` 式走**最长前缀回退**（与后端 `_match_longest_name` 同口径），
 * 名称捕获不再吞后面的中文标点。病灶（9999 实测）：提示词
 * `@音色·程心、@音色·曹彬 的音色参考` 被 `MENTION_RE` 捕获成
 * `'音色·程心、'`（顿号进了名字）⇒ 查表落空 ⇒ **参考栏音频计数恒 0**
 * 且该条音频不计入。后端早已按「最长前缀回退」处理，前端没跟上（P1 同契缺口）。
 */
function replaceMentions(
  text: string,
  map: Record<string, { url: string; kind: MediaType }>,
  resolve: (name: string, info: { url: string; kind: MediaType }, original: string) => string,
): string {
  if (!text) return '';
  const re = new RegExp(MENTION_RE.source, 'g');
  return text.replace(re, (whole, g1: string, g2: string) => {
    // `<<<image_名称>>>` 有闭合定界符，名称天然无歧义，原样查表
    if (g1 !== undefined && g1 !== null) {
      const name = String(g1 || '').trim();
      const info = map[name];
      return info ? resolve(name, info, whole) : name;
    }
    const raw = String(g2 || '').trim();
    // 最长前缀回退：`@音色·程心、` → 命中 `音色·程心`，尾部顿号原样保留
    for (let i = raw.length; i > 0; i -= 1) {
      const cand = raw.slice(0, i);
      const info = map[cand];
      if (info) return resolve(cand, info, whole) + raw.slice(i);
    }
    return raw;
  });
}

/** 提取提示词里的全部引用名（与 `MENTION_RE` 同一事实源）。
 *
 * 2026-09-26：供**计数徽章**等只读消费方复用——此前 `RefAssetBar` 手抄了
 * 第三份正则且不剥方括号，`@[程心]` 查表落空、计数恒 0。
 * 返回 [名称, 原始记号] 对，调用方按需取用。
 *
 * 2026-10-19：名称解析与 `resolvePromptForGeneration` 共用 `replaceMentions`
 * 的**最长前缀回退**（此前这里直接切正则捕获组，`@音色·程心、` 会把顿号
 * 一起带出来 ⇒ 查表落空 ⇒ 音频计数恒 0，与提示词框里已渲染的 chip 自相矛盾）。
 */
export function* mentionNamesIn(
  text: string,
  map: Record<string, { url: string; kind: MediaType }> = storyboardMediaMap(),
): Generator<[string, string]> {
  if (!text) return;
  const out: Array<[string, string]> = [];
  replaceMentions(text, map, (name, _info, original) => {
    out.push([name, original]);
    return original;
  });
  for (const pair of out) yield pair;
}
const KIND_LABEL: Record<MediaType, string> = {
  image: '参考图', video: '参考视频', audio: '参考音频',
};

export interface MediaRef {
  url: string;
  kind: MediaType;
}

function fileNameOf(url: string): string {
  const clean = url.split('?')[0].split('#')[0];
  return clean.split('/').pop() || '';
}

/** 该关键元素组的草稿里是否存在**视觉卡**（图像/视频）——按 mediaType 判定，
 *  **不看是否已出图**（2026-10-16 音色抢名批，与后端
 *  `prompt_refs._group_has_visual_card` 同口径）。
 *  判「卡种类」而非「有无 URL」：否则「组内只有音色卡」与「设定图未出图」
 *  在 URL 面上无法区分，图未生成期间会把组标题让给音频、原故障按时间窗复发。 */
function draftsHaveVisualCard(drafts: Array<{ mediaType?: string }>): boolean {
  return (drafts || []).some((d) =>
    d.mediaType === 'image' || d.mediaType === 'video');
}

/** 构建故事板 名称 → {url, kind} 映射（命名规则与 PromptEditor / 后端对齐）
 *
 *  2026-10-16 音色抢名批：**音色卡不得抢占关键元素组标题**——组标题登记分两遍：
 *  ① 视觉卡（image/video）无条件登记组标题；② 仅当该组没有任何视觉卡时，
 *  才允许音频兜底登记一次（防「只有音色卡」的组静默降级为纯文字）。
 *  与后端 `build_storyboard_media_map` 同契约（P1 单一事实源）。
 */
export function storyboardMediaMap(): Record<string, MediaRef> {
  const map: Record<string, MediaRef> = {};
  const put = (name: string, url: string, kind: MediaType) => {
    const n = (name || '').trim();
    if (!n || !url || map[n]) return;
    map[n] = { url, kind };
  };
  const putTitleAliases = (g: AnyGroup, url: string, kind: MediaType) => {
    // 形态集与后端 `prompt_refs.build_storyboard_media_map` 同契约：
    // 全称 + 剥前缀 + **括注主名**（`<<<image_艾AA>>>` 也要能命中）。
    elementNameVariants(g.title || '').forEach((v) => put(v, url, kind));
  };
  const boards: Array<{ groups: AnyGroup[]; isKeyElement: boolean }> = [
    { groups: state.keyElements, isKeyElement: true },
    { groups: state.shots, isKeyElement: false },
    { groups: state.audioItems, isKeyElement: false },
  ];
  for (const { groups, isKeyElement } of boards) {
    for (const g of groups) {
      const titleReserved = isKeyElement && draftsHaveVisualCard(g.drafts || []);
      let audioFallbackDone = false;
      for (const d of g.drafts || []) {
        const entries: Array<[string | undefined, MediaType]> = [
          [d.imgUrl, 'image'], [d.videoUrl, 'video'], [d.audioUrl, 'audio'],
        ];
        for (const [url, kind] of entries) {
          if (!url) continue;
          if (isKeyElement) {
            if (kind === 'audio') {
              // 音频：组标题只在「纯音色卡组」兜底登记一次
              if (!titleReserved && !audioFallbackDone) {
                putTitleAliases(g, url, kind);
                audioFallbackDone = true;
              }
            } else {
              putTitleAliases(g, url, kind);
            }
          }
          put(d.label || '', url, kind);
          put(fileNameOf(url), url, kind);
        }
      }
    }
  }
  return map;
}

/** 故事板媒体分类列表（@面板上区分：关键元素/分镜/音频） */
export interface BoardMediaItem {
  url: string;
  name: string;
  kind: MediaType;
  category: 'keyElement' | 'shot' | 'audio';
}

export function storyboardMediaList(): BoardMediaItem[] {
  const out: BoardMediaItem[] = [];
  const seen = new Set<string>();
  const push = (name: string, url: string, kind: MediaType, category: BoardMediaItem['category']) => {
    const n = (name || '').trim();
    const key = `${url}|${n}`;
    if (!n || !url || seen.has(key)) return;
    seen.add(key);
    out.push({ url, name: n, kind, category });
  };
  const walk = (groups: AnyGroup[], category: BoardMediaItem['category']) => {
    for (const g of groups) {
      // 2026-10-16 音色抢名批：@面板的显示名同样不得让音色卡借走组标题
      // （与 storyboardMediaMap 同一规则，P1 单一事实源）。视觉卡存在时，
      // 音频条目退回自身 label（如「音色·程心」）作显示名。
      const titleReserved = category === 'keyElement'
        && draftsHaveVisualCard(g.drafts || []);
      for (const d of g.drafts || []) {
        const isAudio = d.mediaType === 'audio';
        const audioName = d.label || g.title;
        const prefer = isAudio && titleReserved
          ? audioName
          : (category === 'keyElement' ? g.title : (d.label || g.title));
        if (d.imgUrl) push(prefer, d.imgUrl, 'image', category);
        if (d.videoUrl) push(prefer, d.videoUrl, 'video', category);
        if (d.audioUrl) push(prefer, d.audioUrl, 'audio', category);
      }
    }
  };
  walk(state.keyElements, 'keyElement');
  walk(state.shots, 'shot');
  walk(state.audioItems, 'audio');
  return out;
}

export interface ResolvedPrompt {
  /** 重写后的提示词（@名称 → [参考图N：名称]） */
  prompt: string;
  /** 最终随请求发送的参考素材 URL 列表（原 refAssets 优先，@命中的补足） */
  refs: string[];
  /** 与 refs 逐项对应的素材类型（图片/视频/音频），供生视频时拆分参考项 */
  refKinds: MediaType[];
}

const AUDIO_EXTS = ['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'];

/** 推断 URL 的素材类型：故事板映射优先，其次按音频扩展名兜底 */
function kindOfUrl(url: string, map: Record<string, MediaRef>): MediaType {
  for (const info of Object.values(map)) {
    if (info.url === url) return info.kind;
  }
  const clean = url.split('?')[0].split('#')[0].toLowerCase();
  return AUDIO_EXTS.some((ext) => clean.endsWith(ext)) ? 'audio' : 'image';
}

/**
 * 解析提示词中的 @提及。
 * @param prompt 原始提示词
 * @param baseRefs 草稿已有参考素材（refAssets），保持顺序
 * @param maxRefs 参考素材上限（出图 5 / 出视频 2）
 *
 * 2026-10-19 音色引用批：标记序号**按素材类型独立编号**（与后端
 * `prompt_refs.resolve_prompt_mentions` 同口径，P1 单一事实源）。
 * 病灶：`[参考音频5：音色·程心]` 用的是**总列表**序号，而发送时音频单独成桶
 * （`generation_submit` 的 out_audios）⇒ 收 1 条音频却被告知「第 5 条」。
 * 改为类型内序号后 `[参考音频1：…]` 与音频桶一致；图片侧口径不变。
 */
export function resolvePromptForGeneration(
  prompt: string,
  baseRefs: string[],
  maxRefs: number,
): ResolvedPrompt {
  const map = storyboardMediaMap();
  const refs: string[] = (baseRefs || []).filter(Boolean).slice(0, maxRefs);

  /** 类型内 0 基序号（该 URL 在同类型素材里第一次出现的位次） */
  const indexInKind = (url: string): number => {
    const want = kindOfUrl(url, map);
    const seen: string[] = [];
    for (const u of refs) {
      if (kindOfUrl(u, map) === want && !seen.includes(u)) seen.push(u);
    }
    return seen.indexOf(url);
  };

  const resolved = replaceMentions(prompt || '', map, (name, info) => {
    let idx = indexInKind(info.url);
    if (idx < 0) {
      if (refs.length >= maxRefs) return name; // 超限：无法随请求发送
      refs.push(info.url);
      idx = indexInKind(info.url);
    }
    return `[${KIND_LABEL[info.kind]}${idx + 1}：${name}]`;
  });

  return {
    prompt: resolved,
    refs,
    refKinds: refs.map((url) => kindOfUrl(url, map)),
  };
}
