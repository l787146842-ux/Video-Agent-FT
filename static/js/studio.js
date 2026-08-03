/**
 * FTDYB - 影视创作工作台核心 JavaScript
 */

// 全局状态管理（初始为空，DOMContentLoaded 时从后端 API 加载）
const state = {
    leftTab: 'storyboard', // storyboard | uncategorized
    subTab: 'keyElements', // keyElements | shots | audio
    showAllAssets: false,
    selectedDraftId: '',
    selectedType: 'keyElement', // keyElement | shot | audio
    isPromptCollapsed: false,
    apiProviders: [],
    skills: [],
    agentBusy: false,
    pendingAttachments: [], // 输入框内待发送的附件

    // 故事板数据（从后端加载）
    keyElements: [],
    shots: [],
    audioItems: [],
    assets: [],
    chatMessages: []
};

// 初始化页面
document.addEventListener('DOMContentLoaded', async () => {
    initSplitters();
    initCanvasSplitter();
    initChatResizeHandle();
    initPreviewUpload();
    // 从后端加载持久化状态（替代硬编码 demo 数据）
    await loadStateFromBackend();
    renderLeftContent();
    renderRightChat();
    updateMiddlePreview();
    await loadCanvasApiConfig();
    bindApiConfigUpdates();
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
        state.documents = Array.isArray(serverState.documents) ? serverState.documents : [];
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

    // 中间预览区域上下横向拖拽（底部栏固定，伸缩提示词区域）
    setupDrag(splitterPreview, (deltaX, deltaY) => {
        if (state.isPromptCollapsed) return;
        const newHeight = Math.max(100, Math.min(600, previewBottom.offsetHeight - deltaY));
        previewBottom.style.height = newHeight + 'px';
        previewBottom.style.flex = 'none';
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

// 初始化中间预览区上传/替换媒体功能
function initPreviewUpload() {
    const previewTop = document.getElementById('previewTop');
    if (!previewTop) return;

    // 双击预览区触发上传
    previewTop.addEventListener('dblclick', () => triggerPreviewUpload());

    // 拖拽上传支持
    previewTop.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        previewTop.classList.add('preview-dragover');
    });
    previewTop.addEventListener('dragleave', (e) => {
        e.preventDefault();
        previewTop.classList.remove('preview-dragover');
    });
    previewTop.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        previewTop.classList.remove('preview-dragover');
        const files = Array.from(e.dataTransfer?.files || []);
        if (files.length) await handlePreviewMediaUpload(files[0]);
    });
}

