/**
 * 拉取模型弹窗——  自 SettingsView 切出。
 * 搜索/页签/勾选状态下沉自管理（弹窗每次打开全新挂载，初始勾选 = 已配置模型）；
 * 父组件只传数据与「应用」回调，行为与切出前一致。
 */
import { For, Show, createSignal, untrack } from 'solid-js';
import { FiX } from 'solid-icons/fi';
import type { FetchedModels, ModelCat } from '../settings-meta';

const CAT_LABEL: Record<ModelCat, string> = { image: '生图', chat: 'LLM', video: '视频' };

export interface ModelPicked {
  image: string[];
  chat: string[];
  video: string[];
}

export function FetchModelsModal(props: {
  fetched: () => FetchedModels;
  savedCats: () => { image: Set<string>; chat: Set<string>; video: Set<string> };
  onApply: (picked: ModelPicked) => void;
  onClose: () => void;
}) {
  const [mSearch, setMSearch] = createSignal('');
  const [mTab, setMTab] = createSignal<'all' | ModelCat>('all');
  // 画布同款：默认勾选 = 已在配置里的（挂载时一次性快照，不随外部变化重算）
  const init = untrack(() => props.savedCats());
  const [checked, setChecked] = createSignal<Set<string>>(
    new Set([...init.image, ...init.chat, ...init.video]),
  );

  const catOf = (m: string): ModelCat => {
    const s = props.savedCats();
    if (s.image.has(m)) return 'image';
    if (s.video.has(m)) return 'video';
    if (s.chat.has(m)) return 'chat';
    const f = props.fetched();
    if ((f.image_models ?? []).includes(m)) return 'image';
    if ((f.video_models ?? []).includes(m)) return 'video';
    return 'chat';
  };

  const modalRows = () => {
    const f = props.fetched();
    const q = mSearch().trim().toLowerCase();
    return (f.all ?? []).filter((m) => (!q || m.toLowerCase().includes(q)) && (mTab() === 'all' || catOf(m) === mTab()));
  };
  const catCount = (cat: ModelCat | 'all') => {
    const f = props.fetched();
    const list = cat === 'all' ? (f.all ?? []) : (f.all ?? []).filter((m) => catOf(m) === cat);
    return { on: list.filter((m) => checked().has(m)).length, total: list.length };
  };
  function toggleChecked(m: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m); else next.add(m);
      return next;
    });
  }
  function applyFetched() {
    const f = props.fetched();
    props.onApply({
      image: (f.all ?? []).filter((m) => catOf(m) === 'image' && checked().has(m)),
      chat: (f.all ?? []).filter((m) => catOf(m) === 'chat' && checked().has(m)),
      video: (f.all ?? []).filter((m) => catOf(m) === 'video' && checked().has(m)),
    });
  }

  return (
    <div class="aps-modal-mask" onClick={() => props.onClose()}>
      <div class="aps-modal" onClick={(e) => e.stopPropagation()}>
        <div class="aps-modal-head">
          <div>
            <div class="aps-sec-title">从上游拉取的模型清单</div>
            <div class="aps-sec-desc">共 {props.fetched().total} 个模型 · 协议 {props.fetched().protocol} · 勾选后应用到模型列表</div>
          </div>
          <button type="button" class="aps-icon-btn" title="关闭" onClick={() => props.onClose()}>
            <FiX size={14} />
          </button>
        </div>
        <div class="aps-modal-tools">
          <input
            class="aps-input aps-modal-search" placeholder="按名称搜索模型…"
            value={mSearch()} onInput={(e) => setMSearch(e.currentTarget.value)}
          />
          <button type="button" class={`aps-tab ${mTab() === 'all' ? 'active' : ''}`} onClick={() => setMTab('all')}>
            全部 {catCount('all').on}/{catCount('all').total}
          </button>
          <button type="button" class={`aps-tab ${mTab() === 'image' ? 'active' : ''}`} onClick={() => setMTab('image')}>
            生图 {catCount('image').on}/{catCount('image').total}
          </button>
          <button type="button" class={`aps-tab ${mTab() === 'chat' ? 'active' : ''}`} onClick={() => setMTab('chat')}>
            LLM {catCount('chat').on}/{catCount('chat').total}
          </button>
          <button type="button" class={`aps-tab ${mTab() === 'video' ? 'active' : ''}`} onClick={() => setMTab('video')}>
            视频 {catCount('video').on}/{catCount('video').total}
          </button>
        </div>
        <div class="aps-modal-list">
          <Show when={modalRows().length > 0} fallback={<div class="aps-empty">无匹配模型</div>}>
            <For each={modalRows()}>
              {(m) => (
                <label class="aps-mrow">
                  <input type="checkbox" checked={checked().has(m)} onChange={() => toggleChecked(m)} />
                  <span class="aps-mcat">{CAT_LABEL[catOf(m)]}</span>
                  <span class="aps-mname">{m}</span>
                </label>
              )}
            </For>
          </Show>
        </div>
        <div class="aps-modal-foot">
          <span class="aps-foot-label">将应用:</span>
          <span class="aps-apply-badge">生图 {catCount('image').on}</span>
          <span class="aps-apply-badge">LLM {catCount('chat').on}</span>
          <span class="aps-apply-badge">视频 {catCount('video').on}</span>
          <span class="aps-foot-unsel">未选 {catCount('all').total - catCount('all').on}</span>
          <span class="aps-foot-spacer" />
          <button type="button" class="aps-btn" onClick={() => props.onClose()}>取消</button>
          <button type="button" class="aps-btn light" onClick={applyFetched}>应用到模型列表</button>
        </div>
      </div>
    </div>
  );
}
