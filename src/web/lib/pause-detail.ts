/**
 * 暂停卡辅助说明（dsh `detail`）的折叠判定与摘要——唯一实现。
 *
 * 2026-10-09（事故 6666，用户裁决「改成折叠展示」）：
 * 病灶 = 模型按既有契约（`WorkflowPauseInput.detail`：「确认批次产出时，把被确认
 * 的对象逐条列在这里」）把 9 张待生成卡逐条列出，正文 645 字 / 10 个换行 ⇒
 * 卡面标题下顶着一大段清单，把选项区挤到视野外。契约本身是 4444/P2-1 的裁决
 * （不能只报总数），故**不改契约、只改呈现**：内容一条不少，默认收起。
 *
 * 判定口径（确定性，无创作空间）：**短说明保持内联**——一行的说明再套一层
 * 折叠只是白白多一次点击，且会退化既有体验基线（§3.1）；**多行长说明折叠**
 * （含换行即视为清单/多段）。两个条件都客观可判，纯函数可单测。
 * 不做「按条数计」之类需要解析语义的判定（那是猜，不是判）。
 */

/** 单行说明的内联上限：超过即视为「一大堆」，与换行同档折叠（防止无换行的长墙） */
export const PAUSE_DETAIL_MAX_INLINE = 160;

/** 该说明是否折叠展示（折叠 = 默认只显示首行摘要，点击展开全文）。 */
export function shouldCollapseDetail(text: string): boolean {
  const body = (text || '').trim();
  if (!body) return false;
  return body.includes('\n') || body.length > PAUSE_DETAIL_MAX_INLINE;
}

/** 折叠态摘要 = 首行（说明的首行恒为「本次要确认什么」的概括句）。 */
export function detailSummary(text: string): string {
  const body = (text || '').trim();
  if (!body) return '';
  const first = body.split('\n')[0].trim();
  return first || body;
}

/** 折叠提示的规模计数 = **非空行数**（含首行概述，与「共 N 行」措辞同口径）。
 *  不数「清单条目」——那要解析编号语义（是猜不是判）。 */
export function detailLineCount(text: string): number {
  return (text || '').split('\n').filter((l) => l.trim()).length;
}
