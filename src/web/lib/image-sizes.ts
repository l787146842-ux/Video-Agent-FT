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

/**
 * 比例转尺寸字符串；custom 时按宽:高计算（长边 1536，像素上限 ~150 万）
 */
export function studioImageSizeForRatio(
  ratio: string,
  customWidth = '',
  customHeight = '',
): string {
  if (ratio !== 'custom') return STUDIO_IMAGE_1K_SIZES[ratio] || STUDIO_IMAGE_1K_SIZES['1:1'];
  const widthRatio = Number(customWidth);
  const heightRatio = Number(customHeight);
  if (!(widthRatio > 0) || !(heightRatio > 0)) return '';
  const parsedRatio = widthRatio / heightRatio;
  const longSide = 1536;
  const pixelLimit = 1572864;
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
