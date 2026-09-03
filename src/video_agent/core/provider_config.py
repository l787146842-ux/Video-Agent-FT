"""供应商业务映射与渠道解析（core 层业务逻辑）。

配置加载/解析/Key 管理基础设施已下沉 utils/provider_config_loader.py；
本模块仅保留业务映射常量与渠道解析逻辑。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.utils.provider_config_loader import (  # noqa: F401
    load_merged_providers,
    load_merged_providers_async,
    get_provider_config,
    get_provider_config_async,
    get_api_key,
    get_api_key_async,
    # 旧公开面全量反向 re-export（评审返修）：与 adapters 侧「旧公开面」口径对齐——
    # 历史上这些符号经 core.provider_config 暴露，下沉 utils/provider_config_loader 后
    # 保留 `core.provider_config.<name>` 旧导入路径不变（仅 re-export，实现归 loader）
    load_api_providers,
    save_api_providers,
    DEFAULT_PROVIDERS,
    provider_key_env,
    runninghub_wallet_key_env,
    read_env_keys,
    resolve_api_key,
    update_env_key,
    clear_env_key,
    get_key_preview,
    classify_models,
    detect_protocol,
    IMAGE_KEYWORDS,
    VIDEO_KEYWORDS,
)

# CLI 协议集合（无 Base URL，通过本机 CLI 工具通信）
CLI_PROTOCOLS = {"jimeng", "codex", "gemini-cli"}


def exclude_retired_mock_providers(providers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """mock 演示通道退役过滤的唯一收口点（批次F 退役兼容）。

    存量用户配置里 protocol=mock 的条目不进入任何消费路径
    （下拉框/聊天默认解析/生成 fallback 链/首可用生图兜底）；
    消费方一律经本函数过滤，禁止各自内联判定。
    """
    return [p for p in providers if str(p.get("protocol") or "") != "mock"]


def first_available_image_provider() -> Tuple[str, str]:
    """返回第一个可用的生图供应商 (id, model)，无则返回空串。

    供调用方（如 image_generate 工具）在未指定供应商时兜底解析，
    避免 LLM 传空 provider 导致「供应商 '' 未配置」的生图失败。
    """
    for p in exclude_retired_mock_providers(load_merged_providers()):
        if not p.get("enabled", True):
            continue
        models = [m for m in (p.get("image_models") or []) if m]
        if models:
            return str(p.get("id") or ""), models[0]
    return "", ""


async def first_available_image_provider_async() -> Tuple[str, str]:
    """异步版：第一个可用的生图供应商 (id, model)。"""
    return first_available_image_provider()


# ---------- 规格文档媒体偏好 ----------

_MEDIA_PREF_PATTERNS: Dict[str, re.Pattern] = {
    "image": re.compile(r"(?:图像生成|生图|图片生成)[:：]?\s*([^，,。;；\n]+)"),
    "video": re.compile(r"(?:视频生成|生成视频)[:：]?\s*([^，,。;；\n]+)"),
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*")


def extract_media_preference(text: str, kind: str = "image") -> Tuple[str, str]:
    """从规格文档正文（如「制作偏好」字段）解析媒体生成偏好。

    例：「图像生成 Antigravity CLI auto 模型」→ ('gemini-cli', 'auto')。
    供应商按配置中的显示名包含匹配（忽略大小写，最长名优先防短名误命中）；
    模型在该供应商的模型列表中匹配（容忍一个字符的笔误，如 aotu→auto），
    未命中返回空模型由下层回退链解决。
    """
    pat = _MEDIA_PREF_PATTERNS.get(kind)
    if not pat or not text:
        return "", ""
    m = pat.search(text)
    if not m:
        return "", ""
    seg = m.group(1).strip()
    if not seg:
        return "", ""
    low = seg.lower()
    best_pid, best_name_len = "", 0
    for p in load_merged_providers():
        name = str(p.get("name") or "").strip()
        pid = str(p.get("id") or "")
        if not name or not pid:
            continue
        if name.lower() in low and len(name) > best_name_len:
            best_pid, best_name_len = pid, len(name)
    if not best_pid:
        return "", ""
    cfg = get_provider_config(best_pid) or {}
    models = [x for x in (cfg.get("image_models" if kind == "image" else "video_models") or []) if x]
    model = ""
    for md in models:
        mdl = md.lower()
        if mdl in low:
            model = md
            break
    if not model:  # 笔误容忍：编辑距离≤1 或字符重排（aotu↔auto）
        for token in _TOKEN_RE.findall(low):
            for md in models:
                mdl = md.lower()
                if abs(len(token) - len(mdl)) > 1 or len(mdl) < 3:
                    continue
                diffs = sum(1 for a, b in zip(token, mdl) if a != b)
                if diffs + abs(len(token) - len(mdl)) <= 1 or sorted(token) == sorted(mdl):
                    model = md
                    break
            if model:
                break
    return best_pid, model


def spec_media_preference(raw_state: Dict[str, Any], kind: str = "image") -> Tuple[str, str]:
    """生成渠道单一事实源（顶部「全局设置」，不再扫描规格文档）。

    出图/出视频渠道、图片分辨率、视频分辨率、分镜最大时长由全局设置唯一
    提供，规格文档不再承载这些硬参数；旧规格文档里的残留行也不参与决策。
    未配置返回 ("", "")，调用方提示用户在顶部「全局设置」配置。
    """
    if kind == "video":
        return str(settings.default_video_provider_id or ""), str(settings.default_video_model or "")
    return str(settings.default_image_provider_id or ""), str(settings.default_image_model or "")


# selected_type（前端 DraftType）→ 状态快照列表键。按卡类型解析（任务 #20）：
# 分区内本身混有出图/出视频/出音频三种卡，禁止「分区 → 媒体类型」映射。
_SELECTED_TYPE_TO_CAT = {
    "keyElement": CAT_KEY_ELEMENTS, "shot": CAT_SHOTS, "audio": CAT_AUDIO_ITEMS,
}


def find_selected_draft(
    raw_state: Dict[str, Any], selected_draft_id: str, selected_type: str,
) -> Optional[Dict[str, Any]]:
    """按 selected_draft_id/selected_type 定位目标草稿卡；未命中/空选择返 None。"""
    if not str(selected_draft_id or "").strip():
        return None
    cat = _SELECTED_TYPE_TO_CAT.get(selected_type, selected_type)
    for group in (raw_state.get(cat) or []):
        if not isinstance(group, dict):
            continue
        for draft in (group.get("drafts") or []):
            if isinstance(draft, dict) and draft.get("id") == selected_draft_id:
                return draft
    return None


def resolve_selected_draft_media_config(
    raw_state: Dict[str, Any], selected_draft_id: str, selected_type: str,
    kind: str = "image",
) -> Tuple[str, str]:
    """按卡类型解析目标草稿卡自身的媒体渠道配置 (provider, second)。

    用户裁决口径（任务 #20）：任何媒体生成的参数继承目标草稿卡自身的配置，
    与分区无关。second 语义：image→画面比例；video/audio→模型。
    优先级 = 用户显式指定 > 草稿卡自身 > 全局默认渠道（protocol.md 生成渠道来源规则）；
    卡无 provider 时回落全局默认渠道，无全局默认返回空（绝不臆造）；
    旧共享字段 providerId/model 保留作旧数据回退。
    """
    if kind == "video":
        pid_field, model_field = "videoProviderId", "videoModel"
    elif kind == "audio":
        pid_field, model_field = "audioProviderId", "audioModel"
    else:
        pid_field, model_field = "imageProviderId", "imageModel"
    draft = find_selected_draft(raw_state, selected_draft_id, selected_type)
    if draft is None:
        if kind == "video":
            return str(settings.default_video_provider_id or ""), str(settings.default_video_model or "")
        if kind == "audio":
            return "", ""
        return str(settings.default_image_provider_id or ""), ""
    provider = str(draft.get(pid_field) or draft.get("providerId") or "").strip()
    if kind == "image":
        # 画面比例与 provider 独立返回（卡未配 provider 时比例仍生效）
        return provider or str(settings.default_image_provider_id or ""), str(draft.get("aspectRatio") or "")
    model = str(draft.get(model_field) or draft.get("model") or "").strip()
    if not provider:
        if kind == "video":
            return str(settings.default_video_provider_id or ""), str(settings.default_video_model or "")
        return "", ""
    return provider, model


def spec_production_params(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """制作参数单一事实源（顶部「全局设置」，不再扫描规格文档）。

    agent 执行生图/出视频/拆分镜时据此主动填入对应参数栏；
    规格文档不再承载这些硬参数，旧文档残留行也不参与决策。
    """
    from src.video_agent.state.provider_prefs import resolve_spec_production_params

    return resolve_spec_production_params(raw_state)


def apply_spec_channel_selections(content: str, reply: str) -> Tuple[str, List[str]]:
    """把用户回应里的渠道选择（「厂商显示名 / 模型名」逐行）落盘到规格文档。

    按供应商显示名匹配（大小写不敏感），模型名命中 image_models → 图像生成、
    video_models → 视频生成；未命中供应商或模型一律 noop。返回 (新正文, 已定稿项)。
    """
    providers = load_merged_providers()
    new_content = str(content or "")
    applied: List[str] = []
    for line in str(reply or "").splitlines():
        line = line.strip()
        if "/" not in line:
            continue
        name, _, model = line.partition("/")
        name = name.strip()
        model = model.strip()
        prov = next(
            (p for p in providers
             if str(p.get("name") or "").strip().lower() == name.lower()),
            None,
        )
        if not prov:
            continue
        kind = ""
        if model and model in (prov.get("image_models") or []):
            kind = "图像生成"
        elif model and model in (prov.get("video_models") or []):
            kind = "视频生成"
        elif not model:
            if prov.get("image_models"):
                kind = "图像生成"
                model = str((prov.get("image_models") or [""])[0])
            elif prov.get("video_models"):
                kind = "视频生成"
                model = str((prov.get("video_models") or [""])[0])
        if not kind:
            continue
        label = f"{name} {model}".strip()
        key_re = re.compile(rf"(?im)^(\s*(?:[-*]\s*)?{kind}\s*[:：]).*$")
        replaced = False

        def _sub(m):
            nonlocal replaced
            replaced = True
            return f"{m.group(1)}{label}"

        new_content = key_re.sub(_sub, new_content)
        if not replaced:
            new_content = new_content.rstrip() + f"\n- {kind}：{label}\n"
        applied.append(f"{kind} {label}")
    return new_content, applied


def stamp_draft_spec_preference(raw_state: Dict[str, Any], draft: Dict[str, Any], cat_key: str) -> bool:
    """新建草稿时补印全局默认（草稿无值时被前端硬编码首选供应商回填污染）。

    补印顺序：分辨率/时长全局默认（草稿自带不覆盖）→ 供应商/模型
    （唯一权威源=全局设置；仅当草稿未自带 providerId 时补印，
    防前端默认首选供应商回填污染——参数栏与全局设置不一致；
    audioItems 跳过供应商补印）。返回是否发生补印。"""
    if not isinstance(draft, dict):
        return False
    stamped = False
    # 分辨率/时长全局默认（与供应商无关，先补）
    if cat_key == CAT_KEY_ELEMENTS and not str(draft.get("imageResolution") or "").strip():
        draft["imageResolution"] = settings.default_image_resolution
        stamped = True
    if cat_key == CAT_SHOTS and str(draft.get("mediaType") or "").strip().lower() == "video":
        if not str(draft.get("resolution") or "").strip():
            draft["resolution"] = settings.default_video_resolution
            stamped = True
        if not str(draft.get("duration") or "").strip():
            draft["duration"] = f"{settings.max_shot_duration}s"
            stamped = True
    if cat_key == CAT_AUDIO_ITEMS:
        return stamped
    kind = "image"
    if cat_key == CAT_SHOTS and str(draft.get("mediaType") or "").strip().lower() == "video":
        kind = "video"
    # 按种类参数隔离：补印写本种类字段，旧共享字段同步保留供旧链路回退
    pid_field = "imageProviderId" if kind == "image" else "videoProviderId"
    model_field = "imageModel" if kind == "image" else "videoModel"
    if str(draft.get(pid_field) or draft.get("providerId") or "").strip():
        return stamped
    pid, model = spec_media_preference(raw_state, kind)
    if not pid:
        # 规格文档无偏好 → 全局设置默认渠道
        if kind == "image":
            pid, model = settings.default_image_provider_id, settings.default_image_model
        else:
            pid, model = settings.default_video_provider_id, settings.default_video_model
    if not pid:
        return stamped
    draft[pid_field] = pid
    draft["providerId"] = pid
    stamped = True
    if model and not str(draft.get(model_field) or draft.get("model") or "").strip():
        draft[model_field] = model
        draft["model"] = model
    return True


def resolve_provider_ref(ref: str) -> str:
    """解析供应商标识：优先内部 id 精确匹配；未命中时按显示名
    （API 配置页名称，如 Grsai / Antigravity CLI）忽略大小写匹配并返回其 id。

    LLM 在 action 中传供应商时常用界面上看到的显示名而非内部 id，
    不解析会报「供应商未配置」。
    """
    if not ref:
        return ""
    ref = str(ref).strip()
    providers = load_merged_providers()
    for p in providers:
        if p.get("id") == ref:
            return ref
    rl = ref.lower()
    for p in providers:
        if str(p.get("name") or "").strip().lower() == rl:
            pid = str(p.get("id") or "")
            if pid:
                logger.info(f"[ProviderConfig] 供应商显示名 '{ref}' → 内部 id '{pid}'")
                return pid
    return ref


async def resolve_provider_ref_async(ref: str) -> str:
    """异步版：解析供应商标识（显示名 → 内部 id）"""
    return resolve_provider_ref(ref)