function triggerPreviewUpload() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*,video/*,audio/*';
    input.onchange = async () => {
        const file = input.files?.[0];
        if (file) await handlePreviewMediaUpload(file);
    };
    input.click();
}

// 预览区右键菜单：替换媒体
function showPreviewReplaceMenu(event) {
    event.preventDefault();
    event.stopPropagation();
    document.getElementById('previewReplaceMenu')?.remove();
    const menu = document.createElement('div');
    menu.id = 'previewReplaceMenu';
    menu.className = 'draft-menu';
    menu.style.left = Math.min(event.clientX, window.innerWidth - 160) + 'px';
    menu.style.top = Math.min(event.clientY, window.innerHeight - 80) + 'px';
    menu.innerHTML = `
        <button onclick="closePreviewReplaceMenu();triggerPreviewUpload()"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>替换媒体文件</button>`;
    document.body.appendChild(menu);
    lucide.createIcons();
    setTimeout(() => document.addEventListener('click', closePreviewReplaceMenu, {once: true}), 0);
}

function closePreviewReplaceMenu() {
    document.getElementById('previewReplaceMenu')?.remove();
}

async function handlePreviewMediaUpload(file) {
    if (!state.selectedDraftId) {
        showToast('请先在左侧选择一个草稿卡片');
        return;
    }
    const form = new FormData();
    form.append('files', file);
    try {
        showToast(`正在上传：${file.name}`);
        const response = await fetch('/api/ai/upload', {method: 'POST', body: form});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(readApiError(data, '媒体上传失败'));
        const uploaded = data.files?.[0];
        if (!uploaded?.url) throw new Error('上传接口没有返回媒体地址');

        // 更新当前草稿的媒体 URL
        const rec = findDraftRecord(state.selectedDraftId, state.selectedType);
        if (rec) {
            const kind = uploaded.kind || 'image';
            if (kind === 'video') {
                rec.draft.mediaType = 'video';
                rec.draft.videoUrl = uploaded.url;
            } else if (kind === 'audio') {
                rec.draft.mediaType = 'audio';
            } else {
                rec.draft.mediaType = 'image';
                rec.draft.imgUrl = uploaded.url;
            }
            rec.draft.tag = '已上传';
            renderLeftContent();
            updateMiddlePreview();
            await persistBoard();
            showToast(`已替换媒体：${uploaded.name || file.name}`);
        }
    } catch (error) {
        showToast(error.message || '媒体上传失败');
    }
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
                             onclick="selectDraftCard('${d.id}', 'keyElement')"
                             oncontextmenu="showDraftMenu(event, '${d.id}', 'keyElement', '${item.id}')">
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
                    <span class="sb-badge" style="background:rgba(139, 92, 246, 0.15); color:#a78bfa">${escapeHtml(item.shotType || '分镜')}</span>
                </div>
                ${(item.sceneRefs && item.sceneRefs.length) ? `
                    <div class="scene-refs">场景:
                        ${item.sceneRefs.map(ref => `
                            <span class="scene-ref-chip" onclick="jumpToElementByTitle('${escapeHtml(String(ref)).replace(/'/g, "\\'")}')" title="点击跳转到该关键元素">${escapeHtml(String(ref))}</span>
                        `).join('')}
                    </div>` : ''}
                <p class="sb-desc">${item.roughDesc}</p>

                <!-- 分镜草稿卡片横排 -->
                <div class="draft-cards-row">
                    <button class="add-card-btn" title="手动生成视频分镜" onclick="addNewDraftCard('${item.id}', 'shot')">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                    </button>
                    ${item.drafts.map(d => `
                        <div class="draft-card ${state.selectedDraftId === d.id ? 'active' : ''}"
                             style="background-color:#2e3346"
                             onclick="selectDraftCard('${d.id}', 'shot')"
                             oncontextmenu="showDraftMenu(event, '${d.id}', 'shot', '${item.id}')">
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
                             onclick="selectDraftCard('${d.id}', 'audio')"
                             oncontextmenu="showDraftMenu(event, '${d.id}', 'audio', '${item.id}')">
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

// 按 title 跳转到关键元素（分镜的 sceneRefs chip 点击）
function jumpToElementByTitle(title) {
    const el = state.keyElements.find(k => k.title === title);
    if (!el) { showToast(`未找到关键元素「${title}」`); return; }
    state.subTab = 'keyElements';
    document.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    if (el.drafts && el.drafts.length) {
        state.selectedDraftId = el.drafts[0].id;
        state.selectedType = 'keyElement';
    }
    renderLeftContent();
    updateMiddlePreview();
}

// === 文档面板（项目文档 + Skill 文档） ===
const docsPanelState = { skillDocs: [], current: null, editing: false, viewMode: 'read' };

// 轻量 Markdown → HTML 渲染（无外部依赖）
function renderMarkdown(src) {
    if (!src) return '<p class="docs-empty">暂无内容</p>';
    const lines = src.split('\n');
    let html = '';
    let inUl = false, inOl = false, inBlock = false;
    const inline = (t) => escapeHtml(t)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>');
    const closeList = () => { if (inUl) { html += '</ul>'; inUl = false; } if (inOl) { html += '</ol>'; inOl = false; } };
    const closeBlock = () => { if (inBlock) { html += '</blockquote>'; inBlock = false; } };
    for (const raw of lines) {
        const line = raw.trimEnd();
        if (/^### /.test(line)) { closeList(); closeBlock(); html += `<h3>${inline(line.slice(4))}</h3>`; }
        else if (/^## /.test(line)) { closeList(); closeBlock(); html += `<h2>${inline(line.slice(3))}</h2>`; }
        else if (/^# /.test(line)) { closeList(); closeBlock(); html += `<h1>${inline(line.slice(2))}</h1>`; }
        else if (/^> /.test(line)) { closeList(); if (!inBlock) { html += '<blockquote>'; inBlock = true; } html += `<p>${inline(line.slice(2))}</p>`; }
        else if (/^[-*] /.test(line)) { closeBlock(); if (inOl) { html += '</ol>'; inOl = false; } if (!inUl) { html += '<ul>'; inUl = true; } html += `<li>${inline(line.slice(2))}</li>`; }
        else if (/^\d+\. /.test(line)) { closeBlock(); if (inUl) { html += '</ul>'; inUl = false; } if (!inOl) { html += '<ol>'; inOl = true; } html += `<li>${inline(line.replace(/^\d+\. /, ''))}</li>`; }
        else if (line.trim() === '') { closeList(); closeBlock(); }
        else { closeList(); closeBlock(); html += `<p>${inline(line)}</p>`; }
    }
    closeList(); closeBlock();
    return html;
}

function setDocsViewMode(mode) {
    docsPanelState.viewMode = mode;
    document.getElementById('docsModeRead')?.classList.toggle('active', mode === 'read');
    document.getElementById('docsModeMd')?.classList.toggle('active', mode === 'md');
    if (docsPanelState.editing) return; // 编辑模式不受影响
    const rendered = document.getElementById('docsRendered');
    const viewer = document.getElementById('docsViewer');
    if (mode === 'read') {
        rendered.innerHTML = renderMarkdown(viewer.textContent);
        rendered.classList.remove('hidden');
        viewer.classList.add('hidden');
    } else {
        rendered.classList.add('hidden');
        viewer.classList.remove('hidden');
    }
}

async function openDocsPanel(targetName = '') {
    const panel = document.getElementById('docsPanel');
    if (!panel) return;
    panel.classList.remove('hidden');
    try {
        const res = await fetch('/api/skills/docs');
        const data = await res.json();
        docsPanelState.skillDocs = Array.isArray(data.docs) ? data.docs : [];
    } catch (_) { docsPanelState.skillDocs = []; }
    renderDocsList();

    // 定位：优先项目文档，其次 Skill 文档，否则第一个
    if (targetName) {
        const pd = (state.documents || []).find(d => d.name === targetName);
        if (pd) { selectDoc('project', targetName); lucide.createIcons(); return; }
        const sd = docsPanelState.skillDocs.find(d => d.slug === targetName || d.name === targetName);
        if (sd) { selectDoc('skill', sd.slug); lucide.createIcons(); return; }
    }
    const first = (state.documents || [])[0];
    if (first) selectDoc('project', first.name);
    else if (docsPanelState.skillDocs[0]) selectDoc('skill', docsPanelState.skillDocs[0].slug);
    lucide.createIcons();
}

function closeDocsPanel() {
    document.getElementById('docsPanel')?.classList.add('hidden');
    docsPanelState.editing = false;
}

function renderDocsList() {
    const list = document.getElementById('docsFileList');
    if (!list) return;
    const projDocs = state.documents || [];
    const cur = docsPanelState.current;
    // 上传素材（仅文本类）
    const textAssets = (state.assets || []).filter(a => /\.(md|txt|pdf)$/i.test(a.name || ''));
    list.innerHTML = `
        <div class="docs-section-title">📁 项目文档</div>
        ${projDocs.length ? projDocs.map(d => `
            <div class="docs-file ${cur?.kind === 'project' && cur?.key === d.name ? 'active' : ''}"
                 onclick="selectDoc('project', '${escapeHtml(d.name).replace(/'/g, "\\'")}')">
                <i data-lucide="file-text" class="w-3.5 h-3.5"></i><span>${escapeHtml(d.name)}</span>
            </div>`).join('') : '<div class="docs-empty">暂无（Agent 拆解时会自动产出）</div>'}
        <div class="docs-section-title">📎 上传素材</div>
        ${textAssets.length ? textAssets.map(a => `
            <div class="docs-file" onclick="openAssetDoc('${escapeHtml(a.name).replace(/'/g, "\\'")}')">
                <i data-lucide="file" class="w-3.5 h-3.5"></i><span>${escapeHtml(a.name)}</span>
            </div>`).join('') : '<div class="docs-empty">暂无上传的文档素材</div>'}
        <div class="docs-section-title">🧩 Skill 文档</div>
        ${(() => {
            const selId = document.getElementById('agentSkillSelect')?.value || '';
            const activeSlug = selId.startsWith('doc:') ? selId.slice(4) : '';
            const visible = activeSlug ? docsPanelState.skillDocs.filter(d => d.slug === activeSlug) : docsPanelState.skillDocs;
            return visible.length ? visible.map(d => `
            <div class="docs-file ${cur?.kind === 'skill' && cur?.key === d.slug ? 'active' : ''}"
                 onclick="selectDoc('skill', '${d.slug}')">
                <i data-lucide="book-open" class="w-3.5 h-3.5"></i><span>${escapeHtml(d.name)}</span>
            </div>`).join('') : '<div class="docs-empty">在聊天框选择 Skill 后显示</div>';
        })()}
        <button class="docs-new-btn" onclick="createNewDoc()">+ 新建文档</button>`;
    lucide.createIcons();
}

function openAssetDoc(name) {
    const asset = (state.assets || []).find(a => a.name === name);
    if (asset?.url) { window.open(asset.url, '_blank'); return; }
    showToast('该素材无预览内容，仅作为引用资产使用');
}

async function createNewDoc() {
    const name = prompt('文档名称：', '无标题.md');
    if (!name || !name.trim()) return;
    const docName = name.trim().endsWith('.md') ? name.trim() : name.trim() + '.md';
    try {
        const res = await fetch('/api/project/document', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: docName, content: ''})
        });
        if (!res.ok) throw new Error('创建失败');
        const data = await res.json();
        state.documents = Array.isArray(data.documents) ? data.documents : (state.documents || []);
        renderDocsList();
        selectDoc('project', docName);
        // 自动进入编辑模式
        toggleDocEdit();
    } catch (e) {
        showToast(e.message || '新建文档失败');
    }
}

function selectDoc(kind, key) {
    docsPanelState.current = { kind, key };
    docsPanelState.editing = false;
    let name = key, content = '';
    if (kind === 'project') {
        const d = (state.documents || []).find(x => x.name === key);
        content = d?.content || '';
        name = key + (d?.updated_at ? ` · ${d.updated_at.replace('T', ' ')}` : '');
    } else {
        const d = docsPanelState.skillDocs.find(x => x.slug === key);
        content = d?.content || '';
        name = d?.name || key;
    }
    document.getElementById('docsCurrentName').textContent = name;
    const viewer = document.getElementById('docsViewer');
    const rendered = document.getElementById('docsRendered');
    viewer.textContent = content;
    // 根据当前视图模式显示
    if (docsPanelState.viewMode === 'read') {
        rendered.innerHTML = renderMarkdown(content);
        rendered.classList.remove('hidden');
        viewer.classList.add('hidden');
    } else {
        rendered.classList.add('hidden');
        viewer.classList.remove('hidden');
    }
    document.getElementById('docsEditor').classList.add('hidden');
    document.getElementById('docsSaveBtn').classList.add('hidden');
    document.getElementById('docsEditBtn').textContent = '编辑';
    renderDocsList();
}

function toggleDocEdit() {
    if (!docsPanelState.current) return;
    const viewer = document.getElementById('docsViewer');
    const rendered = document.getElementById('docsRendered');
    const editor = document.getElementById('docsEditor');
    if (docsPanelState.editing) {
        // 取消编辑，恢复查看模式
        docsPanelState.editing = false;
        editor.classList.add('hidden');
        if (docsPanelState.viewMode === 'read') {
            rendered.innerHTML = renderMarkdown(viewer.textContent);
            rendered.classList.remove('hidden');
            viewer.classList.add('hidden');
        } else {
            rendered.classList.add('hidden');
            viewer.classList.remove('hidden');
        }
        document.getElementById('docsSaveBtn').classList.add('hidden');
        document.getElementById('docsEditBtn').textContent = '编辑';
        return;
    }
    docsPanelState.editing = true;
    editor.value = viewer.textContent;
    rendered.classList.add('hidden');
    viewer.classList.add('hidden');
    editor.classList.remove('hidden');
    document.getElementById('docsSaveBtn').classList.remove('hidden');
    document.getElementById('docsEditBtn').textContent = '取消';
}

async function saveCurrentDoc() {
    const cur = docsPanelState.current;
    if (!cur || !docsPanelState.editing) return;
    const content = document.getElementById('docsEditor').value;
    try {
        if (cur.kind === 'project') {
            const res = await fetch('/api/project/document', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: cur.key, content})
            });
            if (!res.ok) throw new Error(readApiError(await res.json().catch(() => ({})), '保存失败'));
            const d = (state.documents || []).find(x => x.name === cur.key);
            if (d) d.content = content;
        } else {
            const res = await fetch('/api/skills/docs/' + encodeURIComponent(cur.key), {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content})
            });
            if (!res.ok) throw new Error(readApiError(await res.json().catch(() => ({})), '保存失败'));
            const d = docsPanelState.skillDocs.find(x => x.slug === cur.key);
            if (d) d.content = content;
            // Skill 内容即流程——同步刷新下拉框数据里的 system_prompt
            const sk = state.skills.find(s => s.id === 'doc:' + cur.key);
            if (sk) sk.system_prompt = content;
        }
        showToast('文档已保存');
        selectDoc(cur.kind, cur.key);
    } catch (e) {
        showToast(e.message || '保存失败');
    }
}

// Skill 下拉旁「查看」按钮：打开当前选中 Skill 的文档
function viewCurrentSkillDoc() {
    const skillId = document.getElementById('agentSkillSelect')?.value || '';
    if (skillId.startsWith('doc:')) openDocsPanel(skillId.slice(4));
    else openDocsPanel();
}

// 批量生成（前端按钮触发，调用后端 /api/generate/batch-image）
async function batchGenerate(target) {
    const providerSelect = document.getElementById('imageProviderSelect');
    const modelSelect = document.getElementById('imageModelSelect');
    const providerId = providerSelect?.value || '';
    const model = modelSelect?.value || '';
    if (!providerId || !model) {
        showToast('请先在中间预览区选择图片 API 和模型');
        return;
    }
    const label = target === 'all_keyElements' ? '概念图' : '关键帧';
    if (!confirm(`确认为所有${label}提交批量生图任务？`)) return;
    try {
        const res = await fetch('/api/generate/batch-image', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ target, provider_id: providerId, model, size: '1280x720', aspect_ratio: '16:9' })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '批量生成失败');
        if (data.count > 0) {
            showToast(`已提交 ${data.count} 个${label}生成任务`);
            renderLeftContent();
        } else {
            showToast(data.detail || '没有可生成的草稿（需先有提示词）');
        }
    } catch (e) {
        showToast(e.message || '批量生成请求失败');
    }
}

// 故事板持久化（草稿删除等前端直改操作后调用）
async function persistBoard() {
    try {
        await fetch('/api/project/state', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                keyElements: state.keyElements,
                shots: state.shots,
                audioItems: state.audioItems,
                assets: state.assets
            })
        });
    } catch (e) {
        showToast('保存失败：' + (e.message || e));
    }
}

// === 草稿右键菜单 ===
function showDraftMenu(event, draftId, type, groupId) {
    event.preventDefault();
    event.stopPropagation();
    closeDraftMenu();
    const menu = document.createElement('div');
    menu.id = 'draftContextMenu';
    menu.className = 'draft-menu';
    menu.style.left = Math.min(event.clientX, window.innerWidth - 180) + 'px';
    menu.style.top = Math.min(event.clientY, window.innerHeight - 160) + 'px';
    menu.innerHTML = `
        <button onclick="draftMenuAddToChat('${draftId}', '${type}')"><i data-lucide="message-square" class="w-3.5 h-3.5"></i>添加到对话</button>
        <button onclick="draftMenuDelete('${draftId}', '${type}', '${groupId}')"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i>删除此草稿</button>
        <button onclick="draftMenuMoveToUncategorized('${draftId}', '${type}', '${groupId}')"><i data-lucide="folder-minus" class="w-3.5 h-3.5"></i>移除到未归类素材</button>`;
    document.body.appendChild(menu);
    lucide.createIcons();
    setTimeout(() => document.addEventListener('click', closeDraftMenu, {once: true}), 0);
}

function closeDraftMenu() {
    document.getElementById('draftContextMenu')?.remove();
}

function _groupsOfType(type) {
    return type === 'shot' ? state.shots : type === 'audio' ? state.audioItems : state.keyElements;
}

function draftMenuAddToChat(draftId, type) {
    closeDraftMenu();
    selectDraftCard(draftId, type);
    const rec = findDraftRecord(draftId, type);
    if (!rec) return;
    const draft = rec.draft;
    const label = draft.label || draftId;
    const imgUrl = draft.imgUrl || '';

    // 如果草稿有图片，作为图片附件添加到对话（让 LLM 能识别图片）
    if (imgUrl && !imgUrl.includes('picsum.photos')) {
        state.pendingAttachments.push({
            id: `draft-img-${draftId}`,
            name: `${label}.png`,
            type: 'image',
            url: imgUrl
        });
        renderPendingAttachments();
        const input = document.getElementById('chatInput');
        if (input) {
            if (!input.value.trim()) input.value = `请分析这张「${label}」的画面内容，给出改进建议：`;
            input.focus();
        }
        showToast(`已将「${label}」的图片添加到对话`);
    } else {
        const input = document.getElementById('chatInput');
        if (input) {
            input.value = `针对草稿「${label}」：` + input.value;
            input.focus();
        }
    }
}

async function draftMenuMoveToUncategorized(draftId, type, groupId) {
    closeDraftMenu();
    const group = _groupsOfType(type).find(g => g.id === groupId);
    if (!group) return;
    const draft = (group.drafts || []).find(d => d.id === draftId);
    if (!draft) return;
    // 从原分组移除
    group.drafts = group.drafts.filter(d => d.id !== draftId);
    // 添加到未归类素材
    const mediaType = draft.mediaType || 'image';
    state.assets.unshift({
        id: `ast-${Date.now()}-${Math.random().toString(36).slice(2,6)}`,
        name: draft.label || '未命名素材',
        type: mediaType,
        isBound: false,
        url: draft.imgUrl || draft.videoUrl || ''
    });
    if (state.selectedDraftId === draftId) state.selectedDraftId = group.drafts[0]?.id || '';
    renderLeftContent();
    renderUncategorizedAssets();
    updateMiddlePreview();
    await persistBoard();
    showToast('已移除到未归类素材');
}

async function draftMenuDelete(draftId, type, groupId) {
    closeDraftMenu();
    const group = _groupsOfType(type).find(g => g.id === groupId);
    if (!group) return;
    group.drafts = (group.drafts || []).filter(d => d.id !== draftId);
    if (state.selectedDraftId === draftId) state.selectedDraftId = group.drafts[0]?.id || '';
    renderLeftContent();
    updateMiddlePreview();
    await persistBoard();
    showToast('草稿已删除');
}

async function draftMenuClearGroup(type, groupId) {
    closeDraftMenu();
    const group = _groupsOfType(type).find(g => g.id === groupId);
    if (!group || !(group.drafts || []).length) return;
    if (!confirm(`确定清空「${group.title}」的全部 ${group.drafts.length} 个草稿？`)) return;
    group.drafts = [];
    renderLeftContent();
    updateMiddlePreview();
    await persistBoard();
    showToast('该组草稿已清空');
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

    // 1. 媒体预览更新（若该草稿正在生成，显示进度与实时耗时）
    const activeGen = state.activeGenerations[currentDraft.id];
    if (activeGen) {
        mediaViewer.innerHTML = `
            <div class="text-center text-purple-400">
                <i data-lucide="loader" class="w-10 h-10 animate-spin mx-auto mb-2"></i>
                <p class="text-xs">${activeGen.kind === 'video' ? '视频' : '图片'}生成中…
                    <span class="gen-elapsed" data-gen-start="${activeGen.start}">0.0s</span></p>
            </div>`;
    } else if (currentDraft.mediaType === 'image') {
        if (currentDraft.imgUrl) {
            mediaViewer.innerHTML = `<img src="${currentDraft.imgUrl}" alt="Preview Image" class="max-h-full rounded-lg shadow-xl" oncontextmenu="showPreviewReplaceMenu(event)">`;
        } else {
            mediaViewer.innerHTML = `
                <div class="preview-upload-placeholder" onclick="triggerPreviewUpload()">
                    <i data-lucide="upload-cloud" class="w-12 h-12 mx-auto mb-3 opacity-60"></i>
                    <p class="text-sm font-semibold text-gray-300">上传</p>
                    <p class="text-xs text-gray-500 mt-1">拖拽 / 粘贴 / 点击上传</p>
                </div>`;
        }
    } else if (currentDraft.mediaType === 'video') {
        if (currentDraft.videoUrl) {
            mediaViewer.innerHTML = `
                <video src="${currentDraft.videoUrl}" controls autoplay loop class="max-h-full rounded-lg shadow-xl" oncontextmenu="showPreviewReplaceMenu(event)"></video>
            `;
        } else {
            mediaViewer.innerHTML = `
                <div class="preview-upload-placeholder" onclick="triggerPreviewUpload()">
                    <i data-lucide="upload-cloud" class="w-12 h-12 mx-auto mb-3 opacity-60"></i>
                    <p class="text-sm font-semibold text-gray-300">上传</p>
                    <p class="text-xs text-gray-500 mt-1">拖拽 / 粘贴 / 点击上传</p>
                </div>`;
        }
    } else if (currentDraft.mediaType === 'audio') {
        mediaViewer.innerHTML = `
            <div class="audio-preview-card">
                <i data-lucide="loader" class="w-12 h-12 text-emerald-400 animate-spin"></i>
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
                    <i data-lucide="image" class="w-3.5 h-3.5"></i> 生成图片
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
                    <i data-lucide="video" class="w-3.5 h-3.5"></i> 生成视频
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
    const collapseArea = document.getElementById('promptCollapseArea');
    const toggleBar = document.getElementById('promptToggleBar');
    const collapseIcon = document.getElementById('collapseIcon');
    const previewBottom = document.getElementById('previewBottom');

    if (state.isPromptCollapsed) {
        collapseArea.classList.add('hidden');
        toggleBar.classList.add('collapsed');
        collapseIcon.setAttribute('data-lucide', 'chevron-down');
        previewBottom.style.height = 'auto';
        previewBottom.style.flex = 'none';
    } else {
        collapseArea.classList.remove('hidden');
        toggleBar.classList.remove('collapsed');
        collapseIcon.setAttribute('data-lucide', 'chevron-up');
        previewBottom.style.height = '280px';
        previewBottom.style.flex = 'none';
    }
    lucide.createIcons();
}

// 渲染右侧 Agent 聊天
function renderRightChat() {
    const feed = document.getElementById('chatFeed');
    if (!feed) return;

    const lastIdx = state.chatMessages.length - 1;
    feed.innerHTML = state.chatMessages.map((msg, idx) => msg.docCard ? `
        <div class="chat-msg ${msg.sender}">
            <div class="doc-card" onclick="openDocsPanel('${escapeHtml(msg.docCard).replace(/'/g, "\\'")}')">
                <i data-lucide="file-text" class="w-4 h-4"></i>
                <span class="doc-card-name">${escapeHtml(msg.docCard)}</span>
                <span class="doc-card-status">已完成</span>
                <i data-lucide="chevron-right" class="w-3.5 h-3.5 opacity-50"></i>
            </div>
        </div>` : `
        <div class="chat-msg ${msg.sender}">
            ${msg.confirm ? `
            <div class="stage-card">
                <div class="stage-card-header" onclick="this.parentElement.classList.toggle('expanded')">
                    <i data-lucide="check-circle" class="w-4 h-4 stage-check"></i>
                    <span class="stage-card-title">阶段完成</span>
                    ${msg.appliedActions ? `<span class="stage-card-badge">已执行 ${msg.appliedActions} 个操作</span>` : ''}
                    <i data-lucide="chevron-down" class="w-3.5 h-3.5 stage-arrow"></i>
                </div>
                <div class="stage-card-body">${escapeHtml(msg.confirm)}</div>
            </div>` : ''}
            ${msg.sender !== 'user' ? `<span class="msg-author">${escapeHtml(msg.modelName || 'Agent')}</span>` : ''}
            <div class="chat-bubble">${escapeHtml(msg.text).replace(/\n/g, '<br>')}</div>
            ${msg.meta ? `<div class="msg-meta">${escapeHtml(msg.meta)}</div>` : ''}
            ${(msg.confirm && idx === lastIdx) ? `
                <div class="confirm-bar">
                    <div class="confirm-actions">
                        <button class="confirm-btn primary" onclick="sendAgentMessage('确认')">确认，继续</button>
                        <button class="confirm-btn" onclick="document.getElementById('chatInput')?.focus()">我要调整</button>
                    </div>
                </div>` : ''}
        </div>
    `).join('');

    feed.scrollTop = feed.scrollHeight;
    lucide.createIcons();
}

// 在聊天流末尾追加一个"流式中"的 Agent 气泡，返回操作句柄
function createStreamingBubble(modelName) {
    const feed = document.getElementById('chatFeed');
    if (!feed) return null;
    const wrap = document.createElement('div');
    wrap.className = 'chat-msg agent streaming';
    wrap.innerHTML = `
        <span class="msg-author">${escapeHtml(modelName || 'Agent')}</span>
        <div class="chat-bubble"><span class="stream-text"></span><span class="stream-cursor">▍</span></div>
        <div class="stream-log"></div>
        <div class="msg-meta chat-status">
            <span class="spinner-dot"></span>
            <span class="status-text">正在连接…</span>
            <span class="status-elapsed">0.0s</span>
        </div>`;
    feed.appendChild(wrap);
    feed.scrollTop = feed.scrollHeight;

    const textEl = wrap.querySelector('.stream-text');
    const statusEl = wrap.querySelector('.status-text');
    const logEl = wrap.querySelector('.stream-log');
    const elapsedEl = wrap.querySelector('.status-elapsed');
    const t0 = performance.now();
    const timer = setInterval(() => {
        elapsedEl.textContent = ((performance.now() - t0) / 1000).toFixed(1) + 's';
    }, 100);

    const stageLog = [];
    return {
        setStatus(text) {
            // 阶段变化时把上一个阶段归档为 ✓ 行（重复状态不归档）
            const prev = statusEl.textContent;
            if (prev && prev !== text && prev !== '正在连接…' && prev !== '正在回复…'
                && stageLog[stageLog.length - 1] !== prev) {
                stageLog.push(prev);
                logEl.innerHTML = stageLog.map(s => `<div class="stream-log-line">✓ ${escapeHtml(s)}</div>`).join('');
            }
            statusEl.textContent = text;
            feed.scrollTop = feed.scrollHeight;
        },
        appendText(piece) {
            textEl.innerHTML += escapeHtml(piece).replace(/\n/g, '<br>');
            feed.scrollTop = feed.scrollHeight;
        },
        stages() { return stageLog.slice(); },
        remove() { clearInterval(timer); wrap.remove(); },
        elapsedSec() { return (performance.now() - t0) / 1000; }
    };
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

    // 附件交给服务端绑定资产 + 读取文档正文注入 LLM（不再只塞前端本地列表）
    const attachments = state.pendingAttachments.map(att => ({
        id: att.id,
        name: att.name,
        url: att.url,
        kind: att.type
    }));

    state.chatMessages.push({ sender: 'user', text: displayText });
    input.value = '';
    state.pendingAttachments = [];
    renderPendingAttachments();
    state.agentBusy = true;
    setAgentBusy(true);
    renderRightChat();
    const bubble = createStreamingBubble(model);
    try {
        const history = state.chatMessages.slice(-12, -1).map(message => ({
            role: message.sender === 'agent' ? 'assistant' : 'user',
            content: message.text
        }));
        // 上下文与协议提示词由服务端注入；前端只传 skill 角色提示词 + 选中态
        const response = await fetch('/api/canvas-llm/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: text || '请查看我上传的素材',
                system_prompt: skill?.system_prompt || '',
                provider,
                model,
                ms_model: provider === 'modelscope' ? model : '',
                messages: history,
                images: selectedAgentAssetUrls('image'),
                videos: selectedAgentAssetUrls('video'),
                selected_draft_id: state.selectedDraftId || '',
                selected_type: state.selectedType || '',
                asset_mode: document.getElementById('agentAssetSelect')?.value || 'bound',
                context_mode: 'studio',
                attachments
            })
        });
        if (!response.ok || !response.body) {
            const data = await response.json().catch(() => ({}));
            throw new Error(readApiError(data, 'Agent 请求失败'));
        }

        // 解析 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sseBuf = '';
        let done = false;

        while (!done) {
            const {value, done: rdDone} = await reader.read();
            if (rdDone) break;
            sseBuf += decoder.decode(value, {stream: true});
            let idx;
            while ((idx = sseBuf.indexOf('\n\n')) !== -1) {
                const raw = sseBuf.slice(0, idx).trim();
                sseBuf = sseBuf.slice(idx + 2);
                if (!raw.startsWith('data:')) continue;
                let ev;
                try { ev = JSON.parse(raw.slice(5).trim()); } catch (_) { continue; }

                if (ev.type === 'status') {
                    bubble?.setStatus(ev.text || '');
                } else if (ev.type === 'delta') {
                    bubble?.setStatus('正在回复…');
                    bubble?.appendText(ev.text || '');
                } else if (ev.type === 'done') {
                    done = true;
                    const p = ev.payload || {};
                    const elapsed = ((p.elapsed_ms || 0) / 1000).toFixed(1);
                    const metaParts = [`耗时 ${elapsed}s`];
                    if (p.steps > 1) metaParts.push(`${p.steps} 轮`);
                    if (p.applied_actions > 0) metaParts.push(`更新 ${p.applied_actions} 项`);
                    bubble?.remove();
                    state.chatMessages.push({
                        sender: 'agent',
                        text: String(p.text || '').trim() || '（空回复）',
                        meta: metaParts.join(' · '),
                        confirm: p.confirmation || '',
                        appliedActions: p.applied_actions || 0,
                        modelName: model
                    });
                    // 本轮产出的文档 → 可点击的"已完成"卡片
                    (p.documents_written || []).forEach(name => {
                        state.chatMessages.push({sender: 'agent', docCard: name, text: ''});
                    });
                    if (p.state) refreshStateFromBackend(p.state);
                    renderRightChat();
                    if (p.applied_actions > 0) showToast(`Agent 已联动更新 ${p.applied_actions} 项（${elapsed}s）`);
                    (p.warnings || []).forEach(w => showToast('⚠ ' + w));
                } else if (ev.type === 'error') {
                    done = true;
                    throw new Error(ev.detail || 'Agent 处理失败');
                }
            }
        }
        if (!done) throw new Error('连接中断，未收到完整回复');
    } catch (error) {
        bubble?.remove();
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
    // 状态圆点：推理中绿色闪烁，停止时灰色
    const dot = document.getElementById('agentStatusDot');
    if (dot) dot.classList.toggle('busy', busy);
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
    const newId = `draft-${Date.now()}`;

    if (type === 'keyElement') {
        const item = state.keyElements.find(k => k.id === groupId);
        if (item) {
            item.drafts.push({
                id: newId,
                label: `自定义草稿`,
                tag: '手动',
                mediaType: 'image',
                imgUrl: '',
                prompt: '',
                model: '',
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
                prompt: '',
                mode: '图生视频',
                model: ''
            });
        }
    } else if (type === 'audio') {
        const item = state.audioItems.find(a => a.id === groupId);
        if (item) {
            item.drafts.push({
                id: newId,
                label: `自定义音频`,
                tag: '手动',
                mediaType: 'audio',
                prompt: ''
            });
        }
    }

    renderLeftContent();
    selectDraftCard(newId, type);
    persistBoard();
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
    state.documents = serverState.documents || [];
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
            fetch('/api/plugins/ftdyb-agent/config')
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
// studio-actions 协议提示词与上下文注入已收归服务端（src/video_agent/web/routes/agent.py），
// 前端只发送消息本体 + 选中态，服务端是唯一事实源。

// 初始化 state 中的模型字段
state.availableChatModels = DEFAULT_CHAT_MODELS;
state.availableImageModels = DEFAULT_IMAGE_MODELS;
state.availableVideoModels = DEFAULT_VIDEO_MODELS;
state.apiProviders = [];

// 进行中的生成任务：draftId → {start: Date.now(), kind: 'image'|'video'}
state.activeGenerations = {};

// 全局计时器：刷新页面上所有 [data-gen-start] 的耗时显示
setInterval(() => {
    document.querySelectorAll('[data-gen-start]').forEach(el => {
        el.textContent = ((Date.now() - Number(el.dataset.genStart)) / 1000).toFixed(1) + 's';
    });
}, 200);

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
        // 同步更新 pill 标签
        const modelLabel = document.getElementById('modelPillLabel');
        if (modelLabel) modelLabel.textContent = model || '模型';
    };
    if (modelSelect) modelSelect.onchange = () => localStorage.setItem('studioAgentModel', modelSelect.value);

    // 初始化 pill 标签显示当前选中值
    const apiLabel = document.getElementById('apiPillLabel');
    const modelLabel = document.getElementById('modelPillLabel');
    if (apiLabel && providerSelect && providerSelect.value) {
        const selectedOpt = providerSelect.options[providerSelect.selectedIndex];
        if (selectedOpt) apiLabel.textContent = selectedOpt.text;
    }
    if (modelLabel && modelSelect && modelSelect.value) {
        modelLabel.textContent = modelSelect.value;
    }

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
                reference_images: refs.slice(0, 5),
                // 带上 draft 关联，服务端完成后自动回写并持久化
                draft_id: draft.id || '',
                draft_type: state.selectedType || 'keyElement'
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '生图请求失败'));
        if (data.task_id) {
            // 标记生成中：预览区出现实时计时
            state.activeGenerations[draft.id] = {start: Date.now(), kind: 'image'};
            draft.tag = '生成中';
            updateMiddlePreview();
            renderLeftContent();
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

function finishGeneration(draft) {
    const rec = state.activeGenerations[draft.id];
    delete state.activeGenerations[draft.id];
    updateMiddlePreview();
    renderLeftContent();
    return rec ? ((Date.now() - rec.start) / 1000).toFixed(1) : null;
}

async function pollAndPreviewImage(taskId, draft) {
    let attempts = 0;
    while (attempts < 150) {   // 150 × 2s = 5 分钟，真实生图可能较慢
        try {
            const res = await fetch('/api/canvas-image-tasks/' + encodeURIComponent(taskId));
            if (res.status === 404) { finishGeneration(draft); showToast('任务丢失，请重试'); return; }
            const data = await res.json();
            if (data.status === 'succeeded' && data.result && data.result.images && data.result.images.length) {
                draft.imgUrl = data.result.images[0];
                draft.tag = data.mock ? 'mock 演示' : '已生成';
                const sec = data.elapsed || finishGeneration(draft);
                finishGeneration(draft);
                showToast(`图片渲染完成！耗时 ${sec}s`);
                return;
            }
            if (data.status === 'failed') {
                draft.tag = '生成失败';
                const sec = data.elapsed || finishGeneration(draft);
                finishGeneration(draft);
                showToast(`生成失败（${sec}s）: ` + (data.error || '未知错误'));
                return;
            }
        } catch (e) { /* 静默重试 */ }
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
    }
    finishGeneration(draft);
    showToast('轮询超时（5 分钟），请检查供应商状态后重试');
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
                multimodal: mode === '对口型数字人',
                draft_id: draft.id || '',
                draft_type: state.selectedType || 'shot'
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '视频生成请求失败'));

        const videoUrl = data.video_url || data.videos?.[0] || data.images?.[0];
        if (videoUrl) {
            draft.videoUrl = videoUrl;
            updateMiddlePreview();
            showToast('视频已生成！');
        } else if (data.task_id) {
            // 标记生成中 + 轮询：预览区出现实时计时
            state.activeGenerations[draft.id] = {start: Date.now(), kind: 'video'};
            draft.tag = '生成中';
            updateMiddlePreview();
            renderLeftContent();
            pollAndPreviewVideo(data.task_id, draft);
        } else {
            showToast('视频任务已提交');
        }
    } catch (err) {
        console.error('[Studio] 生成视频失败:', err);
        showToast(err.message || '视频生成请求失败，请检查 API 配置');
    }
}

