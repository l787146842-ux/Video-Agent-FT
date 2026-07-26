/**
 * Flova Studio - 影视创作工作台核心 JavaScript
 */

// 全局状态管理
const state = {
    leftTab: 'storyboard', // storyboard | uncategorized
    subTab: 'keyElements', // keyElements | shots | audio
    showAllAssets: false,
    selectedDraftId: 'ke-1-d1',
    selectedType: 'keyElement', // keyElement | shot | audio
    isPromptCollapsed: false,
    apiProviders: [],
    skills: [],
    agentBusy: false,
    pendingAttachments: [], // 输入框内待发送的附件
    
    // 故事板数据（支持 Agent 实时修改与插入）
    keyElements: [
        {
            id: 'ke-1',
            title: '人物设定：探险队长罗林',
            desc: '穿着重型外骨骼战甲，眼神坚毅，面部有微小机械疤痕，带高科技全息单镜片。',
            drafts: [
                {
                    id: 'ke-1-d1',
                    label: '草稿1 - 概念高光',
                    tag: '推荐',
                    mediaType: 'image',
                    imgUrl: 'https://picsum.photos/id/1025/1200/800',
                    prompt: '超高细节，探险队长罗林特写，正面视角，穿着黑色磨损外骨骼战甲，全息单镜片散发蓝光，眼神坚毅，电影级采光，8k分辨率，赛博朋克现实主义 --ar 16:9 --v 6.0',
                    model: 'Flux.1',
                    aspectRatio: '16:9',
                    size: '1280x720',
                    refAssets: []
                },
                {
                    id: 'ke-1-d2',
                    label: '草稿2 - 战甲细节',
                    tag: '已确认',
                    mediaType: 'image',
                    imgUrl: 'https://picsum.photos/id/1062/1200/800',
                    prompt: '探险队长战甲金属纹理特写，带有微光粒子与机械结构拼合，真实金属光泽，硬核科幻设计 --ar 16:9',
                    model: 'Midjourney v6',
                    aspectRatio: '16:9',
                    size: '1280x720',
                    refAssets: []
                }
            ]
        },
        {
            id: 'ke-2',
            title: '场景设定：二维化降维星云',
            desc: '太阳系边缘被二向箔压缩形成的平面星云，颜色绚丽而诡异，毫无厚度的平面质感。',
            drafts: [
                {
                    id: 'ke-2-d1',
                    label: '草稿1 - 星云全景',
                    tag: '草稿',
                    mediaType: 'image',
                    imgUrl: 'https://picsum.photos/id/1015/1200/800',
                    prompt: '三体降维打击视觉表现，二维化的太阳系星空，极度绚丽的绚彩平坦漩涡，无深度感，空间折叠美学，高清电影剧照 --ar 21:9',
                    model: 'Nano Pro',
                    aspectRatio: '21:9',
                    size: '1280x544',
                    refAssets: []
                }
            ]
        }
    ],

    shots: [
        {
            id: 'shot-1',
            title: '镜头 01',
            duration: '4.5s',
            roughDesc: '飞船缓缓穿过降维星云边缘，产生扭曲的光晕与能量涟漪。',
            drafts: [
                {
                    id: 'shot-1-d1',
                    label: '分镜卡片 1',
                    tag: '生成中',
                    mediaType: 'video',
                    videoUrl: 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
                    prompt: '镜头向前慢推，探险飞船从左向右穿过炫彩二维漩涡，船体表面泛起金色能量涟漪，流畅电影运镜，60fps，科幻大片质感',
                    mode: '全能参考',
                    model: 'Sora',
                    resolution: '1080p',
                    duration: '5s',
                    aspectRatio: '16:9',
                    refAssets: ['https://picsum.photos/id/1015/400/300']
                }
            ]
        },
        {
            id: 'shot-2',
            title: '镜头 02',
            duration: '3.0s',
            roughDesc: '罗林队长推下推进器手柄，仪表盘指针剧烈抖动。',
            drafts: [
                {
                    id: 'shot-2-d1',
                    label: '分镜卡片 1',
                    tag: '待确认',
                    mediaType: 'video',
                    videoUrl: '',
                    prompt: '特写镜头：硬朗的大手推下金属推进器手柄，全息控制面板红光闪烁，仪表盘指针快速飙升，镜头轻微震颤',
                    mode: '图生视频',
                    model: 'Luma Dream Machine',
                    resolution: '1080p',
                    duration: '3s',
                    aspectRatio: '16:9',
                    refAssets: []
                }
            ]
        }
    ],

    audioItems: [
        {
            id: 'audio-1',
            title: '音频层 01 - 旁白与环境音',
            timeRange: '00:00 - 00:08',
            prompt: '深沉压抑的宇宙低频震动配乐，伴随着高科技飞船报警蜂鸣声，以及男旁白深邃的声音：“太阳系正在坠入二维...”',
            drafts: [
                {
                    id: 'audio-1-d1',
                    label: '音频草稿 1',
                    mediaType: 'audio',
                    prompt: '深沉压抑宇宙低音 + 高科技报警音 + 男声独白：“太阳系正在坠入二维...”',
                    mode: '多模态音频生成',
                    model: 'ElevenLabs',
                    timbre: '深邃男声 (Deep Narrator)',
                    refAssets: []
                }
            ]
        }
    ],

    // 未归类素材
    assets: [
        { id: 'ast-1', name: '罗林肖像参考.png', type: 'image', isBound: true, url: 'https://picsum.photos/id/1025/400/300' },
        { id: 'ast-2', name: '星云纹理背景.jpg', type: 'image', isBound: true, url: 'https://picsum.photos/id/1015/400/300' },
        { id: 'ast-3', name: '飞船引擎音效.mp3', type: 'audio', isBound: false, url: '' },
        { id: 'ast-4', name: '二向箔降维渲染.mp4', type: 'video', isBound: false, url: 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4' },
        { id: 'ast-5', name: '空间站草图.jpg', type: 'image', isBound: false, url: 'https://picsum.photos/id/1062/400/300' }
    ],

    // Agent 对话历史
    chatMessages: [
        {
            sender: 'agent',
            text: '你好！我是你的 AI 编剧与导演助手。我已经根据《深空探险三体》剧本提取出了 2 个关键元素、2 个关键分镜和音频层。你可以点击左侧草稿卡片进行预览，或者直接告诉我需要调整什么！'
        }
    ]
};

// 初始化页面
document.addEventListener('DOMContentLoaded', async () => {
    initSplitters();
    // 从后端加载持久化状态（替代硬编码 demo 数据）
    await loadStateFromBackend();
    renderLeftContent();
    renderRightChat();
    updateMiddlePreview();
    await loadCanvasApiConfig();
    bindApiConfigUpdates();
    renderWorkflowPhases();
    lucide.createIcons();
});

// 从后端加载项目状态
async function loadStateFromBackend() {
    try {
        const res = await fetch('/api/project/state');
        if (!res.ok) return;
        const serverState = await res.json();
        if (serverState.keyElements && serverState.keyElements.length) state.keyElements = serverState.keyElements;
        if (serverState.shots && serverState.shots.length) state.shots = serverState.shots;
        if (serverState.audioItems && serverState.audioItems.length) state.audioItems = serverState.audioItems;
        if (serverState.assets && serverState.assets.length) state.assets = serverState.assets;
        if (serverState.chatMessages && serverState.chatMessages.length) state.chatMessages = serverState.chatMessages;
        // 设置项目名
        if (serverState.project_name) {
            document.getElementById('currentProjectName').textContent = serverState.project_name;
        }
        // 选中第一个 draft
        const firstGroup = state.keyElements[0] || state.shots[0] || state.audioItems[0];
        if (firstGroup && firstGroup.drafts && firstGroup.drafts.length) {
            state.selectedDraftId = firstGroup.drafts[0].id;
            state.selectedType = state.keyElements.includes(firstGroup) ? 'keyElement'
                : state.shots.includes(firstGroup) ? 'shot' : 'audio';
        }
        console.log('[Studio] State loaded from backend');
    } catch (e) {
        console.warn('[Studio] Failed to load state from backend, using defaults:', e);
    }
}

// 初始化拖拽分割线 (Splitters)
function initSplitters() {
    const colLeft = document.getElementById('colLeft');
    const colMiddle = document.getElementById('colMiddle');
    const colRight = document.getElementById('colRight');
    const previewTop = document.getElementById('previewTop');
    const previewBottom = document.getElementById('previewBottom');

    const splitterLeft = document.getElementById('splitterLeft');
    const splitterRight = document.getElementById('splitterRight');
    const splitterPreview = document.getElementById('splitterPreview');

    // 左侧与中间竖向拖拽
    setupDrag(splitterLeft, (deltaX) => {
        const newWidth = Math.max(240, Math.min(600, colLeft.offsetWidth + deltaX));
        colLeft.style.width = newWidth + 'px';
    });

    // 中间与右侧竖向拖拽
    setupDrag(splitterRight, (deltaX) => {
        const newWidth = Math.max(280, Math.min(650, colRight.offsetWidth - deltaX));
        colRight.style.width = newWidth + 'px';
    });

    // 中间预览区域上下横向拖拽
    setupDrag(splitterPreview, (deltaX, deltaY) => {
        const newHeight = Math.max(120, Math.min(500, previewBottom.offsetHeight - deltaY));
        previewBottom.style.height = newHeight + 'px';
    }, true);
}

function setupDrag(element, onMove, isVertical = false) {
    let startX = 0;
    let startY = 0;

    element.addEventListener('mousedown', (e) => {
        startX = e.clientX;
        startY = e.clientY;
        element.classList.add('dragging');

        const handleMouseMove = (moveEvent) => {
            const deltaX = moveEvent.clientX - startX;
            const deltaY = moveEvent.clientY - startY;
            onMove(deltaX, deltaY);
            startX = moveEvent.clientX;
            startY = moveEvent.clientY;
        };

        const handleMouseUp = () => {
            element.classList.remove('dragging');
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
    });
}

// 切换左侧大分类（故事板 vs 未归类素材）
function switchLeftTab(tab) {
    state.leftTab = tab;
    document.getElementById('tabStoryboard').classList.toggle('active', tab === 'storyboard');
    document.getElementById('tabUncategorized').classList.toggle('active', tab === 'uncategorized');
    
    document.getElementById('storyboardView').classList.toggle('hidden', tab !== 'storyboard');
    document.getElementById('uncategorizedView').classList.toggle('hidden', tab !== 'uncategorized');

    if (tab === 'uncategorized') {
        renderUncategorizedAssets();
    }
}

// 切换故事板子分类（关键元素 | 分镜 | 音频层）
function switchSubTab(sub) {
    state.subTab = sub;
    document.getElementById('subKeyElements').classList.toggle('active', sub === 'keyElements');
    document.getElementById('subShots').classList.toggle('active', sub === 'shots');
    document.getElementById('subAudio').classList.toggle('active', sub === 'audio');

    renderLeftContent();
}

// 渲染左侧内容
function renderLeftContent() {
    const container = document.getElementById('subCategoryContent');
    if (!container) return;

    if (state.subTab === 'keyElements') {
        container.innerHTML = state.keyElements.map(item => `
            <div class="sb-group">
                <div class="sb-group-header">
                    <div class="sb-title">
                        <i data-lucide="image" class="w-4 h-4 text-blue-400"></i>
                        <span>${item.title}</span>
                    </div>
                    <span class="sb-badge">关键元素</span>
                </div>
                <p class="sb-desc">${item.desc}</p>

                <!-- 草稿卡片横排 -->
                <div class="draft-cards-row">
                    <button class="add-card-btn" title="手动新建/上传草稿" onclick="addNewDraftCard('${item.id}', 'keyElement')">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                    </button>
                    ${item.drafts.map(d => `
                        <div class="draft-card ${state.selectedDraftId === d.id ? 'active' : ''}" 
                             style="background-image: url('${d.imgUrl}')" 
                             onclick="selectDraftCard('${d.id}', 'keyElement')">
                            ${d.tag ? `<span class="draft-card-tag">${d.tag}</span>` : ''}
                            <span class="draft-card-label">${d.label}</span>
                        </div>
                    `).join('')}
                </div>

                <!-- 草稿卡片调整输入框 -->
                <div class="card-adjust-box">
                    <input type="text" class="card-adjust-input" placeholder="对选中的画面卡片提出修改意见..." 
                           onkeydown="if(event.key==='Enter') adjustDraftCardPrompt('${item.id}', this.value)">
                    <button class="card-adjust-btn" onclick="adjustDraftCardPrompt('${item.id}', this.previousElementSibling.value)">微调</button>
                </div>
            </div>
        `).join('');
    } else if (state.subTab === 'shots') {
        container.innerHTML = state.shots.map(item => `
            <div class="sb-group">
                <div class="sb-group-header">
                    <div class="sb-title">
                        <i data-lucide="video" class="w-4 h-4 text-purple-400"></i>
                        <span>${item.title} (${item.duration})</span>
                    </div>
                    <span class="sb-badge" style="background:rgba(139, 92, 246, 0.15); color:#a78bfa">分镜</span>
                </div>
                <p class="sb-desc">${item.roughDesc}</p>

                <!-- 分镜草稿卡片横排 -->
                <div class="draft-cards-row">
                    <button class="add-card-btn" title="手动生成视频分镜" onclick="addNewDraftCard('${item.id}', 'shot')">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                    </button>
                    ${item.drafts.map(d => `
                        <div class="draft-card ${state.selectedDraftId === d.id ? 'active' : ''}" 
                             style="background-color:#2e3346" 
                             onclick="selectDraftCard('${d.id}', 'shot')">
                            ${d.tag ? `<span class="draft-card-tag" style="background:#8b5cf6">${d.tag}</span>` : ''}
                            <span class="draft-card-label">${d.label}</span>
                        </div>
                    `).join('')}
                </div>

                <!-- 调整输入框 -->
                <div class="card-adjust-box">
                    <input type="text" class="card-adjust-input" placeholder="调整此段分镜镜头、运镜或动作描述..." 
                           onkeydown="if(event.key==='Enter') adjustShotPrompt('${item.id}', this.value)">
                    <button class="card-adjust-btn" onclick="adjustShotPrompt('${item.id}', this.previousElementSibling.value)">调整</button>
                </div>
            </div>
        `).join('');
    } else if (state.subTab === 'audio') {
        container.innerHTML = state.audioItems.map(item => `
            <div class="sb-group">
                <div class="sb-group-header">
                    <div class="sb-title">
                        <i data-lucide="music" class="w-4 h-4 text-emerald-400"></i>
                        <span>${item.title}</span>
                    </div>
                    <span class="sb-badge" style="background:rgba(16, 185, 129, 0.15); color:#34d399">${item.timeRange}</span>
                </div>
                <p class="sb-desc">${item.prompt}</p>

                <div class="draft-cards-row">
                    <button class="add-card-btn" title="上传或写提示词生成音频" onclick="addNewDraftCard('${item.id}', 'audio')">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                    </button>
                    ${item.drafts.map(d => `
                        <div class="draft-card ${state.selectedDraftId === d.id ? 'active' : ''}" 
                             style="background-color:#1e293b" 
                             onclick="selectDraftCard('${d.id}', 'audio')">
                            <span class="draft-card-label">${d.label}</span>
                        </div>
                    `).join('')}
                </div>

                <div class="card-adjust-box">
                    <input type="text" class="card-adjust-input" placeholder="调整配乐语气、台词或旁白细节..."
                           onkeydown="if(event.key==='Enter') adjustAudioPrompt('${item.id}', this.value)">
                    <button class="card-adjust-btn" onclick="adjustAudioPrompt('${item.id}', this.previousElementSibling.value)">微调</button>
                </div>
            </div>
        `).join('');
    }

    lucide.createIcons();
}

// 选中草稿卡片
function selectDraftCard(draftId, type) {
    state.selectedDraftId = draftId;
    state.selectedType = type;
    renderLeftContent();
    updateMiddlePreview();
}

// 渲染未归类素材
function renderUncategorizedAssets() {
    const grid = document.getElementById('assetsGrid');
    if (!grid) return;

    const filtered = state.assets.filter(a => state.showAllAssets || !a.isBound);

    grid.innerHTML = filtered.map(a => `
        <div class="asset-item" style="background-image: url('${a.url || '/static/images/logo.png'}')" title="${escapeHtml(a.name)}">
            <span class="asset-item-badge">${a.type.toUpperCase()} | ${a.isBound ? '已绑定' : '未绑定'}</span>
            <span class="asset-item-name">${escapeHtml(a.name)}</span>
        </div>
    `).join('');
}

function toggleShowAllAssets() {
    state.showAllAssets = !state.showAllAssets;
    document.getElementById('assetShowAllTrack').classList.toggle('active', state.showAllAssets);
    document.getElementById('assetShowAllButton')?.setAttribute('aria-pressed', String(state.showAllAssets));
    renderUncategorizedAssets();
}

// 更新中间预览与参数控制
function updateMiddlePreview() {
    const mediaViewer = document.getElementById('previewMediaViewer');
    const promptInput = document.getElementById('detailedPromptInput');
    const paramBar = document.getElementById('paramControlsBar');
    const refThumbs = document.getElementById('refThumbs');

    let currentDraft = null;

    if (state.selectedType === 'keyElement') {
        state.keyElements.forEach(ke => {
            const found = ke.drafts.find(d => d.id === state.selectedDraftId);
            if (found) currentDraft = found;
        });
    } else if (state.selectedType === 'shot') {
        state.shots.forEach(s => {
            const found = s.drafts.find(d => d.id === state.selectedDraftId);
            if (found) currentDraft = found;
        });
    } else if (state.selectedType === 'audio') {
        state.audioItems.forEach(a => {
            const found = a.drafts.find(d => d.id === state.selectedDraftId);
            if (found) currentDraft = found;
        });
    }

    if (!currentDraft) {
        if (mediaViewer) mediaViewer.innerHTML = `
            <div class="text-center text-gray-500">
                <i data-lucide="image" class="w-12 h-12 mx-auto mb-2 opacity-30"></i>
                <p class="text-xs">暂无预览内容</p>
            </div>`;
        if (promptInput) promptInput.value = '';
        lucide.createIcons();
        return;
    }

    // 1. 媒体预览更新
    if (currentDraft.mediaType === 'image') {
        mediaViewer.innerHTML = `<img src="${currentDraft.imgUrl}" alt="Preview Image" class="max-h-full rounded-lg shadow-xl">`;
    } else if (currentDraft.mediaType === 'video') {
        if (currentDraft.videoUrl) {
            mediaViewer.innerHTML = `
                <video src="${currentDraft.videoUrl}" controls autoplay loop class="max-h-full rounded-lg shadow-xl"></video>
            `;
        } else {
            mediaViewer.innerHTML = `
                <div class="text-center text-purple-400">
                    <i data-lucide="loader" class="w-10 h-10 animate-spin mx-auto mb-2"></i>
                    <p class="text-xs">Agent 提交生成任务，等待渲染完成...</p>
                </div>
            `;
        }
    } else if (currentDraft.mediaType === 'audio') {
        mediaViewer.innerHTML = `
            <div class="audio-preview-card">
                <i data-lucide="disc" class="w-12 h-12 text-emerald-400 animate-spin"></i>
                <span class="text-sm font-semibold text-gray-200">${currentDraft.label}</span>
                <audio controls class="w-full mt-2">
                    <source src="" type="audio/mpeg">
                    您的浏览器不支持音频播放
                </audio>
            </div>
        `;
    }

    // 2. 提示词填入
    promptInput.value = currentDraft.prompt || '';

    // 3. 参考素材缩略图填入
    if (currentDraft.refAssets && currentDraft.refAssets.length > 0) {
        refThumbs.innerHTML = currentDraft.refAssets.map(url => `
            <img src="${url}" class="ref-thumb" alt="Reference">
        `).join('');
    } else {
        refThumbs.innerHTML = `<span class="text-xs text-gray-500">暂无参考素材</span>`;
    }

    // 4. 参数控制栏根据模式渲染
    if (state.selectedType === 'keyElement') {
        currentDraft.providerId = populateDraftProvider(currentDraft, 'image');
        const imageProviders = apiProvidersFor('image');
        const imageModels = providerModels(currentDraft.providerId, 'image');
        if (!imageModels.includes(currentDraft.model)) currentDraft.model = imageModels[0] || '';
        paramBar.innerHTML = `
            <div class="param-group">
                <span class="param-label">图片 API:</span>
                <select class="param-select" id="imageProviderSelect" aria-label="图片 API 平台">
                    ${imageProviders.map(provider => optionHtml(provider.id, provider.name || provider.id, currentDraft.providerId)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">生成模型:</span>
                <select class="param-select" id="modelSelect" aria-label="图片生成模型">
                    ${imageModels.map(model => optionHtml(model, model, currentDraft.model)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">图片比例:</span>
                <select class="param-select" id="aspectSelect" aria-label="图片画面比例">
                    <option ${currentDraft.aspectRatio === '1:1' ? 'selected' : ''}>1:1</option>
                    <option ${currentDraft.aspectRatio === '16:9' ? 'selected' : ''}>16:9</option>
                    <option ${currentDraft.aspectRatio === '9:16' ? 'selected' : ''}>9:16</option>
                    <option ${currentDraft.aspectRatio === '3:4' ? 'selected' : ''}>3:4</option>
                    <option ${currentDraft.aspectRatio === '4:3' ? 'selected' : ''}>4:3</option>
                    <option ${currentDraft.aspectRatio === '2:3' ? 'selected' : ''}>2:3</option>
                    <option ${currentDraft.aspectRatio === '3:2' ? 'selected' : ''}>3:2</option>
                    <option ${currentDraft.aspectRatio === '21:9' ? 'selected' : ''}>21:9</option>
                    <option ${currentDraft.aspectRatio === '9:21' ? 'selected' : ''}>9:21</option>
                    <option value="custom" ${currentDraft.aspectRatio === 'custom' ? 'selected' : ''}>自定义</option>
                </select>
            </div>
            <div class="param-group studio-custom-ratio" id="imageCustomRatioGroup" ${currentDraft.aspectRatio === 'custom' ? '' : 'hidden'}>
                <span class="param-label">自定义:</span>
                <input class="custom-ratio-input" id="imageCustomRatioWidth" type="number" min="1" step="1" value="${escapeHtml(currentDraft.customRatioWidth || '4')}" aria-label="自定义比例宽">
                <span class="text-gray-500">:</span>
                <input class="custom-ratio-input" id="imageCustomRatioHeight" type="number" min="1" step="1" value="${escapeHtml(currentDraft.customRatioHeight || '3')}" aria-label="自定义比例高">
            </div>
            <div class="flex gap-2">
                <button class="btn-secondary" onclick="saveDraftParams()">保存</button>
                <button class="btn-primary" onclick="generateImage()">
                    <i data-lucide="sparkles" class="w-3.5 h-3.5"></i> 生成图片
                </button>
            </div>
        `;
    } else if (state.selectedType === 'shot') {
        currentDraft.providerId = populateDraftProvider(currentDraft, 'video');
        const videoProviders = apiProvidersFor('video');
        const videoModels = providerModels(currentDraft.providerId, 'video');
        if (!videoModels.includes(currentDraft.model)) currentDraft.model = videoModels[0] || '';
        paramBar.innerHTML = `
            <div class="param-group">
                <span class="param-label">模式拉框:</span>
                <select class="param-select" id="videoModeSelect" aria-label="视频生成模式">
                    <option ${currentDraft.mode === '全能参考' ? 'selected' : ''}>全能参考</option>
                    <option ${currentDraft.mode === '图生视频' ? 'selected' : ''}>图生视频</option>
                    <option ${currentDraft.mode === '首尾帧生视频' ? 'selected' : ''}>首尾帧生视频</option>
                    <option ${currentDraft.mode === '对口型数字人' ? 'selected' : ''}>对口型数字人</option>
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">视频 API:</span>
                <select class="param-select" id="videoProviderSelect" aria-label="视频 API 平台">
                    ${videoProviders.map(provider => optionHtml(provider.id, provider.name || provider.id, currentDraft.providerId)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">视频模型:</span>
                <select class="param-select" id="videoModelSelect" aria-label="视频生成模型">
                    ${videoModels.map(model => optionHtml(model, model, currentDraft.model)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">分辨率:</span>
                <select class="param-select" id="videoResolutionSelect" aria-label="视频分辨率">
                    <option ${currentDraft.resolution === '720p' ? 'selected' : ''}>720p</option>
                    <option ${currentDraft.resolution === '1080p' || !currentDraft.resolution ? 'selected' : ''}>1080p</option>
                    <option ${currentDraft.resolution === '2K' ? 'selected' : ''}>2K</option>
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">时长:</span>
                <select class="param-select" id="durationSelect" aria-label="视频时长">
                    <option ${currentDraft.duration === '3s' ? 'selected' : ''}>3s</option>
                    <option ${currentDraft.duration === '5s' || !currentDraft.duration ? 'selected' : ''}>5s</option>
                    <option ${currentDraft.duration === '10s' ? 'selected' : ''}>10s</option>
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">画幅比例:</span>
                <select class="param-select" id="videoAspectSelect" aria-label="视频画幅比例">
                    <option ${currentDraft.aspectRatio === '16:9' || !currentDraft.aspectRatio ? 'selected' : ''}>16:9</option>
                    <option ${currentDraft.aspectRatio === '9:16' ? 'selected' : ''}>9:16</option>
                    <option ${currentDraft.aspectRatio === '1:1' ? 'selected' : ''}>1:1</option>
                    <option ${currentDraft.aspectRatio === '21:9' ? 'selected' : ''}>21:9</option>
                </select>
            </div>
            <div class="flex gap-2">
                <button class="btn-secondary" onclick="saveDraftParams()">保存</button>
                <button class="btn-primary" style="background:#8b5cf6" onclick="generateVideo()">
                    <i data-lucide="film" class="w-3.5 h-3.5"></i> 生成视频
                </button>
            </div>
        `;
    } else if (state.selectedType === 'audio') {
        currentDraft.providerId = populateDraftProvider(currentDraft, 'chat');
        const audioProviders = apiProvidersFor('chat');
        const audioModels = providerModels(currentDraft.providerId, 'chat');
        if (!audioModels.includes(currentDraft.model)) currentDraft.model = audioModels[0] || '';
        paramBar.innerHTML = `
            <div class="param-group">
                <span class="param-label">生成模式:</span>
                <select class="param-select" id="audioModeSelect" aria-label="音频生成模式">
                    <option ${currentDraft.mode === '多模态音频生成' ? 'selected' : ''}>多模态音频生成</option>
                    <option ${currentDraft.mode === '旁白语音合成' ? 'selected' : ''}>旁白语音合成</option>
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">规划 API:</span>
                <select class="param-select" id="audioProviderSelect" aria-label="音频规划 API 平台">
                    ${audioProviders.map(provider => optionHtml(provider.id, provider.name || provider.id, currentDraft.providerId)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">规划模型:</span>
                <select class="param-select" id="audioModelSelect" aria-label="音频规划模型">
                    ${audioModels.map(model => optionHtml(model, model, currentDraft.model)).join('')}
                </select>
            </div>
            <div class="param-group">
                <span class="param-label">音色选择:</span>
                <select class="param-select" id="audioVoiceSelect" aria-label="音频音色">
                    <option ${currentDraft.timbre === '深邃男声 (Deep Narrator)' || !currentDraft.timbre ? 'selected' : ''}>深邃男声 (Deep Narrator)</option>
                    <option ${currentDraft.timbre === '冷酷女声 (AI Core Voice)' ? 'selected' : ''}>冷酷女声 (AI Core Voice)</option>
                </select>
            </div>
            <div class="flex gap-2">
                <button class="btn-primary" style="background:#10b981" onclick="generateAudio()">
                    <i data-lucide="music" class="w-3.5 h-3.5"></i> 生成音频规划
                </button>
            </div>
        `;
    }

    bindDraftApiControls(currentDraft);

    lucide.createIcons();
}

function populateDraftProvider(draft, kind) {
    const providers = apiProvidersFor(kind);
    return providers.some(provider => provider.id === draft.providerId) ? draft.providerId : preferredProviderIdForKind(kind, providers);
}

function bindDraftApiControls(draft) {
    const pairs = [
        ['imageProviderSelect', 'modelSelect', 'image'],
        ['videoProviderSelect', 'videoModelSelect', 'video'],
        ['audioProviderSelect', 'audioModelSelect', 'chat']
    ];
    pairs.forEach(([providerId, modelId, kind]) => {
        const providerSelect = document.getElementById(providerId);
        const modelSelect = document.getElementById(modelId);
        if (!providerSelect || !modelSelect) return;
        providerSelect.disabled = !providerSelect.options.length;
        modelSelect.disabled = !modelSelect.options.length;
        providerSelect.onchange = () => {
            draft.providerId = providerSelect.value;
            draft.model = populateModelSelect(modelSelect, draft.providerId, kind, '');
        };
        modelSelect.onchange = () => { draft.model = modelSelect.value; };
    });

    const imageAspectSelect = document.getElementById('aspectSelect');
    const customRatioGroup = document.getElementById('imageCustomRatioGroup');
    const customRatioWidth = document.getElementById('imageCustomRatioWidth');
    const customRatioHeight = document.getElementById('imageCustomRatioHeight');
    if (imageAspectSelect && customRatioGroup) {
        const syncImageRatio = () => {
            draft.aspectRatio = imageAspectSelect.value;
            customRatioGroup.hidden = imageAspectSelect.value !== 'custom';
            if (imageAspectSelect.value === 'custom') {
                draft.customRatioWidth = customRatioWidth.value || '4';
                draft.customRatioHeight = customRatioHeight.value || '3';
            }
        };
        imageAspectSelect.onchange = syncImageRatio;
        [customRatioWidth, customRatioHeight].forEach(input => {
            input.oninput = () => {
                draft.customRatioWidth = customRatioWidth.value;
                draft.customRatioHeight = customRatioHeight.value;
            };
        });
        syncImageRatio();
    }
}

// 提示词收缩与展开
function toggleCollapsePrompt() {
    state.isPromptCollapsed = !state.isPromptCollapsed;
    const promptInput = document.getElementById('detailedPromptInput');
    const collapseText = document.getElementById('collapseText');
    const collapseIcon = document.getElementById('collapseIcon');

    if (state.isPromptCollapsed) {
        promptInput.style.display = 'none';
        collapseText.innerText = '展开提示词';
        collapseIcon.setAttribute('data-lucide', 'chevron-down');
    } else {
        promptInput.style.display = 'block';
        collapseText.innerText = '收缩提示词 (只看画面)';
        collapseIcon.setAttribute('data-lucide', 'chevron-up');
    }
    lucide.createIcons();
}

// 渲染右侧 Agent 聊天
function renderRightChat() {
    const feed = document.getElementById('chatFeed');
    if (!feed) return;

    feed.innerHTML = state.chatMessages.map(msg => `
        <div class="chat-msg ${msg.sender}">
            <span class="msg-author">${msg.sender === 'user' ? '你' : '导演 Agent'}</span>
            <div class="chat-bubble">${escapeHtml(msg.text).replace(/\n/g, '<br>')}</div>
        </div>
    `).join('');

    feed.scrollTop = feed.scrollHeight;
}

// 发送 Agent 消息与交互循环
async function sendAgentMessage(forcedText = '') {
    const input = document.getElementById('chatInput');
    const text = String(forcedText || input.value || '').trim();
    const hasAttachments = state.pendingAttachments.length > 0;
    if ((!text && !hasAttachments) || state.agentBusy) return;

    const provider = document.getElementById('agentProviderSelect')?.value || '';
    const model = document.getElementById('agentModelSelect')?.value || '';
    const skillId = document.getElementById('agentSkillSelect')?.value || 'production-agent';
    const skill = state.skills.find(item => item.id === skillId);
    if (!provider || !model) {
        showToast('请先选择 Agent API 和对应模型');
        return;
    }

    // 构建显示文本：包含附件信息
    let displayText = text;
    if (hasAttachments) {
        const attNames = state.pendingAttachments.map(a => a.name).join('、');
        const attPrefix = `[已上传并绑定素材] ${attNames}`;
        displayText = text ? `${attPrefix}\n${text}` : attPrefix;
    }

    // 将附件绑定到资产库
    if (hasAttachments) {
        for (const att of state.pendingAttachments) {
            state.assets.unshift({
                id: att.id,
                name: att.name,
                type: att.type,
                isBound: true,
                url: att.url
            });
        }
        if (state.leftTab === 'uncategorized') renderUncategorizedAssets();
    }

    state.chatMessages.push({ sender: 'user', text: displayText });
    input.value = '';
    state.pendingAttachments = [];
    renderPendingAttachments();
    state.agentBusy = true;
    setAgentBusy(true);
    renderRightChat();
    try {
        const context = buildAgentContext();
        const history = state.chatMessages.slice(-12, -1).map(message => ({
            role: message.sender === 'agent' ? 'assistant' : 'user',
            content: message.text
        }));
        const systemPrompt = [skill?.system_prompt || '', STUDIO_ACTION_PROTOCOL_PROMPT].filter(Boolean).join('\n\n');
        const response = await fetch('/api/canvas-llm', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: [text || '请查看我上传的素材', context].filter(Boolean).join('\n\n'),
                system_prompt: systemPrompt,
                provider,
                model,
                ms_model: provider === 'modelscope' ? model : '',
                messages: history,
                images: selectedAgentAssetUrls('image'),
                videos: selectedAgentAssetUrls('video')
            })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(readApiError(data, 'Agent 请求失败'));
        const visibleReply = String(data.text || '').trim();
        if (!visibleReply) throw new Error('Agent 返回了空回复');
        const appliedCount = data.applied_actions || 0;

        // 后端已执行 studio-actions 并持久化，用返回的 state 快照刷新前端
        if (data.state && appliedCount > 0) {
            refreshStateFromBackend(data.state);
        }

        state.chatMessages.push({sender: 'agent', text: visibleReply});
        renderRightChat();
        if (appliedCount > 0) showToast(`Agent 已联动更新 ${appliedCount} 项`);
    } catch (error) {
        state.chatMessages.push({sender: 'agent', text: `请求失败：${error.message || error}`});
        renderRightChat();
    } finally {
        state.agentBusy = false;
        setAgentBusy(false);
    }
}

function setAgentBusy(busy) {
    const button = document.getElementById('agentSendBtn');
    const input = document.getElementById('chatInput');
    if (button) button.disabled = busy;
    if (input) input.disabled = busy;
}

function buildAgentContext() {
    const assetMode = document.getElementById('agentAssetSelect')?.value || 'bound';
    return [
        '当前 Studio 状态 JSON 如下。需要改左侧故事板、中间预览提示词、确认状态或资产绑定时，请使用 studio-actions。',
        JSON.stringify(buildStudioSnapshot(assetMode), null, 2)
    ].join('\n\n');
}

function selectedAgentAssetUrls(kind) {
    const mode = document.getElementById('agentAssetSelect')?.value || 'bound';
    return state.assets
        .filter(asset => asset.type === kind && asset.url && (mode === 'all' || asset.isBound))
        .map(asset => asset.url);
}

function buildStudioSnapshot(assetMode) {
    const selected = findDraftRecord(state.selectedDraftId, state.selectedType);
    const assets = state.assets
        .filter(asset => assetMode === 'all' || asset.isBound)
        .map(asset => ({
            id: asset.id,
            name: asset.name,
            type: asset.type,
            isBound: !!asset.isBound,
            url: asset.url || ''
        }));
    return {
        selected: selected ? {
            draft_type: selected.type,
            group_id: selected.group.id,
            draft_id: selected.draft.id,
            group_title: selected.group.title || '',
            draft_label: selected.draft.label || ''
        } : null,
        keyElements: state.keyElements.map(item => ({
            id: item.id,
            title: item.title,
            desc: item.desc,
            drafts: item.drafts.map(draftSnapshot)
        })),
        shots: state.shots.map(item => ({
            id: item.id,
            title: item.title,
            duration: item.duration,
            roughDesc: item.roughDesc,
            drafts: item.drafts.map(draftSnapshot)
        })),
        audioItems: state.audioItems.map(item => ({
            id: item.id,
            title: item.title,
            timeRange: item.timeRange,
            prompt: item.prompt,
            drafts: item.drafts.map(draftSnapshot)
        })),
        assets
    };
}

function draftSnapshot(draft) {
    return {
        id: draft.id,
        label: draft.label,
        tag: draft.tag || '',
        mediaType: draft.mediaType,
        prompt: draft.prompt || '',
        model: draft.model || '',
        mode: draft.mode || '',
        aspectRatio: draft.aspectRatio || '',
        duration: draft.duration || '',
        resolution: draft.resolution || '',
        timbre: draft.timbre || '',
        refAssets: draft.refAssets || []
    };
}

function normalizeStudioType(value) {
    const text = String(value || '').trim();
    if (!text || text === 'current') return '';
    if (/^(keyElement|key-element|key_element|element|image)$/i.test(text) || /关键|元素|图片/.test(text)) return 'keyElement';
    if (/^(shot|shots|storyboard|video)$/i.test(text) || /分镜|镜头|视频/.test(text)) return 'shot';
    if (/^(audio|audioItem|audio_item)$/i.test(text) || /音频|旁白|声音/.test(text)) return 'audio';
    return '';
}

function subTabForType(type) {
    if (type === 'shot') return 'shots';
    if (type === 'audio') return 'audio';
    return 'keyElements';
}

function groupsForStudioType(type) {
    if (type === 'shot') return state.shots;
    if (type === 'audio') return state.audioItems;
    return state.keyElements;
}

function findDraftRecord(draftId = state.selectedDraftId, type = state.selectedType) {
    const normalized = normalizeStudioType(type) || state.selectedType || 'keyElement';
    const targetId = draftId === 'current' ? state.selectedDraftId : draftId;
    const types = targetId ? [normalized, 'keyElement', 'shot', 'audio'] : [normalized];
    const seen = new Set();
    for (const t of types) {
        if (!t || seen.has(t)) continue;
        seen.add(t);
        for (const group of groupsForStudioType(t)) {
            const draft = group.drafts?.find(item => item.id === targetId);
            if (draft) return { type: t, group, draft };
        }
    }
    return null;
}

function findGroupRecord(groupId = 'current', type = state.selectedType) {
    const normalized = normalizeStudioType(type) || state.selectedType || 'keyElement';
    if (!groupId || groupId === 'current') {
        const current = findDraftRecord(state.selectedDraftId, normalized);
        return current ? { type: current.type, group: current.group } : null;
    }
    const types = [normalized, 'keyElement', 'shot', 'audio'];
    const seen = new Set();
    for (const t of types) {
        if (!t || seen.has(t)) continue;
        seen.add(t);
        const group = groupsForStudioType(t).find(item => item.id === groupId);
        if (group) return { type: t, group };
    }
    return null;
}

function parseStudioActions(reply) {
    const actions = [];
    const blocks = [
        /```(?:studio-actions|studio_action|studioActions)\s*([\s\S]*?)```/gi,
        /<studio-actions>([\s\S]*?)<\/studio-actions>/gi
    ];
    for (const pattern of blocks) {
        let match;
        while ((match = pattern.exec(reply)) !== null) {
            actions.push(...normalizeActionList(parseActionJson(match[1])));
        }
    }
    return actions.filter(action => action && typeof action === 'object');
}

function parseActionJson(raw) {
    const text = String(raw || '').trim();
    if (!text) return null;
    try {
        return JSON.parse(text);
    } catch (_) {
        return null;
    }
}

function normalizeActionList(parsed) {
    if (Array.isArray(parsed)) return parsed;
    if (parsed && Array.isArray(parsed.actions)) return parsed.actions;
    if (parsed && parsed.action) return [parsed];
    return [];
}

function stripStudioActionBlocks(reply) {
    return String(reply || '')
        .replace(/```(?:studio-actions|studio_action|studioActions)\s*[\s\S]*?```/gi, '')
        .replace(/<studio-actions>[\s\S]*?<\/studio-actions>/gi, '')
        .trim();
}

function applyStudioActions(actions) {
    if (!actions.length) return 0;
    let applied = 0;
    for (const action of actions) {
        if (applyStudioAction(action)) applied += 1;
    }
    if (applied) {
        renderLeftContent();
        updateMiddlePreview();
        if (state.leftTab === 'uncategorized') renderUncategorizedAssets();
        showToast(`Agent 已联动更新 ${applied} 项`);
    }
    return applied;
}

function applyStudioAction(action) {
    const name = String(action.action || action.type || '').trim();
    if (!name) return false;
    if (name === 'update_draft' || name === 'patch_draft' || name === 'update_current_draft' || name === 'set_prompt') {
        return applyDraftPatch(action);
    }
    if (name === 'confirm_draft' || name === 'confirm_current_draft') {
        return applyDraftPatch({...action, patch: {tag: action.tag || '已确认'}});
    }
    if (name === 'update_group' || name === 'patch_group') {
        return applyGroupPatch(action);
    }
    if (name === 'add_draft') {
        return applyAddDraft(action);
    }
    if (name === 'bind_asset') {
        return applyBindAsset(action);
    }
    if (name === 'select_draft') {
        return applySelectDraft(action);
    }
    return false;
}

function actionPatch(action, key = 'patch') {
    const patch = action[key] || action.fields || action.updates || {};
    return patch && typeof patch === 'object' ? patch : {};
}

function assignAllowedFields(target, patch, allowed) {
    let changed = false;
    for (const field of allowed) {
        if (!Object.prototype.hasOwnProperty.call(patch, field)) continue;
        const value = Array.isArray(patch[field]) ? [...patch[field]] : patch[field];
        if (value === undefined) continue;
        target[field] = value;
        changed = true;
    }
    return changed;
}

function applyDraftPatch(action) {
    const type = normalizeStudioType(action.draft_type || action.kind || action.target_type);
    const draftId = action.draft_id || action.target_id || action.id || 'current';
    const record = findDraftRecord(draftId, type || state.selectedType);
    if (!record) return false;
    const patch = {...actionPatch(action), ...actionPatch(action, 'draft')};
    if (action.prompt && !patch.prompt) patch.prompt = action.prompt;
    const changed = assignAllowedFields(record.draft, patch, [
        'label', 'tag', 'mediaType', 'imgUrl', 'videoUrl', 'prompt', 'mode', 'model',
        'providerId', 'resolution', 'duration', 'aspectRatio', 'size', 'timbre',
        'refAssets', 'customRatioWidth', 'customRatioHeight'
    ]);
    if (changed) {
        state.selectedType = record.type;
        state.selectedDraftId = record.draft.id;
        state.subTab = subTabForType(record.type);
        const promptInput = document.getElementById('detailedPromptInput');
        if (promptInput && patch.prompt) promptInput.value = patch.prompt;
    }
    return changed;
}

function applyGroupPatch(action) {
    const type = normalizeStudioType(action.group_type || action.kind || action.target_type);
    const groupId = action.group_id || action.target_id || action.id || 'current';
    const record = findGroupRecord(groupId, type || state.selectedType);
    if (!record) return false;
    const changed = assignAllowedFields(record.group, actionPatch(action), [
        'title', 'desc', 'roughDesc', 'duration', 'timeRange', 'prompt'
    ]);
    if (changed) state.subTab = subTabForType(record.type);
    return changed;
}

function applyAddDraft(action) {
    const type = normalizeStudioType(action.group_type || action.draft_type || action.kind) || state.selectedType || 'keyElement';
    const record = findGroupRecord(action.group_id || 'current', type);
    if (!record) return false;
    const draftPatch = actionPatch(action, 'draft');
    const id = draftPatch.id || `${record.type}-draft-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const mediaType = draftPatch.mediaType || (record.type === 'shot' ? 'video' : record.type === 'audio' ? 'audio' : 'image');
    const draft = {
        id,
        label: draftPatch.label || 'Agent 草稿',
        tag: draftPatch.tag || 'Agent',
        mediaType,
        imgUrl: draftPatch.imgUrl || (mediaType === 'image' ? '/static/images/logo.png' : ''),
        videoUrl: draftPatch.videoUrl || '',
        prompt: draftPatch.prompt || '',
        mode: draftPatch.mode || (record.type === 'shot' ? '图生视频' : record.type === 'audio' ? '多模态音频生成' : ''),
        model: draftPatch.model || '',
        resolution: draftPatch.resolution || '1080p',
        duration: draftPatch.duration || (record.type === 'shot' ? '5s' : ''),
        aspectRatio: draftPatch.aspectRatio || '16:9',
        size: draftPatch.size || '1280x720',
        timbre: draftPatch.timbre || '',
        refAssets: Array.isArray(draftPatch.refAssets) ? [...draftPatch.refAssets] : []
    };
    record.group.drafts = record.group.drafts || [];
    record.group.drafts.push(draft);
    state.selectedType = record.type;
    state.selectedDraftId = draft.id;
    state.subTab = subTabForType(record.type);
    return true;
}

function applyBindAsset(action) {
    const assetId = action.asset_id || action.id || '';
    const url = action.url || action.asset_url || '';
    const name = action.name || action.asset_name || url || 'Agent 绑定素材';
    let asset = state.assets.find(item => (assetId && item.id === assetId) || (url && item.url === url) || (name && item.name === name));
    if (!asset) {
        asset = {
            id: assetId || `ast-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
            name,
            type: action.asset_type || action.kind || action.mediaType || 'image',
            isBound: true,
            url
        };
        state.assets.unshift(asset);
    } else {
        asset.isBound = true;
        if (url && !asset.url) asset.url = url;
        if (action.asset_type || action.kind) asset.type = action.asset_type || action.kind;
    }
    const type = normalizeStudioType(action.draft_type || action.target_type);
    const record = findDraftRecord(action.draft_id || action.target_id || 'current', type || state.selectedType);
    if (record && asset.url && asset.type === 'image') {
        record.draft.refAssets = record.draft.refAssets || [];
        if (!record.draft.refAssets.includes(asset.url)) record.draft.refAssets.push(asset.url);
    }
    return true;
}

