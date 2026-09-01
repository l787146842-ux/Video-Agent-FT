import {
  createSignal, createEffect, onMount, onCleanup, Show, type ParentProps,
} from 'solid-js';
import { useLocation } from '@solidjs/router';
import { FiChevronDown } from 'solid-icons/fi';
import { Header } from './Header';
import { ToastHost } from '@/components/shared/Toast';
import { ContextMenuHost } from '@/components/shared/ContextMenu';
import { ConfirmDialogHost } from '@/components/shared/ConfirmDialog';
import { SplashScreen } from '@/components/shared/SplashScreen';
import { DocsPanel } from '@/components/docs/DocsPanel';
import { AdjustDialog } from '@/components/left-panel/AdjustDialog';
import { AssetLibraryModal } from '@/components/right-panel/AssetLibraryModal';
import { GenerationLogPanel } from './GenerationLogPanel';
import { initGenerationEvents, restoreActiveGenerations } from '@/lib/generation-events';
import { getProjectState } from '@/api/project';
import { getAppConfig, getProviders } from '@/api/providers';
import { getSkills } from '@/api/agent';
import { ensureGlobalSettings } from '@/stores/global-settings';
import { state, studioActions } from '@/stores/studio';
import { chatActions } from '@/stores/chat';
import { registerQueueStorageKey } from '@/lib/chat/queue-storage';
import { resumeAgentTasks, focusConversation } from '@/hooks/use-sse';
import { convActions, convState } from '@/stores/conversations';
import { showToast } from '@/stores/toast';
import {
  performRedo, performUndo, refreshHistoryStatus,
} from '@/stores/history';
import { uid } from '@/lib/utils';
import { bootFail, warnBootTaskResume } from '@/lib/boot-fallback';
import type { AssetPickerItem } from '@/api/providers';
import {
  setCanvasIframe, setCanvasError, canvasOverlayDragging,
  setCanvasEmbed, canvasIframeSrc,
} from '@/stores/canvas';

/**
 * 布局壳 — Router root 组件
 * Header（品牌/导航/主题/项目切换）+ 当前路由页面 + 全局 Toast。
 *
 * 导航栏收放箭头拆为两个版本：嵌在 Header 内部（默认）/ 独立 fixed 版
 *（header 收起后仍可见可点击，用于再次展开）。
 *   —— 收放箭头是导航栏的附属控件，所以"隐藏导航栏"等于"把箭头提到屏幕顶部"。
 */