async function pollAndPreviewVideo(taskId, draft) {
    let attempts = 0;
    while (attempts < 300) {   // 300 × 2s = 10 分钟，视频生成较慢
        try {
            const res = await fetch('/api/tasks/' + encodeURIComponent(taskId));
            const data = await res.json();
            if (data.status === 'not_found') { finishGeneration(draft); showToast('任务丢失，请重试'); return; }
            if ((data.status === 'succeeded' || data.status === 'completed') && data.video_url) {
                draft.videoUrl = data.video_url;
                draft.tag = data.mock ? 'mock 演示' : '已生成';
                const sec = data.elapsed || finishGeneration(draft);
                finishGeneration(draft);
                showToast(`视频渲染完成！耗时 ${sec}s`);
                return;
            }
            if (data.status === 'failed') {
                draft.tag = '生成失败';
                const sec = data.elapsed || finishGeneration(draft);
                finishGeneration(draft);
                showToast(`视频生成失败（${sec}s）: ` + (data.error || '未知错误'));
                return;
            }
        } catch (e) { /* 静默重试 */ }
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
    }
    finishGeneration(draft);
    showToast('视频轮询超时（10 分钟），请检查供应商状态后重试');
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
    const audioT0 = performance.now();

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
                messages: [],
                context_mode: 'none'
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(readApiError(data, '音频规划失败'));
        draft.prompt = String(data.text || draft.prompt);
        draft.mode = mode;
        draft.timbre = timbre;
        document.getElementById('detailedPromptInput').value = draft.prompt;
        showToast(`音频规划已生成（耗时 ${((performance.now() - audioT0) / 1000).toFixed(1)}s）`);
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
    container.innerHTML = state.pendingAttachments.map((att, idx) => {
        if (att.type === 'image' && att.url) {
            return `
                <div class="attachment-chip attachment-img-chip">
                    <div class="attachment-thumb-wrap">
                        <img src="${att.url}" class="attachment-thumb" alt="${escapeHtml(att.name)}">
                        <div class="attachment-hover-preview"><img src="${att.url}" alt="preview"></div>
                    </div>
                    <span class="attachment-name">${escapeHtml(att.name)}</span>
                    <button class="attachment-remove" onclick="removePendingAttachment(${idx})" title="移除">
                        <i data-lucide="x" class="w-3 h-3"></i>
                    </button>
                </div>`;
        }
        return `
            <div class="attachment-chip">
                <i data-lucide="file" class="w-3.5 h-3.5"></i>
                <span class="attachment-name">${escapeHtml(att.name)}</span>
                    <button class="attachment-remove" onclick="removePendingAttachment(${idx})" title="移除">
                        <i data-lucide="x" class="w-3 h-3"></i>
                    </button>
            </div>`;
    }).join('');
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
    if (Array.isArray(serverState.documents)) state.documents = serverState.documents;

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
// 注：阶段步骤条（WF_PHASES/renderWorkflowPhases）已随新版 UI 移除（修复计划书 P0-1），
// 此处仅保留工作流运行按钮与 SSE 进度 toast。
let wfEventSource = null;

async function startWorkflow() {
    const btn = document.getElementById('workflowRunBtn');
    if (btn) btn.disabled = true;

    try {
        // 把 Agent 面板选中的供应商/模型传给工作流，供 story/storyboard/image 阶段真实调用
        const res = await fetch('/api/workflow/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                goal: '自动生成完整影视项目',
                provider: document.getElementById('agentProviderSelect')?.value || '',
                model: document.getElementById('agentModelSelect')?.value || '',
                image_provider: document.getElementById('imageProviderSelect')?.value || '',
                image_model: document.getElementById('modelSelect')?.value || ''
            })
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

    wfEventSource = new EventSource('/api/workflow/events');
    wfEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.event === 'phase_started') {
                // 阶段步骤条已移除，进度仅以 toast 呈现
            } else if (data.event === 'phase_completed') {
                showToast(`${data.label}${data.skipped ? '（跳过）' : ' 完成'}：${data.detail || ''}`);
            } else if (data.event === 'phase_failed') {
                showToast(`${data.label || data.phase} 失败：${data.error || ''}`);
            } else if (data.event === 'workflow_done') {
                showToast(data.message || '工作流全部完成！');
                wfEventSource.close();
                wfEventSource = null;
                const btn = document.getElementById('workflowRunBtn');
                if (btn) btn.disabled = false;
                // 刷新故事板（工作流可能添加了新 draft）
                fetch('/api/project/state').then(r => r.json()).then(s => refreshStateFromBackend(s));
            } else if (data.event === 'workflow_failed') {
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

// ========== 双模式切换：影视Agent / 画布 ==========

let _canvasLoaded = false;

let _apiSettingsLoaded = false;

function switchWorkMode(mode) {
    document.body.classList.toggle('mode-canvas', mode === 'canvas' || mode === 'api');
    document.body.classList.toggle('mode-api', mode === 'api');
    document.body.classList.remove('nav-hidden');
    document.getElementById('modeAgentBtn').classList.toggle('active', mode === 'agent');
    document.getElementById('modeCanvasBtn').classList.toggle('active', mode === 'canvas');
    document.getElementById('modeApiBtn').classList.toggle('active', mode === 'api');

    // 画布/API模式下显示导航箭头
    const isOverlayMode = mode === 'canvas' || mode === 'api';
    document.getElementById('navToggleArrow').classList.toggle('hidden', !isOverlayMode);
    document.getElementById('agentToggleHandle').classList.toggle('hidden', mode !== 'canvas');

    // API 配置层显隐
    document.getElementById('apiSettingsLayer').classList.toggle('hidden', mode !== 'api');
    document.getElementById('canvasLayer').classList.toggle('hidden', mode !== 'canvas');

    const colRight = document.getElementById('colRight');

    // 切回 agent 模式时恢复侧栏
    if (mode === 'agent') {
        colRight.classList.remove('collapsed');
        colRight.style.transform = '';
        _updateAgentToggleIcon(false);
    }

    // API 模式下隐藏 Agent 侧栏
    if (mode === 'api') {
        colRight.classList.add('collapsed');
    }

    // 导航箭头重置为向上（导航栏可见）
    _updateNavToggleIcon(false);

    // 画布 iframe 懒加载
    if (mode === 'canvas' && !_canvasLoaded) {
        document.getElementById('canvasIframe').src = 'http://localhost:3000';
        _canvasLoaded = true;
    }

    // API 配置 iframe 懒加载
    if (mode === 'api' && !_apiSettingsLoaded) {
        document.getElementById('apiSettingsIframe').src = '/static/api-settings.html';
        _apiSettingsLoaded = true;
    }
}

// 主题切换（使用 StudioTheme API 统一管理）
function toggleThemeMode() {
    const isDark = document.documentElement.classList.contains('dark');
    const next = isDark ? 'light' : 'dark';
    document.documentElement.classList.toggle('dark', next === 'dark');
    document.documentElement.classList.toggle('light', next === 'light');
    if (window.StudioTheme) window.StudioTheme.set(next);
    const icon = document.getElementById('themeToggleIcon');
    icon.setAttribute('data-lucide', next === 'dark' ? 'moon' : 'sun');
    if (window.lucide) lucide.createIcons({ nodes: [icon] });
    localStorage.setItem('theme', next);
}

function toggleAgentSidebar() {
    const col = document.getElementById('colRight');
    col.classList.toggle('collapsed');
    const collapsed = col.classList.contains('collapsed');
    _updateAgentToggleIcon(collapsed);
}

// 画布模式：在侧栏左边缘检测拖拽（无独立热区元素，始终贴合边框）
function initCanvasSplitter() {
    const colRight = document.getElementById('colRight');
    const EDGE_ZONE = 8; // 左边缘检测区域宽度(px)
    let startX = 0;
    let startWidth = 0;

    colRight.addEventListener('mousedown', (e) => {
        // 仅画布模式且侧栏展开时生效
        if (!document.body.classList.contains('mode-canvas')) return;
        if (colRight.classList.contains('collapsed')) return;

        // 检测是否点击在左边缘区域
        const rect = colRight.getBoundingClientRect();
        if (e.clientX - rect.left > EDGE_ZONE) return;

        e.preventDefault();
        startX = e.clientX;
        startWidth = colRight.offsetWidth;
        document.body.classList.add('dragging-splitter');

        const onMove = (ev) => {
            const deltaX = ev.clientX - startX;
            const newWidth = Math.max(280, Math.min(700, startWidth - deltaX));
            colRight.style.width = newWidth + 'px';
        };

        const onUp = () => {
            document.body.classList.remove('dragging-splitter');
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        };

        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    });
}

function toggleHeaderVisibility() {
    document.body.classList.toggle('nav-hidden');
    _updateNavToggleIcon(document.body.classList.contains('nav-hidden'));
}

// 输入区与消息区之间的拖拽调整
function initChatResizeHandle() {
    const handle = document.getElementById('chatResizeHandle');
    const inputArea = document.getElementById('chatInputArea');
    let startY = 0;
    let startHeight = 0;

    handle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startY = e.clientY;
        startHeight = inputArea.offsetHeight;
        handle.classList.add('dragging');

        const onMove = (ev) => {
            const deltaY = ev.clientY - startY;
            const newHeight = Math.max(100, Math.min(400, startHeight - deltaY));
            inputArea.style.height = newHeight + 'px';
            inputArea.style.flexShrink = '0';
        };

        const onUp = () => {
            handle.classList.remove('dragging');
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        };

        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    });
}

