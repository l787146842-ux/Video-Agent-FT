/**
 * 钉住 store 测试（F3 Artifact 钉住侧栏）。
 *
 * 钉死：kind 判别联合的 id 派生、pin/unpin/toggle API、上限 3 满额拒绝、
 * 重复钉仅激活、取消激活项后激活权移交、clearAllPinned 归零。
 */
import { describe, expect, it, beforeEach } from 'vitest';
import {
  pinned, activeId, pinArtifact, unpinArtifact, togglePinArtifact,
  isPinnedId, pinnedIdOf, setActivePinned, clearAllPinned, PINNED_MAX,
} from '../pinned';

const img = (n: number) => ({ kind: 'image' as const, url: `/a/img${n}.png`, name: `img${n}.png` });
const vid = (n: number) => ({ kind: 'video' as const, url: `/a/v${n}.mp4`, name: `v${n}.mp4` });
const doc = (name: string) => ({ kind: 'doc' as const, name });

describe('pinned store — 钉住侧栏', () => {
  beforeEach(() => clearAllPinned());

  it('pinnedIdOf：kind + 主键派生稳定 id', () => {
    expect(pinnedIdOf(img(1))).toBe('image:/a/img1.png');
    expect(pinnedIdOf(vid(1))).toBe('video:/a/v1.mp4');
    expect(pinnedIdOf(doc('剧本.md'))).toBe('doc:剧本.md');
  });

  it('pinArtifact 追加并激活新项', () => {
    expect(pinArtifact(img(1))).toBe(true);
    expect(pinned()).toHaveLength(1);
    expect(pinned()[0].kind).toBe('image');
    expect(activeId()).toBe('image:/a/img1.png');
  });

  it('重复钉同项：不新增，仅激活并返回 true', () => {
    pinArtifact(img(1));
    pinArtifact(vid(1));
    setActivePinned('');
    expect(pinArtifact(img(1))).toBe(true);
    expect(pinned()).toHaveLength(2);
    expect(activeId()).toBe('image:/a/img1.png');
  });

  it(`上限 ${PINNED_MAX}：满额再钉返回 false 且不新增`, () => {
    pinArtifact(img(1));
    pinArtifact(vid(1));
    pinArtifact(doc('剧本.md'));
    expect(pinned()).toHaveLength(PINNED_MAX);
    expect(pinArtifact(img(9))).toBe(false);
    expect(pinned()).toHaveLength(PINNED_MAX);
    expect(activeId()).toBe('doc:剧本.md'); // 拒绝不改变激活项
  });

  it('三种 kind 并存且各自保留元数据（doc 仅持名）', () => {
    pinArtifact(img(1));
    pinArtifact({ ...vid(1), thumb: '/a/v1.jpg' });
    pinArtifact(doc('分镜.md'));
    const [i, v, d] = pinned();
    expect(i.kind).toBe('image');
    expect(v.kind === 'video' && v.thumb).toBe('/a/v1.jpg');
    expect(d.kind === 'doc' && d.name).toBe('分镜.md');
    expect('url' in d).toBe(false);
  });

  it('unpinArtifact：移除成功返回 true；不存在返回 false', () => {
    pinArtifact(img(1));
    expect(unpinArtifact('image:/a/img1.png')).toBe(true);
    expect(pinned()).toHaveLength(0);
    expect(unpinArtifact('image:/a/img1.png')).toBe(false);
  });

  it('取消激活项：激活权移交给剩余最后一项；清空后归空', () => {
    pinArtifact(img(1));
    pinArtifact(vid(1));
    pinArtifact(doc('a.md'));
    unpinArtifact('doc:a.md'); // 激活项被移除
    expect(activeId()).toBe('video:/a/v1.mp4');
    unpinArtifact('video:/a/v1.mp4');
    expect(activeId()).toBe('image:/a/img1.png');
    unpinArtifact('image:/a/img1.png');
    expect(activeId()).toBe('');
  });

  it('togglePinArtifact：未钉→钉；已钉→取消', () => {
    togglePinArtifact(img(1));
    expect(isPinnedId('image:/a/img1.png')).toBe(true);
    togglePinArtifact(img(1));
    expect(isPinnedId('image:/a/img1.png')).toBe(false);
    expect(pinned()).toHaveLength(0);
  });

  it('clearAllPinned：列表与激活一并归零', () => {
    pinArtifact(img(1));
    pinArtifact(vid(1));
    clearAllPinned();
    expect(pinned()).toHaveLength(0);
    expect(activeId()).toBe('');
  });
});
