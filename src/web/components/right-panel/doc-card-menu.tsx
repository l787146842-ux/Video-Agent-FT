/**
 * doc-card-menu.tsx — 文档完成卡与右键菜单入口（自 ChatMessageItem 拆分，
 * 前端物理行数 250 红线收敛）。
 *
 * 卡片本体是 <button>，内嵌图标按钮非法，故钉住入口走项目右键菜单惯例
 * （同 MediaViewer 替换菜单）。
 */
import { FiBookmark, FiChevronRight, FiFileText } from 'solid-icons/fi';
import { openDocsPanel } from '@/stores/docs';
import { togglePinArtifact } from '@/stores/pinned';
import { showContextMenu } from '@/components/shared/ContextMenu';
import { t } from '@/lib/locale';

/** 文档卡右键菜单项：打开文档面板 / 钉住到对照栏 */
export const docCardMenu = (doc: string) => ([
  { label: '打开文档面板', icon: FiFileText, onClick: () => openDocsPanel(doc) },
  { label: '钉住到对照栏', icon: FiBookmark, onClick: () => togglePinArtifact({ kind: 'doc', name: doc }) },
]);

/** 文档完成卡：点击打开文档面板；右键出菜单（含钉住入口） */
export function DocCard(props: { doc: string }) {
  return (
    <button
      type="button"
      class="doc-card"
      onClick={() => openDocsPanel(props.doc)}
      onContextMenu={(e) => showContextMenu(e, docCardMenu(props.doc))}
    >
      <FiFileText size={15} class="doc-card-icon" />
      <span class="doc-card-name">{props.doc}</span>
      <span class="doc-card-status">{t('rp.msg.docDone')}</span>
      <FiChevronRight size={12} class="doc-card-arrow" />
    </button>
  );
}