// 底部工具栏 pill 按钮弹出下拉菜单
function togglePillDropdown(type) {
    // 关闭已有弹出
    const existing = document.querySelector('.pill-dropdown');
    if (existing) { existing.remove(); return; }

    const btnMap = { api: 'apiPillBtn', model: 'modelPillBtn', skill: 'skillPillBtn', asset: 'assetPillBtn' };
    const selectMap = { api: 'agentProviderSelect', model: 'agentModelSelect', skill: 'agentSkillSelect', asset: 'agentAssetSelect' };
    const select = document.getElementById(selectMap[type]);
    if (!select) return;

    const btn = document.getElementById(btnMap[type]);
    const rect = btn.getBoundingClientRect();
    const parentRect = btn.closest('.col-right').getBoundingClientRect();

    const dropdown = document.createElement('div');
    dropdown.className = 'pill-dropdown';
    dropdown.style.cssText = `position:absolute; bottom:${parentRect.bottom - rect.top + 6}px; left:${rect.left - parentRect.left}px; z-index:100;`;

    // 素材库特殊处理：模式选择 + 打开熊布素材库面板
    if (type === 'asset') {
        const currentMode = document.getElementById('agentAssetSelect').value;
        let html = '';
        html += `<div class="pill-option${currentMode === 'all' ? ' selected' : ''}" data-asset-mode="all">素材库</div>`;
        html += `<div class="pill-option${currentMode === 'bound' ? ' selected' : ''}" data-asset-mode="bound">仅已绑定素材</div>`;
        html += '<div class="pill-dropdown-section"></div>';
        html += '<div class="pill-option" data-action="open-library">📂 打开画布素材库</div>';
        dropdown.innerHTML = html;
        btn.closest('.col-right').appendChild(dropdown);

        dropdown.addEventListener('click', (e) => {
            const opt = e.target.closest('.pill-option');
            if (!opt) return;
            const mode = opt.dataset.assetMode;
            const action = opt.dataset.action;
            if (mode) {
                const sel = document.getElementById('agentAssetSelect');
                sel.value = mode;
                sel.dispatchEvent(new Event('change'));
                document.getElementById('assetPillLabel').textContent = mode === 'all' ? '素材库' : '已绑定';
            } else if (action === 'open-library') {
                openAssetLibrary();
            }
            dropdown.remove();
        });
        _bindDropdownClose(dropdown, btn);
        return;
    }

    const options = Array.from(select.options).filter(o => o.value || type === 'api').map(o =>
        `<div class="pill-option${select.value === o.value ? ' selected' : ''}" data-val="${o.value}">${o.text || o.value}</div>`
    ).join('');
    dropdown.innerHTML = options || '<div class="pill-option disabled">请先选择 API</div>';

    btn.closest('.col-right').appendChild(dropdown);

    // 点击选项
    dropdown.addEventListener('click', (e) => {
        const opt = e.target.closest('.pill-option');
        if (!opt || opt.classList.contains('disabled')) return;
        const val = opt.dataset.val;
        select.value = val;
        select.dispatchEvent(new Event('change'));
        const labelMap = { api: 'apiPillLabel', model: 'modelPillLabel', skill: 'skillPillLabel', asset: 'assetPillLabel' };
        document.getElementById(labelMap[type]).textContent = opt.textContent;
        // 切换 API 后自动更新模型下拉框显示
        if (type === 'api') {
            const modelSelect = document.getElementById('agentModelSelect');
            const modelLabel = document.getElementById('modelPillLabel');
            if (modelSelect && modelLabel) {
                modelLabel.textContent = modelSelect.value || '模型';
            }
        }
        dropdown.remove();
    });

    _bindDropdownClose(dropdown, btn);
}