export function LayoutShell(props: ParentProps) {
  const location = useLocation();
  const [headerHidden, setHeaderHidden] = createSignal(false);
  const [loading, setLoading] = createSignal(true);

  /** 覆盖层模式（画布 / API 配置 / 全局设置）才显示收放箭头 */
  const overlayMode = () =>
    location.pathname === '/canvas' || location.pathname === '/settings'
    || location.pathname === '/global-settings';

  /** 当前是否在画布路由 */
  const onCanvasRoute = () => location.pathname === '/canvas';

  // 切换模式时恢复导航栏（旧版 switchWorkMode 行为）
  createEffect(() => {
    void location.pathname;
    setHeaderHidden(false);
  });

  // ========== 画布 iframe 持久化（不随路由卸载，保留画布状态） ==========
  let canvasIframeRef: HTMLIFrameElement | undefined;

  // 全局快捷键：Ctrl+Z 撤销 / Ctrl+Shift+Z、Ctrl+Y 重做（输入框内不拦截）
  function onGlobalKeyDown(e: KeyboardEvent) {
    if (!(e.ctrlKey || e.metaKey)) return;
    const target = e.target as HTMLElement;
    const typing = target.closest('input, textarea, [contenteditable="true"]');
    if (typing) return;
    const key = e.key.toLowerCase();
    if (key === 'z' && !e.shiftKey) {
      e.preventDefault();
      void performUndo();
    } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
      e.preventDefault();
      void performRedo();
    }
  }

  onMount(async () => {
    document.addEventListener('keydown', onGlobalKeyDown);
    onCleanup(() => document.removeEventListener('keydown', onGlobalKeyDown));
    void refreshHistoryStatus();

    // 排队消息持久化键：项目 + 对话维度，刷新后按当前上下文恢复
    registerQueueStorageKey(
      () => `ftdyb.queued.${state.projectId || 'none'}.${convState.activeId || 'main'}`,
    );

    // 刷新存活：后端 worker 仍在跑（刷新不中断）则显示忙态并轮询，完成后同步成果
    void reattachRunningAgent();

    // 全局生成事件总线：agent/批量生成驱动卡片转圈 + 生成日志联动
    initGenerationEvents();

    // 画布 iframe 卸载时清引用（在线状态经后端 API 探测，跨源 postMessage 通道已移除）
    onCleanup(() => setCanvasIframe(undefined));

    // 全局生成设置（顶栏入口/参数栏自动填充共用）预热加载
    void ensureGlobalSettings();

    // 后端未就绪降级为默认空状态（行为不变；warn+toast 信号见 lib/boot-fallback）
    const [snapshot, cfg, provs, skills] = await Promise.all([
      getProjectState().catch(bootFail('project-state')),
      getAppConfig().catch(bootFail('app-config')),
      getProviders().catch(bootFail('providers')),
      getSkills().catch(bootFail('skills')),
    ]);

    if (snapshot) {
      studioActions.loadFullState(snapshot);
      chatActions.loadMessages(snapshot.chatMessages || []);
      convActions.loadFromSnapshot(snapshot); // 多对话标签栏从快照装载
    } else {
      convActions.loadFromSnapshot(null);
    }

    // 刷新后恢复读秒：后端仍在处理的生成任务重新点亮卡片/预览框转圈
    void restoreActiveGenerations();

    studioActions.setApiConfig({
      chatModels: cfg?.chat_models,
      imageModels: cfg?.image_models,
      videoModels: cfg?.video_models,
      canvasUrl: cfg?.canvas_url,
      // 仅保留启用的供应商（对齐旧逻辑）
      providers: (provs?.providers || []).filter((p) => p.enabled !== false),
      skills: skills ?? undefined,
    });
    // 后端下发的画布嵌入引导参数（画布站点 / canvas-agent / token）
    setCanvasEmbed(cfg?.infinite_canvas_embed);
    setLoading(false);
  });

  async function reattachRunningAgent() {
    const pid = state.projectId || '';
    if (!pid) return;
    try { await resumeAgentTasks(pid); } catch (err) { warnBootTaskResume(err); }
  }

  // 项目切换后也自动恢复该项目的后台任务订阅（刷新/切回都能继续看到进度）
  createEffect(() => {
    const pid = state.projectId;
    if (!pid) return;
    void resumeAgentTasks(pid);
  });

  // 批 6-2 多会话并行：切换活跃对话时聚焦其任务事件流（重订阅拿 replay 恢复）；首装载/项目切换后的首次赋值只记录不触发。
  let prevConvId: string | undefined;
  createEffect(() => {
    const cid = convState.activeId;
    if (!cid || prevConvId === undefined || prevConvId === cid) {
      prevConvId = cid || undefined;
      return;
    }
    prevConvId = cid;
    focusConversation(cid);
  });

  // 画布 iframe 初始化：等 loading 结束后 DOM 就绪再设引导 src（Show 渲染后等一帧确保 ref 就绪）
  let iframeInitialized = false;
  createEffect(() => {
    if (loading() || iframeInitialized) return;
    requestAnimationFrame(() => {
      if (iframeInitialized || !canvasIframeRef) return;
      iframeInitialized = true;
      setCanvasIframe(canvasIframeRef);
      canvasIframeRef.src = canvasIframeSrc();
    });
  });

  return (
    <div class="panel-column" classList={{ 'overlay-shell': overlayMode() }}>
      <Show when={loading()}>
        <SplashScreen />
      </Show>
      <Show when={!loading()}>
      <Show when={!headerHidden()}>
        <Header
          overlayMode={overlayMode()}
          onToggleHeader={() => setHeaderHidden(true)}
        />
      </Show>

      {/* 导航栏收起时单独渲染 fixed 箭头到视口顶部中央（仅覆盖层模式；用于再次展开） */}
      <Show when={overlayMode() && headerHidden()}>
        <button
          type="button"
          class="nav-toggle-arrow nav-toggle-arrow--floating"
          title="展开导航栏"
          onClick={() => setHeaderHidden(false)}
        >
          <FiChevronDown size={14} />
        </button>
      </Show>

      <main class="layout-main">
        {props.children}
        {/* 画布 iframe 持久层：始终挂载，不随路由卸载，保留画布操作状态 */}
        <div
          class="canvas-persistent-layer"
          style={{ display: onCanvasRoute() ? 'block' : 'none' }}
        >
          <iframe
            ref={canvasIframeRef}
            class="canvas-iframe"
            classList={{ 'pointer-events-none': canvasOverlayDragging() }}
            title="画布模式"
            onLoad={() => {
              // 画布页面成功加载 → 清除离线错误标志（忽略 src 设置前 about:blank 的空加载）
              if (canvasIframeRef?.src && /^https?:/.test(canvasIframeRef.src)) {
                setCanvasError(false);
              }
            }}
          />
        </div>
      </main>

      <ToastHost />
      <ContextMenuHost />
      <ConfirmDialogHost />
      <DocsPanel />
      <AdjustDialog />
      <GenerationLogPanel />

      {/* 全局"画布素材库"模态框（左栏 AssetCard 和 ChatInput 工具栏共用） */}
      <AssetLibraryModal
        open={state.assetLibraryOpen}
        onClose={() => studioActions.closeAssetLibrary()}
        onPick={(items: AssetPickerItem[]) => {
          // 批量作为图片附件加入 pendingAttachments
          items.forEach((item) => {
            studioActions.addPendingAttachment({
              id: uid('canvas'),
              name: item.name,
              type: 'image',
              url: item.url,
            });
          });
          showToast(`已添加 ${items.length} 个素材`, 'success');
        }}
      />
      </Show>
    </div>
  );
}