function applySelectDraft(action) {
    const type = normalizeStudioType(action.draft_type || action.kind || action.target_type);
    const record = findDraftRecord(action.draft_id || action.target_id || action.id, type || state.selectedType);
    if (!record) return false;
    state.selectedType = record.type;
    state.selectedDraftId = record.draft.id;
    state.subTab = subTabForType(record.type);
    return true;
}

function applyAgentReplyToCurrentDraft(reply, userText, appliedActions = 0) {
    const draft = getCurrentDraft();
    if (!draft) return;
    if (appliedActions > 0) return;
    if (/确认|通过|定稿|锁定|采用/.test(userText)) {
        draft.tag = '已确认';
        renderLeftContent();
        updateMiddlePreview();
        return;
    }
    if (/修改|调整|优化|改写|提示词/.test(userText)) {
        draft.prompt = reply;
        document.getElementById('detailedPromptInput').value = reply;
        renderLeftContent();
        updateMiddlePreview();
    }
}

function handleChatKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAgentMessage();
    }
}

// 手动新建草稿卡片 (+)
function addNewDraftCard(groupId, type) {
    const promptText = prompt('请输入新草稿卡片的生成要求或提示词：');
    if (!promptText) return;

    const newId = `draft-${Date.now()}`;

    if (type === 'keyElement') {
        const item = state.keyElements.find(k => k.id === groupId);
        if (item) {
            item.drafts.push({
                id: newId,
                label: `自定义草稿`,
                tag: '手动',
                mediaType: 'image',
                imgUrl: 'https://picsum.photos/id/1069/1200/800',
                prompt: promptText,
                model: 'Flux.1',
                aspectRatio: '16:9'
            });
        }
    } else if (type === 'shot') {
        const item = state.shots.find(s => s.id === groupId);
        if (item) {
            item.drafts.push({
                id: newId,
                label: `自定义分镜`,
                tag: '手动',
                mediaType: 'video',
                videoUrl: '',
                prompt: promptText,
                mode: '图生视频',
                model: 'Sora'
            });
        }
    }

    renderLeftContent();
    selectDraftCard(newId, type);
}