// 素材库下拉：从熊布加载素材列表
async function _loadCanvasAssets(dropdown) {
    try {
        const resp = await fetch('/api/canvas-assets');
        const data = await resp.json();
        const online = data.canvas_online;
        const library = data.library;

        let html = '<div class="pill-dropdown-section">模式</div>';
        html += '<div class="pill-option" data-asset-mode="all">全部素材</div>';
        html += '<div class="pill-option" data-asset-mode="bound">仅已绑定素材</div>';

        if (!online || !library) {
            html += '<div class="pill-dropdown-section">熊布素材库</div>';
            html += `<div class="pill-option disabled">${online ? '素材库为空' : '熊布离线，无法加载'}</div>`;
        } else {
            // 解析熊布素材库结构: libraries → categories → items
            const libraries = library.libraries || [];
            const activeId = library.active_library_id || '';
            const activeLib = libraries.find(l => l.id === activeId) || libraries[0];
            const categories = (activeLib && activeLib.categories) || library.categories || [];

            let totalItems = 0;
            categories.forEach(cat => {
                const items = cat.items || [];
                if (items.length === 0) return;
                html += `<div class="pill-dropdown-section">${cat.name || '未分类'}</div>`;
                items.slice(0, 10).forEach(item => {
                    totalItems++;
                    const name = item.name || item.id || '未命名素材';
                    const url = item.url || item.path || '';
                    html += `<div class="pill-option" data-asset-url="${url}" data-asset-name="${name}">${name}</div>`;
                });
                if (items.length > 10) {
                    html += `<div class="pill-option disabled">… 还有 ${items.length - 10} 个</div>`;
                }
            });

            if (totalItems === 0) {
                html += '<div class="pill-dropdown-section">熊布素材库</div>';
                html += '<div class="pill-option disabled">素材库为空，请先在熊布中添加素材</div>';
            }
        }
        dropdown.innerHTML = html;

        // 点击事件
        dropdown.addEventListener('click', (e) => {
            const opt = e.target.closest('.pill-option');
            if (!opt || opt.classList.contains('disabled')) return;
            const mode = opt.dataset.assetMode;
            const assetUrl = opt.dataset.assetUrl;
            if (mode) {
                const sel = document.getElementById('agentAssetSelect');
                sel.value = mode;
                sel.dispatchEvent(new Event('change'));
                document.getElementById('assetPillLabel').textContent = mode === 'all' ? '素材库' : '已绑定';
            } else if (assetUrl) {
                _attachCanvasAsset(opt.dataset.assetName, assetUrl);
            }
            dropdown.remove();
        });
    } catch (err) {
        dropdown.innerHTML = '<div class="pill-option disabled">加载失败: ' + err.message + '</div>';
    }
}

