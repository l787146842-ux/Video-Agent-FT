/**
 * 生成时参考素材上限（C3）
 *
 * 出视频对齐 Seedance 2.5 多模态参考能力：总共最多 50 个素材，
 * 其中图片 ≤30 / 视频 ≤10 / 音频 ≤10。出图参考上限 10（用户审定）。
 *
 * 参考素材栏本身的存储不再有上限（REF_BAR_CAPACITY 仅作工程兜底）；
 * 生成提交时按类型取前 N 个，超限部分 toast 明示"仅前 N 个生效"。
 */
export const VIDEO_GEN_LIMITS = {
  image: 30,
  video: 10,
  audio: 10,
  total: 50,
} as const;

/** 出图（关键元素概念图等）参考图上限 */
export const IMAGE_GEN_LIMIT = 10;

/** 参考栏存储容量（无上限语义，999 为工程兜底值） */
export const REF_BAR_CAPACITY = 999;