function adjustDraftCardPrompt(groupId, text) {
    if (!text) return;
    sendAgentMessage(`对关键元素 ${groupId} 的当前草稿提出微调意见：${text}`);
}

function adjustShotPrompt(groupId, text) {
    if (!text) return;
    sendAgentMessage(`对分镜 ${groupId} 的当前草稿提出微调意见：${text}`);
}

function adjustAudioPrompt(groupId, text) {
    if (!text) return;
    sendAgentMessage(`对音频层 ${groupId} 的当前草稿提出微调意见：${text}`);
}

// === 项目切换 ===
function toggleProjectMenu() {
    const menu = document.getElementById('projectMenu');
    if (menu) {
        menu.classList.toggle('hidden');
        if (!menu.classList.contains('hidden')) loadProjectMenu();
    }
}

async function loadProjectMenu() {
    const container = document.getElementById('projectMenuList');
    if (!container) return;
    try {
        const res = await fetch('/api/project/list');
        const data = await res.json();
        const projects = data.projects || [];
        const activeId = data.active_project_id || '';
        container.innerHTML = projects.map(p => {
            const isActive = p.id === activeId;
            const icon = isActive ? '<i data-lucide="check" class="w-3 h-3 text-blue-400"></i>' : '<i data-lucide="folder" class="w-3 h-3 opacity-30"></i>';
            const time = p.updated_at ? p.updated_at.replace('T', ' ').slice(5, 16) : '';
            const delBtn = projects.length > 1 ? `<span class="del-proj-btn text-gray-600 hover:text-red-400 p-0.5" title="删除项目" onclick="event.stopPropagation();deleteProject('${p.id}','${escapeHtml(p.name)}')"><i data-lucide="trash-2" class="w-3 h-3"></i></span>` : '';
            return `<button class="w-full text-left px-3 py-2 text-xs ${isActive ? 'text-gray-100 bg-gray-700/50' : 'text-gray-300'} hover:bg-gray-700 flex items-center gap-2" onclick="switchProject('${p.id}')">
                ${icon}
                <span class="flex-1 truncate">${escapeHtml(p.name)}</span>
                <span class="text-[10px] text-gray-500">${time}</span>
                ${delBtn}
            </button>`;
        }).join('');
        lucide.createIcons();
    } catch (e) {
        container.innerHTML = '<div class="px-3 py-2 text-xs text-gray-500">加载失败</div>';
    }
}

