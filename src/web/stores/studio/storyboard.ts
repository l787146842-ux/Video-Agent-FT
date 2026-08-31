/** Studio store · 故事板域薄聚合（Q14 裁决 2026-09-01 方案 A：god-store 三分后的原样重导出）。
 * 实现体三分：
 * - board-persist：持久化域（防抖整板保存链/版本冲突三向合并/卸载冲刷）；
 * - board-sync：服务端快照同步域（生成中/编辑中保护、本地新增保护集、项目纪元）；
 * - board-edit：本地编辑 actions（分组/草稿增删改排，编辑后防抖落盘）。
 * 状态树不动（数据本体仍在 studio-core 单一 createStore），本文件保持原导出
 * 签名与语义，调用方零改动。依赖方向单向：edit → persist/sync，persist → sync。 */
import { boardSyncActions } from './board-sync';
import { boardEditActions } from './board-edit';

export { getProjectSession } from './board-sync';
export { persistBoard } from './board-persist';
export { categoryForSubTab } from './board-edit';

/** 故事板动作面（同步域 + 本地编辑域合并，原单一对象签名不变） */
export const storyboardActions = {
  ...boardSyncActions,
  ...boardEditActions,
};
