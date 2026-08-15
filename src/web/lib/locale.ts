/**
 * 轻量 i18n（计划书 P2-4）：UI 文案抽取到 locale 字典，zh-CN 为默认语言。
 *
 * 约定：
 * - key 以面板前缀分组（rp.* = right-panel，第一期；后续 mp.* / lp.* / layout.*）
 * - 占位符用 {name} 形式，经 t(key, vars) 插值
 * - 查找顺序：当前语言 → zh-CN 回退 → key 本身（缺失可见，便于排查）
 * - 后端返回的动态文案（错误 detail、模型回复等）不走此字典
 */
export type LocaleId = 'zh-CN' | 'en';

const zhCN: Record<string, string> = {
  // ---------- RightPanel / ChatFeed / 流式指示 ----------
  'rp.header.busy': 'Agent 工作中',
  'rp.header.idle': 'Agent 空闲',
  'rp.header.resizeHint': '拖动调整输入框高度',
  'rp.feed.empty': '和 Agent 聊聊，让它帮你规划故事板',
  'rp.feed.hint': '我能把创意/剧本拆解成关键元素、分镜与音频，并逐步规划生成——告诉我你的创意目标即可',
  'rp.streaming.thinking': '正在思考…',
  'rp.streaming.connecting': '正在连接…',
  'rp.streaming.reasoning': '深度思考中…',
  'rp.streaming.replying': '正在回复…',
  'rp.streaming.restoring': '正在恢复 Agent 进度…',
  'rp.streaming.processing': '正在处理…',
  'rp.conv.close': '关闭对话',
  'rp.conv.create': '新建对话',
  'rp.conv.branch': '分支当前对话（快照并派生新对话）',
  'rp.conv.busyGuard': 'Agent 正在回复，请稍后再操作对话窗口',

  // ---------- 输入区 ----------
  'rp.input.aria': '给 Agent 发送指令',
  'rp.input.placeholder': '给 Agent 发送指令（如：调整场景1氛围、帮我拆分分镜、生成下个动作...）',
  'rp.input.added': '已放入输入框：{name}',
  'rp.toolbar.upload': '上传参考素材或文档',
  'rp.toolbar.providerTitle': 'API 平台选择',
  'rp.toolbar.modelTitle': 'Agent 模型选择',
  'rp.toolbar.skill': '技能',
  'rp.toolbar.assets': '素材库',
  'rp.toolbar.assetsTitle': '素材库：从故事板/未归类素材中选取媒体发送到对话框',
  'rp.toolbar.skillDoc': '查看/编辑当前 Skill 流程文档',
  'rp.toolbar.send': '发送',
  'rp.toolbar.stop': '停止生成',
  'rp.toolbar.contextUsage': '上下文用量',
  'rp.toolbar.contextTip': '{usage}K 上下文已使用',
  'rp.toolbar.contextLoading': '统计中…',
  'rp.pill.unselected': '未选择',
  'rp.pill.empty': '暂无可用选项',
  'rp.pill.model': '模型',
  'rp.pill.thinking': '推理等级',
  'rp.pill.noModel': '未配置模型',
  'rp.attachment.remove': '移除',
  'rp.mention.aria': '画布图片选择',
  'rp.mention.loading': '加载画布图片中...',
  'rp.mention.offline': '画布未连接，画布图片引用不可用（故事板素材仍可 @ 引用）',
  'rp.mention.none': '画布内暂无图片',
  'rp.mention.noMatch': '无匹配图片',
  'rp.lightbox.alt': '原图预览',
  'rp.lightbox.download': '下载',
  'rp.lightbox.close': '关闭 (Esc)',

  // ---------- Skill 选择 / 详情 / 导入 ----------
  'rp.skill.title': '技能加载',
  'rp.skill.inserted': 'Skill「{name}」已插入输入框，发送后生效并写入文档',
  'rp.skill.deleted': 'Skill「{name}」已删除',
  'rp.skill.deleteFailed': '删除失败：{error}',
  'rp.skill.preview': '预览 Skill 详情',
  'rp.skill.insertTip': '插入 Skill 到输入框，发送后生效',
  'rp.skill.delete': '删除 Skill',
  'rp.skill.confirmDelete': '删除「{name}」？',
  'rp.skill.confirm': '确定',
  'rp.skill.cancel': '取消',
  'rp.skill.none': '暂无可用 Skill',
  'rp.skill.noneOption': '不使用技能',
  'rp.skill.noneOptionHint': '不激活任何 Skill，自由对话模式',
  'rp.skill.import': '导入 Skill',
  'rp.skillDetail.noIntro': '暂无简介',
  'rp.skillDetail.introEmpty': '简介不能为空',
  'rp.skillDetail.introSaved': '简介已保存',
  'rp.skillDetail.saveFailed': '保存失败：{error}',
  'rp.skillDetail.tabIntro': '简介',
  'rp.skillDetail.tabContent': '内容',
  'rp.skillDetail.saveIntro': '保存简介',
  'rp.skillDetail.renderPreview': '渲染预览',
  'rp.skillDetail.source': '源码',
  'rp.skillDetail.noContent': '暂无内容',
  'rp.skillDetail.copy': '复制全文',
  'rp.skillDetail.copied': 'Skill 内容已复制到剪贴板',
  'rp.skillDetail.copyFailed': '复制失败，请手动选择文本复制',
  'rp.skillDetail.use': '去使用 Skill',
  'rp.skillImport.title': '导入 Skill',
  'rp.skillImport.slugInvalid': '请填写有效的 Skill 标识（中文/英文/数字/连字符）',
  'rp.skillImport.contentEmpty': '内容不能为空',
  'rp.skillImport.imported': 'Skill「{name}」已导入',
  'rp.skillImport.upload': '上传文件',
  'rp.skillImport.slugLabel': 'Skill 标识（文件名）',
  'rp.skillImport.slugPlaceholder': '如 my-skill（英文/数字/连字符）',
  'rp.skillImport.contentLabel': 'Skill 内容（Markdown）',
  'rp.skillImport.contentPlaceholder': '粘贴 Skill 内容，或上传 .md 文件。\n\n标准格式：\n# Skill 名称\n> 调用规则：一句话说明\n## 流程规划\n...',
  'rp.skillImport.save': '保存 Skill',

  // ---------- 消息卡片 ----------
  'rp.msg.docDone': '已完成',
  'rp.msg.imageResult': '生图结果',
  'rp.msg.imageTip': '{name} — 点击查看原图，按住拖动到画布',
  'rp.msg.download': '下载',
  'rp.msg.lightboxAlt': '原图预览',
  'rp.msg.downloadOriginal': '下载原图',
  'rp.msg.closeEsc': '关闭 (Esc)',
  'rp.msg.stageDone': '阶段完成',
  'rp.msg.appliedOps': '已执行 {count} 个操作',
  'rp.msg.stopped': '已停止',
  'rp.msg.emptyReply': '（空回复）',
  'rp.msg.memoryRefs': '记忆参考 {count} 条',
  'rp.msg.mediaInserted': 'Agent 已添加 {count} 个素材到对话输入框，确认后可发送',
  'rp.msg.gatePlatform': '平台',
  'rp.msg.gateSkill': 'Skill『{name}』',

  // ---------- 过程时间线（深度思考 + 已处理操作） ----------
  'rp.timeline.thinking': '深度思考',
  'rp.timeline.processing': '正在处理…（已完成 {count} 项）',
  'rp.timeline.processed': '已处理 {count} 个操作',
  'rp.msg.confirmContinue': '确认，继续',
  'rp.msg.confirmText': '确认',
  'rp.msg.adjust': '我要调整',
  'rp.msg.gateOverride': '本次放行（仅本次生效）',

  // ---------- 确认向导（814F6 i18n 补齐） ----------
  'rp.confirm.customBtn': '其它（自定义输入）',
  'rp.confirm.customPlaceholder': '输入你的想法，发送后作为本组的选择…',
  'rp.confirm.send': '发送',
  'rp.confirm.next': '下一步',
  'rp.confirm.hintCustom': '将发送自定义内容',
  'rp.confirm.hintPick': '选择后点击发送',
  'rp.confirm.pickProvider': '请选择 API 厂商…',

  // ---------- 排队引导消息（推理中继续发送） ----------
  'rp.queue.title': '排队中的引导消息（Agent 完成后自动发送）',
  'rp.queue.guide': '引导',
  'rp.queue.guideTitle': '停止当前推理，优先用这条消息引导下一步',
  'rp.queue.delete': '删除',
  'rp.queue.more': '更多操作',
  'rp.queue.edit': '编辑消息',
  'rp.queue.openSide': '在侧边聊天中打开',
  'rp.queue.closeQueue': '关闭排队',
  'rp.queue.closeQueueTitle': '清空全部排队消息',
  'rp.queue.openSideBusy': 'Agent 忙碌中，无法新建对话，消息已保留在排队',
  'rp.queue.guideConfirmTitle': '中断当前任务？',
  'rp.queue.guideConfirmMessage': '点「引导」会立即停止 Agent 正在执行的任务，并优先发送这条消息：{text}',
  'rp.queue.guideConfirmOk': '停止并引导',
  'rp.queue.guideSpinner': '排队中，当前推理停止后优先发送',
  'rp.queue.enqueued': '已加入排队，Agent 完成当前任务后自动发送（可点「引导」立即接管）',
  'rp.queue.cleared': '已清空排队消息',
  'rp.task.done': '后台 Agent 任务已完成',
  'rp.send.noProvider': '请先选择 Agent API 和对应模型',
  'rp.skill.manifestHint': '高级声明（skill_manifest，系统自动维护，无需编辑）',

  // ---------- 素材库（画布资产弹窗） ----------
  'rp.asset.tabImage': '图片资产',
  'rp.asset.tabCanvas': '画布资产',
  'rp.asset.tabLocal': '本地素材',
  'rp.asset.openCanvasTitle': '在画布中打开',
  'rp.asset.canvasJump': '画布',
  'rp.asset.close': '关闭',
  'rp.asset.canvasSpace': '画布操作空间',
  'rp.asset.selectCanvas': '选择画布…',
  'rp.asset.kindSmart': '智能画布',
  'rp.asset.kindNormal': '普通画布',
  'rp.asset.noCanvas': '暂无画布',
  'rp.asset.noCanvasHint': '请先在画布中创建一个画布',
  'rp.asset.noCanvasImages': '该画布中暂无图片',
  'rp.asset.canvasImagesHint': '在画布上生成的素材会出现在这里',
  'rp.asset.loading': '加载中...',
  'rp.asset.canvasOffline': '画布未连接，画布素材功能受限',
  'rp.asset.canvasOfflineHint': '请检查画布服务是否启动；故事板/未归类素材仍可用',
  'rp.asset.offlineLimited': '画布未连接，功能受限（{error}）',
  'rp.asset.connectionFailed': '连接失败',
  'rp.asset.checkOriginPre': '检查 ',
  'rp.asset.checkOriginPost': ' 是否启动',
  'rp.asset.reconnect': '重连画布',
  'rp.asset.loadFailed': '加载失败：{error}',
  'rp.asset.emptyOf': '暂无{label}',
  'rp.asset.emptyImageHint': '在画布画布"素材库"里添加图片资产',
  'rp.asset.emptyLocalHint': '点击底部"添加"上传本地素材',
  'rp.asset.select': '选中',
  'rp.asset.unselect': '取消选中',
  'rp.asset.cardToggle': '{name} — 点击{action}',
  'rp.asset.selected': '已选 {count} 个',
  'rp.asset.addToChat': '添加到对话框',

  // ---------- 素材库（故事板选择弹窗） ----------
  'rp.picker.tabKeyElement': '关键元素',
  'rp.picker.tabShot': '分镜',
  'rp.picker.tabAudio': '音频',
  'rp.picker.tabUncat': '未归类素材',
  'rp.picker.openCanvasLibrary': '打开画布素材库',
  'rp.picker.canvasAssets': '画布素材',
  'rp.picker.addedToChat': '已将 {count} 个素材添加到对话',
  'rp.picker.emptyOf': '暂无{label}媒体素材',
  'rp.picker.uncatHint': '从故事板移除的素材会出现在这里',
  'rp.picker.boardHint': '故事板草稿生成/上传媒体后会出现在这里',
};

/** 语言包注册表：en 待第三期后补齐，当前回退 zh-CN */
const dictionaries: Record<LocaleId, Record<string, string>> = {
  'zh-CN': zhCN,
  en: {},
};

let currentLocale: LocaleId = 'zh-CN';

export function setLocale(locale: LocaleId): void {
  currentLocale = locale;
}

export function getLocale(): LocaleId {
  return currentLocale;
}

/**
 * 取文案：当前语言 → zh-CN 回退 → key 本身。
 * vars 提供 {占位符} 插值，如 t('rp.input.added', { name: '图A' })。
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  let text = dictionaries[currentLocale][key] ?? zhCN[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}