async function switchProject(projectId) {
    try {
        const res = await fetch('/api/project/switch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ project_id: projectId })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.detail || '切换失败');
        applyProjectState(data.state);
        document.getElementById('projectMenu')?.classList.add('hidden');
        showToast(`已切换到项目：${(data.state || {}).project_name || projectId}`);
    } catch (err) {
        showToast('切换项目失败：' + (err.message || err));
    }
}

async function deleteProject(projectId, projectName) {
    if (!confirm(`确定删除项目「${projectName}」？此操作不可撤销。`)) return;
    try {
        const res = await fetch('/api/project/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ project_id: projectId })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.detail || '删除失败');
        applyProjectState(data.state);
        loadProjectMenu();
        showToast(`已删除项目：${projectName}`);
    } catch (err) {
        showToast('删除失败：' + (err.message || err));
    }
}

async function createNewProject() {
    const name = prompt('输入新项目名称：');
    if (!name || !name.trim()) return;
    const projectName = name.trim();

    try {
        const res = await fetch('/api/project/new', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: projectName })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.detail || '新建项目失败');
        applyProjectState(data.state);
        document.getElementById('projectMenu')?.classList.add('hidden');
        showToast(`已创建新项目：${projectName}`);
    } catch (err) {
        showToast('新建项目失败：' + (err.message || err));
    }
}

