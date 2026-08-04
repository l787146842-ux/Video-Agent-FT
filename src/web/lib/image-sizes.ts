/**
 * 图片比例 → 尺寸映射（从旧 api/config.ts 迁移）
 */

const STUDIO_IMAGE_1K_SIZES: Record<string, string> = {
  '1:1': '1024x1024',
  '2:3': '1024x1536',
  '3:2': '1536x1024',
  '3:4': '1008x1344',
  '4:3': '1344x1008',
  '9:16': '720x1280',
  '16:9': '1280x720',
  '21:9': '1280x544',
  '9:21': '544x1280',
};

/** 分辨率档位 → 尺寸倍率（1K=基准，2K=2 倍，4K=4 倍，与后端 image_size_for 一致） */
const RESOLUTION_MULTIPLIERS: Record<string, number> = { '1K': 1, '2K': 2, '4K': 4 };

/** 把 "1280x720" 按倍率放大（保持 16 对齐特性，因为倍率为整数） */
function scaleSize(size: string, mult: number): string {
  if (mult <= 1) return size;
  const [w, h] = size.split('x').map(Number);
  if (!(w > 0) || !(h > 0)) return size;
  return `${w * mult}x${h * mult}`;
}

/**
 * 比例转尺寸字符串；custom 时按宽:高计算（长边 1536，像素上限 ~150 万）。
 * resolution：分辨率档位（1K/2K/4K），按比例放大基准尺寸。
 */
export function studioImageSizeForRatio(
  ratio: string,
  customWidth = '',
  customHeight = '',
  resolution = '1K',
): string {
  const mult = RESOLUTION_MULTIPLIERS[(resolution || '1K').toUpperCase()] ?? 1;
  if (ratio !== 'custom') {
    return scaleSize(STUDIO_IMAGE_1K_SIZES[ratio] || STUDIO_IMAGE_1K_SIZES['1:1'], mult);
  }
  const widthRatio = Number(customWidth);
  const heightRatio = Number(customHeight);
  if (!(widthRatio > 0) || !(heightRatio > 0)) return '';
  const parsedRatio = widthRatio / heightRatio;
  const longSide = 1536 * mult;
  const pixelLimit = 1572864 * mult * mult;
  const rawWidth = parsedRatio >= 1
    ? longSide
    : Math.min(longSide * parsedRatio, Math.sqrt(pixelLimit * parsedRatio));
  const rawHeight = parsedRatio >= 1
    ? Math.min(longSide / parsedRatio, Math.sqrt(pixelLimit / parsedRatio))
    : longSide;
  const width = Math.max(64, Math.floor(rawWidth / 16) * 16);
  const height = Math.max(64, Math.floor(rawHeight / 16) * 16);
  return `${width}x${height}`;
}