// 将熊布素材作为附件添加到输入框
function _attachCanvasAsset(name, url) {
    if (!state.pendingAttachments) state.pendingAttachments = [];
    state.pendingAttachments.push({
        id: 'canvas-' + Date.now(),
        name: name,
        url: url,
        type: 'image'
    });
    renderPendingAttachments();
    showToast(`已添加熊布素材: ${name}`);
}

// 下拉菜单点击外部关闭
function _bindDropdownClose(dropdown, btn) {
    setTimeout(() => {
        const closeHandler = (ev) => {
            if (!dropdown.contains(ev.target) && !btn.contains(ev.target)) {
                dropdown.remove();
                document.removeEventListener('mousedown', closeHandler);
            }
        };
        document.addEventListener('mousedown', closeHandler);
    }, 0);
}

// 素材库模态面板：自建选择器
let _assetPickerItems = [];
let _assetPickerSelected = new Set();
let _assetPickerTab = 'image';

function openAssetLibrary() {
    const modal = document.getElementById('assetLibraryModal');
    modal.classList.remove('hidden');
    _assetPickerSelected.clear();
    _updateAssetFooter();
    switchAssetTab(_assetPickerTab);
}

function closeAssetLibrary() {
    document.getElementById('assetLibraryModal').classList.add('hidden');
}

