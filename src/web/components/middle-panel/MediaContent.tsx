import { Switch, Match } from 'solid-js';
import type { Draft } from '@/types';

/** 预览媒体内容：按媒体类型切换 视频 / 音频 / 图片（默认） */
export function MediaContent(props: { draft: Draft; url: string; onImageClick?: () => void }) {
  return (
    <div class="preview-media-viewer">
      <Switch fallback={
        <img
          src={props.url}
          alt={props.draft.label}
          class="preview-img-clickable"
          onClick={props.onImageClick}
          title="点击放大查看"
        />
      }>
        <Match when={props.draft.mediaType === 'video'}>
          {/* preload=metadata：切卡片时只加载首帧/元数据，避免每次点卡片
              都后台全量下载视频（大文件时会明显卡顿）；点击播放时照常加载 */}
          <video src={props.url} controls preload="metadata" />
        </Match>
        <Match when={props.draft.mediaType === 'audio'}>
          <div class="preview-audio-wrap">
            <p class="preview-audio-name">{props.draft.label}</p>
            <audio src={props.url} controls />
          </div>
        </Match>
      </Switch>
    </div>
  );
}
