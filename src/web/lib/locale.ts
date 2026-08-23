/* eslint-disable max-lines */ // i18n 字典集中管理，词条随功能自然增长（已登记 FRONTEND_WHITELIST）
/**
 * 轻量 i18n：UI 文案抽取到 locale 字典，zh-CN 为默认语言。
 *
 * 约定：
 * - key 以面板前缀分组（rp.* = right-panel，第一期；后续 mp.* / lp.* / layout.*）
 * - 占位符用 {name} 形式，经 t(key, vars) 插值
 * - key 编译期校验：字典为字面量键对象，t() 只接受 LocaleKey 联合类型，
 *   拼错的 key 在 tsc 阶段即报错；后端驱动的动态键走 tDynamic（运行时回退）
 * - 查找顺序：当前语言 → zh-CN 回退 → key 本身（缺失可见，便于排查）
 * - 后端返回的动态文案（错误 detail、模型回复等）不走此字典
 */
export type LocaleId = 'zh-CN' | 'en';

const zhCN = {
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
  'rp.streaming.reconnecting': '连接中断，正在自动重连（{attempt}/{max}）…',
  'rp.streaming.processing': '正在处理…',
  'rp.streaming.executing': '正在执行第 {n} 项操作：{summary}',

  // ---------- 后端 SSE status 事件固定文案（键与后端 status_event key 一致） ----------
  'agent.roundThinking': '第 {prev} 轮操作已完成，继续思考中（第 {step}/{max} 轮）…',
  'agent.badRetry': '第 {step} 轮输出异常，重试中…',
  'agent.flowGatePause': '越阶操作被流程门禁拦截，已强制暂停',
  'agent.opsDone': '已完成：{ops}',
  'agent.gateHeal': '系统闸机拦截了本轮 {count} 个流程操作，正在要求模型按流程修正…',
  'agent.modelFallback': '模型 {from} 繁忙/异常，已切换 {to} 重试…',
  'agent.mockRunning': 'mock 模式：本地规则生成…',
  // planner 队列级 status 文案（原硬编码中文，收编入字典）
  'agent.roundStart': '第 {step} 轮推理中…（执行上轮操作后继续规划）',
  'agent.planning': '正在推理…（模型正在读状态并规划操作）',
  'agent.actionsApplied': '已应用 {count} 个操作',
  // agent.executing 随 executing_actions 事件退役删除（见 ADR-0001）
  'rp.conv.close': '关闭对话',
  'rp.conv.create': '新建对话',
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
  // 弹层读屏标题（新增读屏文案统一走 t() 字典）
  'rp.lightbox.dialogAria': '媒体预览',
  'rp.msg.lightboxAria': '原图预览',

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

  // ---------- 画布视图 ----------
  // 联动能力明示：画布 postMessage 协议未实现，当前仅素材读写经 HTTP API 生效
  'canvas.linkage.pending': '画布联动开发中，当前支持素材同步',

  // ---------- 消息卡片 ----------
  'rp.msg.docDone': '已完成',
  // 消息 meta 行文案（原硬编码中文，收编入字典）
  'rp.msg.metaTime': '耗时 {s}s',
  'rp.msg.metaRounds': '{n} 轮',
  'rp.msg.metaUpdated': '更新 {n} 项',
  'rp.msg.chosen': '已选',
  // 建议动作按钮（确定性交互）
  'rp.msg.retry': '重试',
  'rp.msg.continueTask': '继续完成',
  // 用户气泡编辑控制点与停止后继续建议（本地派生）
  'rp.msg.edit': '编辑',
  'rp.msg.editTitle': '编辑并重新发送（截断之后的回复并重答）',
  'rp.msg.continueLastTask': '继续刚才的任务',
  'rp.msg.imageResult': '生图结果',
  'rp.msg.imageTip': '{name} — 点击查看原图，按住拖动到画布',
  'rp.msg.videoResult': '视频结果',
  'rp.msg.videoTip': '{name} — 点击放大播放',
  'rp.msg.download': '下载',
  'rp.msg.lightboxAlt': '原图预览',
  'rp.msg.downloadOriginal': '下载原图',
  'rp.msg.closeEsc': '关闭 (Esc)',
  'rp.msg.stageDone': '阶段完成',
  'rp.msg.appliedOps': '已执行 {count} 个操作',
  'rp.msg.confirmAnswered': '已回应',
  'rp.msg.confirmExpired': '已过期',
  'rp.msg.stopped': '已停止',
  // 停止阶段措辞（不变式：任何中断都有痕迹、都有出口）；
  // 与后端 chat_service._STOP_PHASE_TEXT 同一口径
  'rp.msg.stoppedThinking': '已在思考阶段停止（未产生内容）',
  'rp.msg.stoppedTool': '已在工具执行阶段停止',
  'rp.msg.stoppedToolEmpty': '已在工具执行阶段停止（未产生内容）',
  'rp.msg.stoppedStreaming': '已在输出阶段停止',
  'rp.msg.stoppedInflight': '注意：仍有 {n} 项外部生成任务（出图/出视频）在供应商侧继续，本次停止不会撤销',
  'rp.msg.emptyReply': '（空回复）',
  'rp.msg.memoryRefs': '记忆参考 {count} 条',
  'rp.msg.mediaInserted': 'Agent 已添加 {count} 个素材到对话输入框，确认后可发送',
  'rp.msg.gatePlatform': '平台',
  'rp.msg.gateSkill': 'Skill『{name}』',
  'rp.msg.gateCollapseSummary': '闸机拦截 {total} 条（相同原因合并为 {groups} 类，点击展开）',
  'rp.msg.gateCount': '×{count}',

  // ---------- 过程时间线（深度思考 + 已处理操作） ----------
  'rp.timeline.thinking': '深度思考',
  'rp.timeline.processing': '正在处理…（已完成 {count} 项）',
  'rp.timeline.processed': '已处理 {count} 个操作',
  'rp.msg.confirmContinue': '确认，继续',
  'rp.msg.confirmText': '确认',
  'rp.msg.adjust': '我要调整',
  'rp.msg.gateOverride': '放行本次拦截（本轮闸机全部豁免，仅本次生效）',
  'rp.msg.checkSettings': '检查 API 配置',

  // ---------- 确认向导（i18n 补齐） ----------
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
  'rp.queue.guideTitle': '不打断当前操作，本条将在当前操作完成后优先注入',
  'rp.queue.delete': '删除',
  'rp.queue.more': '更多操作',
  'rp.queue.edit': '编辑消息',
  'rp.queue.openSide': '在侧边聊天中打开',
  'rp.queue.closeQueue': '关闭排队',
  'rp.queue.closeQueueTitle': '清空全部排队消息',
  'rp.queue.openSideBusy': 'Agent 忙碌中，无法新建对话，消息已保留在排队',
  'rp.queue.guideSpinner': '已登记，当前操作完成后即注入',
  'rp.queue.enqueued': '已加入排队，Agent 完成当前任务后自动发送（可点「引导」优先注入）',
  'rp.queue.pauseRejected': '暂停回应未能发出（重复点击或任务忙），请在当前暂停卡上重新选择',
  'rp.queue.cleared': '已清空排队消息',
  'rp.task.done': '后台 Agent 任务已完成',
  'rp.suggested.valueRejected': '建议动作文本异常（非人类可读），已拦截发送',
  'rp.msg.metaTokens': '{n} tokens',
  'rp.msg.regenerate': '重新生成（截断之后的回复，按最后问题重答）',
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
  'rp.asset.libraryAria': '画布素材库弹窗',

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
  'rp.picker.dialogAria': '素材库选择弹窗',
  'rp.skillDetail.dialogAria': 'Skill 详情',
  'rp.skillImport.dialogAria': 'Skill 导入',

  // ---------- 代码块增强 ----------
  'rp.code.copy': '复制',
  'rp.code.copied': '已复制',
  'rp.code.copyFailed': '复制失败，请手动选择代码复制',
  'rp.code.langPlain': '文本',

  // ---------- 全局健康层（断网/后端失联横幅，措辞分因） ----------
  'health.offline': '网络已断开，正在等待连接恢复…',
  'health.backendDown': '后端服务失联，正在自动重试…（进行中的任务不受影响）',
  'health.aria': '连接状态提醒',

  // ---------- 长任务阶段进度条（客观进度 + 推理轮次） ----------
  'rp.progress.title': '任务进度',
  'rp.progress.round': '第 {step}/{max} 轮',
  'rp.progress.ke': '关键元素',
  'rp.progress.shots': '分镜',
  'rp.progress.audio': '音频',

  // ---------- 空状态引导卡（示例指令，点击即发送） ----------
  'rp.empty.title': '从一个想法开始',
  'rp.empty.try': '试试这样问',
  'rp.empty.example1': '我有个创意：雨夜巷口追影子的少女，帮我规划故事板',
  'rp.empty.example2': '帮我写一个 30 秒商品宣传短片的方案',
  'rp.empty.example3': '当前有哪些 Skill？推荐一个适合我的题材',
  'rp.empty.example4': '把故事板第一组的提示词润色一下',

  // ---------- 消息搜索与轮次跳转 ----------
  'rp.search.open': '搜索消息 / 跳转轮次',
  'rp.search.placeholder': '搜索消息内容…',
  'rp.search.noResult': '没有匹配的消息',
  'rp.search.turns': '轮次跳转',
  'rp.search.results': '搜索结果',
  'rp.search.ask': '问',
  'rp.search.answer': '答',

  // ---------- 消息窗口化（长会话只渲染近段，向前按需展开） ----------
  'rp.feed.showEarlier': '显示更早的消息（{n} 条未显示）',

  // ---------- 消息悬停工具条与截断重答（任务 #17 新交互模型） ----------
  'rp.msg.copy': '复制',
  'rp.msg.copied': '已复制',
  'rp.msg.branch': '分支：以此消息为分叉点创建新对话',
  'rp.msg.branchedAt': '已从此消息创建分支对话',
  'rp.msg.branchFailed': '创建分支失败：{error}',
  'rp.msg.truncateFailed': '截断重答失败：{error}',
  'rp.msg.editCancel': '取消',
  'rp.msg.editSend': '发送',
  // 存为文档（任务 #6 C-2：不经 LLM 的确定性兜底）
  'rp.msg.saveDoc': '存为文档',
  'rp.msg.saveDocTitle': '把该条回复正文存为项目文档',
  'rp.msg.docSaved': '已存入文档：{name}',
  'rp.msg.docSaveFailed': '存入文档失败：{error}',
} satisfies Record<string, string>;