function switchAssetTab(type) {
    _assetPickerTab = type;
    document.querySelectorAll('.asset-tab').forEach(t => t.classList.toggle('active', t.dataset.type === type));
    _assetPickerSelected.clear();
    _updateAssetFooter();
    _loadAssetPicker(type);
}

async function _loadAssetPicker(type) {
    const container = document.getElementById('assetGridContainer');
    container.innerHTML = '<div class="asset-loading">加载中...</div>';
    try {
        const resp = await fetch(`/api/asset-picker?type=${type}`);
        const data = await resp.json();
        if (!data.canvas_online) {
            container.innerHTML = '<div class="asset-empty"><span>熊布离线，无法加载素材库</span><span style="font-size:11px;color:var(--text-dim)">请确认熊布服务已启动 (localhost:3000)</span></div>';
            return;
        }
        _assetPickerItems = data.items || [];
        _renderAssetGrid(container, _assetPickerItems);
    } catch (err) {
        container.innerHTML = `<div class="asset-empty"><span>加载失败: ${err.message}</span></div>`;
    }
}

function _renderAssetGrid(container, items) {
    if (!items.length) {
        container.innerHTML = '<div class="asset-empty"><span>素材库为空</span><span style="font-size:11px;color:var(--text-dim)">请先在熊布中添加素材</span></div>';
        return;
    }
    // 按 category 分组
    const groups = {};
    items.forEach((item, idx) => {
        const cat = item.category || '未分类';
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push({ ...item, _idx: idx });
    });

    let html = '';
    for (const [cat, catItems] of Object.entries(groups)) {
        html += `<div class="asset-category-title">${cat} (${catItems.length})</div>`;
        html += '<div class="asset-grid">';
        catItems.forEach(item => {
            const thumb = item.thumb || item.url || '';
            const name = item.name || '未命名';
            html += `<div class="asset-card" data-idx="${item._idx}" onclick="_toggleAssetCard(this, ${item._idx})" title="${name}">`;
            if (thumb) {
                html += `<img src="${thumb}" alt="${name}" loading="lazy" onerror="this.style.display='none'">`;
            }
            html += `<div class="asset-card-name">${name}</div></div>`;
        });
        html += '</div>';
    }
    container.innerHTML = html;
}