function applyProjectState(serverState) {
    if (!serverState) return;
    state.keyElements = serverState.keyElements || [];
    state.shots = serverState.shots || [];
    state.audioItems = serverState.audioItems || [];
    state.assets = serverState.assets || [];
    state.chatMessages = serverState.chatMessages || [];
    state.selectedDraftId = '';
    state.selectedType = 'keyElement';
    state.subTab = 'keyElements';

    // 选中第一个 draft
    const firstGroup = state.keyElements[0] || state.shots[0] || state.audioItems[0];
    if (firstGroup && firstGroup.drafts && firstGroup.drafts.length) {
        state.selectedDraftId = firstGroup.drafts[0].id;
        state.selectedType = state.keyElements.includes(firstGroup) ? 'keyElement'
            : state.shots.includes(firstGroup) ? 'shot' : 'audio';
    }

    document.getElementById('currentProjectName').textContent = serverState.project_name || '未命名项目';
    renderLeftContent();
    renderRightChat();
    updateMiddlePreview();
}

// 点击其他区域关闭项目菜单
document.addEventListener('click', (e) => {
    const switcher = document.getElementById('projectSwitcher');
    if (switcher && !switcher.contains(e.target)) {
        document.getElementById('projectMenu')?.classList.add('hidden');
    }
});

