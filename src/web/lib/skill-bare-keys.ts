/**
 * 裸键兼容域（C1c 裁决，导入期只读）：与后端
 * skill_runtime/frontmatter.py::_extract_bare_keys 同口径。
 * 裸键为导入期只读兼容格式（YAML 是唯一落盘格式），不写回落盘。
 */

/** 裸键行识别：仅认文档首行起连续的 skill_name:/skill_description: */
const BARE_KEY_RE = /^(skill_name|skill_description)\s*:\s*(.+?)\s*$/;

/** 提取文档头部连续的裸键行（首个非裸键行即停，值剥成对引号） */
export function extractBareKeys(lines: string[]): { name: string; description: string; consumed: number } {
  let name = '';
  let description = '';
  let consumed = 0;
  for (const raw of lines) {
    const m = BARE_KEY_RE.exec(raw.trim());
    if (!m) break;
    let val = m[2].trim();
    if (val.length >= 2 && val[0] === val[val.length - 1] && (val[0] === '"' || val[0] === "'")) {
      val = val.slice(1, -1);
    }
    if (m[1] === 'skill_name') name = val;
    else description = val;
    consumed++;
  }
  return { name, description, consumed };
}