function _toggleAssetCard(el, idx) {
    if (_assetPickerSelected.has(idx)) {
        _assetPickerSelected.delete(idx);
        el.classList.remove('selected');
    } else {
        _assetPickerSelected.add(idx);
        el.classList.add('selected');
    }
    _updateAssetFooter();
}

function _updateAssetFooter() {
    const count = _assetPickerSelected.size;
    document.getElementById('assetSelectedCount').textContent = `已选 ${count} 个`;
    document.getElementById('assetConfirmBtn').disabled = count === 0;
}

function confirmAssetSelection() {
    _assetPickerSelected.forEach(idx => {
        const item = _assetPickerItems[idx];
        if (item && item.url) {
            _attachCanvasAsset(item.name || '素材', item.url);
        }
    });
    closeAssetLibrary();
}

// 侧栏箭头：展开时向右（向里），收缩时向左（向外）
function _updateAgentToggleIcon(collapsed) {
    const icon = document.getElementById('agentToggleIcon');
    icon.setAttribute('data-lucide', collapsed ? 'chevron-left' : 'chevron-right');
    if (window.lucide) lucide.createIcons({ nodes: [icon] });
}

// 导航箭头：导航栏可见时向上（点击隐藏），隐藏时向下（点击呼出）
function _updateNavToggleIcon(hidden) {
    const icon = document.getElementById('navToggleIcon');
    icon.setAttribute('data-lucide', hidden ? 'chevron-down' : 'chevron-up');
    if (window.lucide) lucide.createIcons({ nodes: [icon] });
}
