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
 * 提取提示词里的全部引用名（与 `MENTION_RE` 同一事实源）。
 *
 * 2026-09-26：供**计数徽章**等只读消费方复用——此前 `RefAssetBar` 手抄了
 * 第三份正则且不剥方括号，`@[程心]` 查表落空、计数恒 0。
 * 返回 [名称, 原始记号] 对，调用方按需取用。
 */
export function* mentionNamesIn(text: string): Generator<[string, string]> {
  if (!text) return;
  const re = new RegExp(MENTION_RE.source, 'g');
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const name = (m[1] || m[2] || '').trim();
    if (name) yield [name, m[0]];
  }
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

/** 构建故事板 名称 → {url, kind} 映射（命名规则与 PromptEditor / 后端对齐） */
export function storyboardMediaMap(): Record<string, MediaRef> {
  const map: Record<string, MediaRef> = {};
  const put = (name: string, url: string, kind: MediaType) => {
    const n = (name || '').trim();
    if (!n || !url || map[n]) return;
    map[n] = { url, kind };
  };
  const boards: Array<{ groups: AnyGroup[]; isKeyElement: boolean }> = [
    { groups: state.keyElements, isKeyElement: true },
    { groups: state.shots, isKeyElement: false },
    { groups: state.audioItems, isKeyElement: false },
  ];
  for (const { groups, isKeyElement } of boards) {
    for (const g of groups) {
      for (const d of g.drafts || []) {
        const entries: Array<[string | undefined, MediaType]> = [
          [d.imgUrl, 'image'], [d.videoUrl, 'video'], [d.audioUrl, 'audio'],
        ];
        for (const [url, kind] of entries) {
          if (!url) continue;
          if (isKeyElement) {
            // 形态集与后端 `prompt_refs.build_storyboard_media_map` 同契约：
            // 全称 + 剥前缀 + **括注主名**（`<<<image_艾AA>>>` 也要能命中）。
            elementNameVariants(g.title || '').forEach((v) => put(v, url, kind));
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
      for (const d of g.drafts || []) {
        const prefer = category === 'keyElement' ? g.title : (d.label || g.title);
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
 */
export function resolvePromptForGeneration(
  prompt: string,
  baseRefs: string[],
  maxRefs: number,
): ResolvedPrompt {
  const map = storyboardMediaMap();
  const refs: string[] = (baseRefs || []).filter(Boolean).slice(0, maxRefs);

  const resolved = (prompt || '').replace(MENTION_RE, (_m, g1: string, g2: string) => {
    const name = (g1 || g2 || '').trim();
    const info = map[name];
    if (!info) return name; // 未命中：去掉记号，保留文字
    let idx = refs.indexOf(info.url);
    if (idx < 0) {
      if (refs.length >= maxRefs) return name; // 超限：无法随请求发送
      refs.push(info.url);
      idx = refs.length - 1;
    }
    return `[${KIND_LABEL[info.kind]}${idx + 1}：${name}]`;
  });

  return {
    prompt: resolved,
    refs,
    refKinds: refs.map((url) => kindOfUrl(url, map)),
  };
}