// === API 配置与动态模型选择 ===
// 从画布后端加载全局模型列表和 providers
async function loadCanvasApiConfig() {
    try {
        const [configRes, providersRes, skillsRes] = await Promise.all([
            fetch('/api/config'),
            fetch('/api/providers'),
            fetch('/api/plugins/flova-agent/config')
        ]);
        
        if (configRes.ok) {
            const config = await configRes.json();
            state.availableChatModels = (config.chat_models && config.chat_models.length) 
                ? config.chat_models 
                : DEFAULT_CHAT_MODELS;
            state.availableImageModels = (config.image_models && config.image_models.length)
                ? config.image_models
                : DEFAULT_IMAGE_MODELS;
            state.availableVideoModels = (config.video_models && config.video_models.length)
                ? config.video_models
                : DEFAULT_VIDEO_MODELS;
            console.log('[Studio] 已成功加载画布全局 API 配置');
        }

        if (providersRes.ok) {
            const pData = await providersRes.json();
            state.apiProviders = (pData.providers || []).filter(provider => provider.enabled !== false);
            console.log('[Studio] 已加载 ' + state.apiProviders.length + ' 个 API 平台');
        }

        if (skillsRes.ok) {
            const skillData = await skillsRes.json();
            state.skills = Array.isArray(skillData.skills) ? skillData.skills : [];
        }

        populateApiControls();
        refreshParamControlsBar(); // 刷新中间预览参数栏的模型下拉
    } catch (e) {
        console.warn('[Studio] 获取 API 配置失败，使用默认配置:', e);
    }
}

function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
}

function readApiError(data, fallback) {
    const detail = data?.detail || data?.message || data?.error;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail) return JSON.stringify(detail);
    return fallback;
}

// 默认后备模型列表（与 main.py 的全局变量对齐）
const DEFAULT_CHAT_MODELS = ['gpt-5.5', 'gpt-4o-mini', 'gemini-3.1-flash-image-preview-2k'];
const DEFAULT_IMAGE_MODELS = ['nano-banana-pro', 'gpt-image-2'];
const DEFAULT_VIDEO_MODELS = ['veo3-fast', 'sora-2', 'seedance2.0_vip'];
const STUDIO_ACTION_PROTOCOL_PROMPT = `
你正在驱动影视 Agent 工作台。用户在右侧 Agent 对话框里确认或修改的事项，如果会影响左侧故事板、中间预览提示词、草稿确认状态或资产绑定，必须在回复末尾追加一个 studio-actions JSON 块。给用户看的文字保持自然简短，JSON 块只给前端读取。

可用 action:
- add_group: 新建故事板分组（关键元素/分镜/音频）。字段：group_type(keyElement/shot/audio), title, desc, 可选 draft(单个草稿) 或 drafts(草稿数组)。
- update_draft: 修改草稿。字段：draft_type(keyElement/shot/audio), draft_id/current, patch。
- update_group: 修改故事板分组。字段：group_type(keyElement/shot/audio), group_id/current, patch。
- add_draft: 给某个分组新增草稿。字段：group_type, group_id/current, draft。若分组不存在会自动创建。
- confirm_draft: 确认草稿。字段：draft_type, draft_id/current。
- bind_asset: 绑定资产。字段：asset_id 或 name/url/type，可选 draft_type/draft_id。
- select_draft: 选中草稿。字段：draft_type, draft_id。

patch/draft 可包含：title, desc, roughDesc, timeRange, duration, label, tag, prompt, imgUrl, videoUrl, mode, model, resolution, aspectRatio, size, timbre, refAssets。

重要规则：
- 当用户要求从文档/素材中拆解关键元素或分镜时，必须使用 add_group 创建新分组，并在其中携带 draft。
- 不要只说“已创建”而不输出 studio-actions 块，否则前端不会有任何变化。
- 每个关键元素/分镜都应该有具体的 prompt（可执行的图片/视频生成提示词）。

格式示例：
\`\`\`studio-actions
[
  {"action":"add_group","group_type":"keyElement","title":"特效设定：太阳系二维化","desc":"太阳系逐渐被二维化的视觉特效设定","draft":{"label":"概念图","tag":"Agent","mediaType":"image","prompt":"太阳系行星逐渐被压平为二维平面，宇宙背景，科幻特效，8K"}},
  {"action":"add_group","group_type":"shot","title":"分镜1：全景—太阳系俯瞰","desc":"从远处俯瞰太阳系全貌","draft":{"label":"全景镜头","tag":"Agent","mediaType":"image","prompt":"宇宙深空俯瞰太阳系，行星轨道清晰可见，电影级采光"}}
]
\`\`\`
`;

// 初始化 state 中的模型字段
state.availableChatModels = DEFAULT_CHAT_MODELS;
state.availableImageModels = DEFAULT_IMAGE_MODELS;
state.availableVideoModels = DEFAULT_VIDEO_MODELS;
state.apiProviders = [];

// 从 apiProviders 中按 provider_id 提取模型列表
function providerModels(providerId, kind) {
    const p = state.apiProviders.find(p => p.id === providerId);
    if (!p) return [];
    const field = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : 'chat_models';
    return (p[field] && p[field].length) ? p[field] : [];
}

// 默认 provider
function defaultProviderId(kind) {
    return preferredProviderIdForKind(kind, apiProvidersFor(kind));
}

function preferredProviderIdForKind(kind, providers = apiProvidersFor(kind)) {
    const preferences = kind === 'video'
        ? ['volcengine', 'jimeng', 'apimart']
        : kind === 'image'
            ? ['custom-api', 'gemini-cli', 'custom-api-6']
            : ['custom-api', 'gemini-cli', 'custom-api-6'];
    for (const id of preferences) {
        if (providers.some(provider => provider.id === id)) return id;
    }
    return providers[0]?.id || 'comfly';
}

// 合并模型列表：provider 模型优先，全局模型兜底
function mergedModels(kind) {
    const globalList = kind === 'image' ? state.availableImageModels
        : kind === 'video' ? state.availableVideoModels
        : state.availableChatModels;
    const combined = new Set();
    state.apiProviders.forEach(p => {
        const field = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : 'chat_models';
        (p[field] || []).forEach(m => { if (m) combined.add(m); });
    });
    globalList.forEach(m => { if (m) combined.add(m); });
    return Array.from(combined);
}

// 填充所有模型下拉框
function apiProvidersFor(kind) {
    const field = kind === 'image' ? 'image_models' : kind === 'video' ? 'video_models' : 'chat_models';
    return state.apiProviders.filter(provider => Array.isArray(provider[field]) && provider[field].length);
}