/** 字典键联合类型：t() 编译期校验的单一来源（拼错的 key 无法通过 tsc） */
export type LocaleKey = keyof typeof zhCN;

/** 字典全部已登记键（key 校验测试/工具遍历用，只读） */
export const LOCALE_KEYS = Object.keys(zhCN) as LocaleKey[];

/** 语言包注册表：en 待第三期后补齐，当前回退 zh-CN */
const dictionaries: Record<LocaleId, Partial<Record<LocaleKey, string>>> = {
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

/** {占位符} 插值：如 interpolate('已放入：{name}', { name: '图A' }) */
function interpolate(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text;
  let out = text;
  for (const [name, value] of Object.entries(vars)) {
    out = out.split(`{${name}}`).join(String(value));
  }
  return out;
}

/**
 * 取文案（编译期键校验）：key 必须是字典已登记键，拼错直接 tsc 报错。
 * vars 提供 {占位符} 插值，如 t('rp.input.added', { name: '图A' })。
 */
export function t(key: LocaleKey, vars?: Record<string, string | number>): string {
  return interpolate(dictionaries[currentLocale][key] ?? zhCN[key], vars);
}

/**
 * 动态键取文案（后端 SSE status 事件下发 key 等运行时字符串专用）：
 * 当前语言 → zh-CN 回退 → key 本身。静态调用点一律用 t()，勿绕过类型校验。
 */
export function tDynamic(key: string, vars?: Record<string, string | number>): string {
  const known = key as LocaleKey;
  const text = dictionaries[currentLocale][known] ?? zhCN[known] ?? key;
  return interpolate(text, vars);
}
