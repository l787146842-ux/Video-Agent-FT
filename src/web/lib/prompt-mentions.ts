/**
 * 提示词 @引用解析（前端版，与后端 prompt_refs.py 规则对齐）
 *
 * 生成（出图/出视频）时把提示词里的 @名称 映射为实际媒体素材：
 * 1. 从故事板构建 名称 → {url, kind} 映射（关键元素分组标题 / 草稿 label / 文件名）；
 * 2. @名称 命中的素材若不在参考列表且未满上限则自动纳入；
 * 3. @名称 重写为位置标记（如 [参考图2：Element_月球]），
 *    让多模态模型精确知道第 N 张参考图对应提示词中的哪个元素。
 */
import { state } from '@/stores/studio';
import type { AnyGroup, MediaType } from '@/types';

const MENTION_RE = /[@＠]([^\s@＠]+)/g;
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
          if (isKeyElement) put(g.title, url, kind);
          put(d.label || '', url, kind);
          put(fileNameOf(url), url, kind);
        }
      }
    }
  }
  return map;
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

/** 推断 URL 的素材类型：故事板映射优先，其次按音频扩展名兑底 */
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

  const resolved = (prompt || '').replace(MENTION_RE, (_m, name: string) => {
    const info = map[name];
    if (!info) return name; // 未命中：去掉 @，保留文字
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