function optionHtml(value, label, selected) {
    return `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
}

function populateProviderSelect(select, kind, selectedId) {
    if (!select) return '';
    const providers = apiProvidersFor(kind);
    const selected = providers.some(provider => provider.id === selectedId) ? selectedId : preferredProviderIdForKind(kind, providers);
    select.innerHTML = providers.length
        ? providers.map(provider => optionHtml(provider.id, provider.name || provider.id, selected)).join('')
        : '<option value="">暂无可用 API</option>';
    select.value = selected;
    select.disabled = !providers.length;
    return selected;
}

function populateModelSelect(select, providerId, kind, selectedModel) {
    if (!select) return '';
    const models = providerModels(providerId, kind);
    const selected = models.includes(selectedModel) ? selectedModel : (models[0] || '');
    select.innerHTML = models.length
        ? models.map(model => optionHtml(model, model, selected)).join('')
        : '<option value="">请先配置该 API 的模型</option>';
    select.value = selected;
    select.disabled = !providerId || !models.length;
    return selected;
}

function populateApiControls() {
    const providerSelect = document.getElementById('agentProviderSelect');
    const modelSelect = document.getElementById('agentModelSelect');
    const providerId = populateProviderSelect(providerSelect, 'chat', localStorage.getItem('studioAgentProvider') || '');
    populateModelSelect(modelSelect, providerId, 'chat', localStorage.getItem('studioAgentModel') || '');
    if (providerSelect) providerSelect.onchange = () => {
        localStorage.setItem('studioAgentProvider', providerSelect.value);
        const model = populateModelSelect(modelSelect, providerSelect.value, 'chat', '');
        localStorage.setItem('studioAgentModel', model);
    };
    if (modelSelect) modelSelect.onchange = () => localStorage.setItem('studioAgentModel', modelSelect.value);

    const skillSelect = document.getElementById('agentSkillSelect');
    if (skillSelect && state.skills.length) {
        const saved = localStorage.getItem('studioAgentSkill') || 'production-agent';
        const selected = state.skills.some(skill => skill.id === saved) ? saved : state.skills[0].id;
        skillSelect.innerHTML = state.skills.map(skill => optionHtml(skill.id, skill.name, selected)).join('');
        skillSelect.value = selected;
        skillSelect.onchange = () => localStorage.setItem('studioAgentSkill', skillSelect.value);
    }
}

function bindApiConfigUpdates() {
    try {
        const channel = new BroadcastChannel('studio-api');
        channel.onmessage = event => {
            if (event.data?.type === 'providers-changed') loadCanvasApiConfig();
        };
    } catch (_) {}
}

// 刷新中间预览参数控制栏（使用实时模型数据）
function refreshParamControlsBar() {
    updateMiddlePreview();
}

// 获取当前选中 draft 的引用
function getCurrentDraft() {
    if (state.selectedType === 'keyElement') {
        for (const ke of state.keyElements) {
            const found = ke.drafts.find(d => d.id === state.selectedDraftId);
            if (found) return found;
        }
    } else if (state.selectedType === 'shot') {
        for (const s of state.shots) {
            const found = s.drafts.find(d => d.id === state.selectedDraftId);
            if (found) return found;
        }
    } else if (state.selectedType === 'audio') {
        for (const a of state.audioItems) {
            const found = a.drafts.find(d => d.id === state.selectedDraftId);
            if (found) return found;
        }
    }
    return null;
}

const STUDIO_IMAGE_1K_SIZES = {
    '1:1': '1024x1024',
    '2:3': '1024x1536',
    '3:2': '1536x1024',
    '3:4': '1008x1344',
    '4:3': '1344x1008',
    '9:16': '720x1280',
    '16:9': '1280x720',
    '21:9': '1280x544',
    '9:21': '544x1280'
};

function studioImageSizeForRatio(ratio, customWidth = '', customHeight = '') {
    if (ratio !== 'custom') return STUDIO_IMAGE_1K_SIZES[ratio] || STUDIO_IMAGE_1K_SIZES['1:1'];
    const widthRatio = Number(customWidth);
    const heightRatio = Number(customHeight);
    if (!(widthRatio > 0) || !(heightRatio > 0)) return '';
    const parsedRatio = widthRatio / heightRatio;
    const longSide = 1536;
    const pixelLimit = 1572864;
    const rawWidth = parsedRatio >= 1 ? longSide : Math.min(longSide * parsedRatio, Math.sqrt(pixelLimit * parsedRatio));
    const rawHeight = parsedRatio >= 1 ? Math.min(longSide / parsedRatio, Math.sqrt(pixelLimit / parsedRatio)) : longSide;
    const width = Math.max(64, Math.floor(rawWidth / 16) * 16);
    const height = Math.max(64, Math.floor(rawHeight / 16) * 16);
    return `${width}x${height}`;
}

// === 生成操作：打通到画布后端 API ===
async function generateImage() {
    const draft = getCurrentDraft();
    if (!draft) { alert('请先在左侧选中一个关键元素草稿卡片'); return; }

    // 从当前 DOM 读取用户选择的参数
    const modelSelect = document.getElementById('modelSelect');
    const providerSelect = document.getElementById('imageProviderSelect');
    const aspectSelect = document.getElementById('aspectSelect');
    const providerId = providerSelect?.value || draft.providerId || '';
    const model = modelSelect?.value || draft.model || '';
    const ratioSelection = aspectSelect ? aspectSelect.value : (draft.aspectRatio || '1:1');
    const customWidth = document.getElementById('imageCustomRatioWidth')?.value || draft.customRatioWidth || '';
    const customHeight = document.getElementById('imageCustomRatioHeight')?.value || draft.customRatioHeight || '';
    const size = studioImageSizeForRatio(ratioSelection, customWidth, customHeight);
    const aspectRatio = ratioSelection === 'custom' ? `${customWidth}:${customHeight}` : ratioSelection;
    const prompt = document.getElementById('detailedPromptInput').value || draft.prompt;

    const refs = (draft.refAssets || []).map(url => ({ url, role: 'reference' }));
    if (!providerId || !model) {
        showToast('请先选择图片 API 和对应模型');
        return;
    }
    if (!size || (ratioSelection === 'custom' && (!Number(customWidth) || !Number(customHeight)))) {
        showToast('请输入有效的自定义图片比例');
        return;
    }

    draft.aspectRatio = ratioSelection;
    draft.customRatioWidth = customWidth;
    draft.customRatioHeight = customHeight;
    draft.size = size;

    showToast('正在提交生图任务...');

    try {
        const res = await fetch('/api/canvas-image-tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                provider_id: providerId,
                model,
                size,
                aspect_ratio: aspectRatio,
                reference_images: refs.slice(0, 5)
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '生图请求失败'));
        if (data.task_id) {
            showToast('生图任务已创建：' + data.task_id);
            // 异步轮询结果
            pollAndPreviewImage(data.task_id, draft);
        } else if (data.images) {
            draft.imgUrl = data.images[0];
            updateMiddlePreview();
            showToast('图片已生成！');
        } else {
            showToast('提交成功，等待异步生成');
        }
    } catch (err) {
        console.error('[Studio] 生图失败:', err);
        showToast(err.message || '生图请求失败，请检查 API 配置');
    }
}

async function pollAndPreviewImage(taskId, draft) {
    let attempts = 0;
    while (attempts < 30) {
        try {
            const res = await fetch('/api/canvas-image-tasks/' + encodeURIComponent(taskId));
            if (res.status === 404) { showToast('任务丢失，请重试'); return; }
            const data = await res.json();
            if (data.status === 'succeeded' && data.result && data.result.images && data.result.images.length) {
                draft.imgUrl = data.result.images[0];
                updateMiddlePreview();
                showToast('图片渲染完成！');
                return;
            }
            if (data.status === 'failed') {
                showToast('生成失败: ' + (data.error || '未知错误'));
                return;
            }
        } catch (e) { /* 静默重试 */ }
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
    }
    showToast('轮询超时，请手动刷新');
}

async function generateVideo() {
    const draft = getCurrentDraft();
    if (!draft) { alert('请先在左侧选中一个分镜草稿卡片'); return; }

    const modeSelect = document.getElementById('videoModeSelect');
    const videoModelSelect = document.getElementById('videoModelSelect');
    const providerSelect = document.getElementById('videoProviderSelect');
    const resolutionSelect = document.getElementById('videoResolutionSelect');
    const durationSelect = document.getElementById('durationSelect');
    const aspectSelect = document.getElementById('videoAspectSelect');
    const mode = modeSelect ? modeSelect.value : (draft.mode || '全能参考');
    const providerId = providerSelect?.value || draft.providerId || '';
    const model = videoModelSelect?.value || draft.model || '';
    const resolution = resolutionSelect?.value || draft.resolution || '1080p';
    const durationStr = durationSelect ? durationSelect.value : (draft.duration || '5s');
    const duration = parseInt(durationStr) || 5;
    const prompt = document.getElementById('detailedPromptInput').value || draft.prompt;
    const aspectRatio = aspectSelect?.value || draft.aspectRatio || '16:9';

    const imageRefs = (draft.refAssets || []).map((url, index) => ({
        url,
        role: index === 0 ? 'first_frame' : index === 1 ? 'last_frame' : 'reference'
    }));
    if (!providerId || !model) {
        showToast('请先选择视频 API 和对应模型');
        return;
    }

    showToast('正在提交视频生成任务...');

    try {
        const res = await fetch('/api/canvas-video', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                provider_id: providerId,
                model,
                duration,
                resolution,
                aspect_ratio: aspectRatio,
                images: imageRefs.slice(0, 2),
                enhance_prompt: mode === '全能参考',
                multimodal: mode === '对口型数字人'
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '视频生成请求失败'));

        const videoUrl = data.video_url || data.videos?.[0] || data.images?.[0];
        if (videoUrl) {
            draft.videoUrl = videoUrl;
            updateMiddlePreview();
            showToast('视频已生成！');
        } else {
            showToast(data.task_id ? `视频任务已提交：${data.task_id}` : '视频任务已提交');
        }
    } catch (err) {
        console.error('[Studio] 生成视频失败:', err);
        showToast(err.message || '视频生成请求失败，请检查 API 配置');
    }
}

async function generateAudio() {
    const draft = getCurrentDraft();
    if (!draft) { alert('请先在左侧选中一个音频层草稿卡片'); return; }

    const prompt = document.getElementById('detailedPromptInput').value || draft.prompt;
    const provider = document.getElementById('audioProviderSelect')?.value || draft.providerId || '';
    const model = document.getElementById('audioModelSelect')?.value || draft.model || '';
    const mode = document.getElementById('audioModeSelect')?.value || draft.mode || '多模态音频生成';
    const timbre = document.getElementById('audioVoiceSelect')?.value || draft.timbre || '深邃男声 (Deep Narrator)';
    if (!provider || !model) {
        showToast('请先选择音频规划 API 和对应模型');
        return;
    }
    showToast('正在生成音频规划...');

    try {
        const res = await fetch('/api/canvas-llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: `请根据以下内容生成可执行的音频层规划，生成模式：${mode}，目标音色：${timbre}。包含旁白、对白、环境音、音乐、时间点和音色建议。不要声称已经生成音频文件。\n\n${prompt}`,
                system_prompt: state.skills.find(skill => skill.id === 'production-agent')?.system_prompt || '',
                provider,
                model,
                ms_model: provider === 'modelscope' ? model : '',
                messages: []
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '音频规划失败'));
        draft.prompt = String(data.text || draft.prompt);
        draft.mode = mode;
        draft.timbre = timbre;
        document.getElementById('detailedPromptInput').value = draft.prompt;
        showToast('音频规划已生成');
    } catch (err) {
        console.error('[Studio] 音频合成失败:', err);
        showToast(err.message || '音频规划失败');
    }
}

function saveDraftParams() {
    const draft = getCurrentDraft();
    if (!draft) return;

    const modelSelect = document.getElementById('modelSelect') || document.getElementById('videoModelSelect');
    if (modelSelect) draft.model = modelSelect.value;

    const providerSelect = document.getElementById('imageProviderSelect') || document.getElementById('videoProviderSelect') || document.getElementById('audioProviderSelect');
    if (providerSelect) draft.providerId = providerSelect.value;

    const audioModelSelect = document.getElementById('audioModelSelect');
    if (audioModelSelect) draft.model = audioModelSelect.value;

    const aspectSelect = document.getElementById('aspectSelect');
    if (aspectSelect) {
        draft.aspectRatio = aspectSelect.value;
        draft.customRatioWidth = document.getElementById('imageCustomRatioWidth')?.value || draft.customRatioWidth || '';
        draft.customRatioHeight = document.getElementById('imageCustomRatioHeight')?.value || draft.customRatioHeight || '';
        draft.size = studioImageSizeForRatio(draft.aspectRatio, draft.customRatioWidth, draft.customRatioHeight);
    }

    const videoAspectSelect = document.getElementById('videoAspectSelect');
    if (videoAspectSelect) draft.aspectRatio = videoAspectSelect.value;

    const videoResolutionSelect = document.getElementById('videoResolutionSelect');
    if (videoResolutionSelect) draft.resolution = videoResolutionSelect.value;

    const durationSelect = document.getElementById('durationSelect');
    if (durationSelect) draft.duration = durationSelect.value;

    const modeSelect = document.getElementById('videoModeSelect');
    if (modeSelect) draft.mode = modeSelect.value;

    const audioModeSelect = document.getElementById('audioModeSelect');
    if (audioModeSelect) draft.mode = audioModeSelect.value;

    const audioVoiceSelect = document.getElementById('audioVoiceSelect');
    if (audioVoiceSelect) draft.timbre = audioVoiceSelect.value;

    draft.prompt = document.getElementById('detailedPromptInput').value || draft.prompt;

    showToast('参数已保存到草稿卡片');
}

// Toast 提示
function showToast(msg) {
    let toast = document.getElementById('studioToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'studioToast';
        toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1e212b;color:#f3f4f6;padding:10px 24px;border-radius:10px;border:1px solid #3b82f6;font-size:13px;z-index:9999;transition:opacity 0.3s;pointer-events:none;';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.opacity = '1';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { toast.style.opacity = '0'; }, 3000);
}

// 聊天文件上传
function triggerChatUpload() {
    document.getElementById('chatFileInput').click();
}

async function handleChatFileUpload(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    for (const file of files) {
        await uploadFileToPending(file);
    }
    e.target.value = '';
}

// 将文件上传并加入待发送附件列表
async function uploadFileToPending(file) {
    const form = new FormData();
    form.append('files', file);
    try {
        showToast(`正在上传：${file.name}`);
        const response = await fetch('/api/ai/upload', {method: 'POST', body: form});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(readApiError(data, '素材上传失败'));
        const uploaded = data.files?.[0];
        if (!uploaded?.url) throw new Error('上传接口没有返回素材地址');
        state.pendingAttachments.push({
            id: `ast-${Date.now()}-${Math.random().toString(36).slice(2,6)}`,
            name: uploaded.name || file.name,
            type: uploaded.kind || 'file',
            url: uploaded.url
        });
        renderPendingAttachments();
        showToast(`已添加：${uploaded.name || file.name}`);
    } catch (error) {
        showToast(error.message || '素材上传失败');
    }
}

// 渲染待发送附件预览
function renderPendingAttachments() {
    const container = document.getElementById('pendingAttachments');
    if (!container) return;
    if (!state.pendingAttachments.length) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }
    container.style.display = 'flex';
    container.innerHTML = state.pendingAttachments.map((att, idx) => `
        <div class="attachment-chip">
            <i data-lucide="${att.type === 'image' ? 'image' : att.type === 'video' ? 'video' : 'file-text'}" class="w-3.5 h-3.5"></i>
            <span class="attachment-name">${escapeHtml(att.name)}</span>
            <button class="attachment-remove" onclick="removePendingAttachment(${idx})" title="移除">
                <i data-lucide="x" class="w-3 h-3"></i>
            </button>
        </div>
    `).join('');
    lucide.createIcons();
}

// 移除待发送附件
function removePendingAttachment(idx) {
    state.pendingAttachments.splice(idx, 1);
    renderPendingAttachments();
}

// 拖拽上传支持
function handleChatDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    const box = document.getElementById('chatInputBox');
    if (box) box.classList.add('drag-over');
}

function handleChatDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    const box = document.getElementById('chatInputBox');
    if (box && !box.contains(e.relatedTarget)) box.classList.remove('drag-over');
}

async function handleChatDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    const box = document.getElementById('chatInputBox');
    if (box) box.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;
    for (const file of files) {
        await uploadFileToPending(file);
    }
}

// === 后端状态同步 ===
// 后端执行 studio-actions 后返回完整状态快照，前端整体替换并重新渲染
function refreshStateFromBackend(serverState) {
    if (!serverState) return;

    // 替换故事板数据
    if (Array.isArray(serverState.keyElements)) state.keyElements = serverState.keyElements;
    if (Array.isArray(serverState.shots)) state.shots = serverState.shots;
    if (Array.isArray(serverState.audioItems)) state.audioItems = serverState.audioItems;
    if (Array.isArray(serverState.assets)) state.assets = serverState.assets;

    // 确保当前选中的 draft 仍然存在，否则选中第一个
    const currentStillExists = findDraftRecord(state.selectedDraftId, state.selectedType);
    if (!currentStillExists) {
        const firstGroup = (state.keyElements[0] || state.shots[0] || state.audioItems[0]);
        if (firstGroup && firstGroup.drafts && firstGroup.drafts.length) {
            state.selectedDraftId = firstGroup.drafts[0].id;
            state.selectedType = state.keyElements.includes(firstGroup) ? 'keyElement'
                : state.shots.includes(firstGroup) ? 'shot' : 'audio';
            state.subTab = subTabForType(state.selectedType);
        }
    }

    // 重新渲染所有面板
    renderLeftContent();
    updateMiddlePreview();
    if (state.leftTab === 'uncategorized') renderUncategorizedAssets();
}

// === 工作流面板 ===
const WF_PHASES = [
    {name: 'story', label: '编剧', icon: 'pen-tool'},
    {name: 'storyboard', label: '分镜', icon: 'layout-grid'},
    {name: 'image', label: '关键帧', icon: 'image'},
    {name: 'video', label: '视频', icon: 'film'},
    {name: 'audio', label: '音频', icon: 'music'},
    {name: 'edit', label: '剪辑', icon: 'scissors'},
];
let wfEventSource = null;

function renderWorkflowPhases(phaseStates = {}) {
    const container = document.getElementById('workflowPhases');
    if (!container) return;
    container.innerHTML = WF_PHASES.map(p => {
        const st = phaseStates[p.name] || 'pending';
        const icon = st === 'completed' ? 'check-circle' : st === 'running' ? 'loader' : st === 'failed' ? 'x-circle' : p.icon;
        return `<div class="wf-phase ${st}" title="${p.label}: ${st}">
            <i data-lucide="${icon}" class="wf-phase-icon ${st === 'running' ? 'animate-spin' : ''}"></i>
            <span>${p.label}</span>
        </div>`;
    }).join('');
    lucide.createIcons();
}

async function startWorkflow() {
    const btn = document.getElementById('workflowRunBtn');
    if (btn) btn.disabled = true;

    try {
        const res = await fetch('/api/workflow/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({goal: '自动生成完整影视项目'})
        });
        const data = await res.json();
        if (!data.ok) {
            showToast(data.message || '启动失败');
            if (btn) btn.disabled = false;
            return;
        }
        showToast('工作流已启动');
        subscribeWorkflowEvents();
    } catch (e) {
        showToast('工作流启动失败: ' + e.message);
        if (btn) btn.disabled = false;
    }
}

function subscribeWorkflowEvents() {
    if (wfEventSource) wfEventSource.close();

    const phaseStates = {};
    WF_PHASES.forEach(p => phaseStates[p.name] = 'pending');
    renderWorkflowPhases(phaseStates);

    wfEventSource = new EventSource('/api/workflow/events');
    wfEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.event === 'phase_started') {
                phaseStates[data.phase] = 'running';
                renderWorkflowPhases(phaseStates);
            } else if (data.event === 'phase_completed') {
                phaseStates[data.phase] = 'completed';
                renderWorkflowPhases(phaseStates);
                showToast(`${data.label} 完成：${data.detail || ''}`);
            } else if (data.event === 'workflow_done') {
                showToast('工作流全部完成！');
                wfEventSource.close();
                wfEventSource = null;
                const btn = document.getElementById('workflowRunBtn');
                if (btn) btn.disabled = false;
                // 刷新故事板（工作流可能添加了新 draft）
                fetch('/api/project/state').then(r => r.json()).then(s => refreshStateFromBackend(s));
            } else if (data.event === 'workflow_failed') {
                phaseStates[data.phase || ''] = 'failed';
                renderWorkflowPhases(phaseStates);
                showToast('工作流失败: ' + (data.error || ''));
                wfEventSource.close();
                wfEventSource = null;
                const btn = document.getElementById('workflowRunBtn');
                if (btn) btn.disabled = false;
            }
        } catch (_) {}
    };
    wfEventSource.onerror = () => {
        wfEventSource.close();
        wfEventSource = null;
        const btn = document.getElementById('workflowRunBtn');
        if (btn) btn.disabled = false;
    };
}
