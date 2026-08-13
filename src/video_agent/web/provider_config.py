"""
供应商配置与 API Key 的唯一读写入口。

之前 routes/agent.py、routes/generate.py、routes/providers.py 各自维护一份
_get_provider_config / _get_api_key / 模型分类逻辑，已全部收敛到这里。

- 供应商配置：data/api_providers.json
- API Key：进程环境变量优先，其次 API/.env
- .env 写入带消毒（去换行）与线程锁，防止 value 注入其他键
"""
import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR, API_DIR, PROVIDERS_FILE, ENV_FILE
from src.video_agent.web.provider_models import validate_providers

# 同时保护 providers 文件与 .env 文件的读写
_config_lock = threading.Lock()

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# CLI 协议集合（无 Base URL，通过本机 CLI 工具通信）
CLI_PROTOCOLS = {"jimeng", "codex", "gemini-cli"}

# ---------- 默认 Provider 配置 ----------
DEFAULT_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "mock",
        "name": "Mock (本地测试)",
        "base_url": "",
        "protocol": "mock",
        "enabled": True,
        "primary": False,
        "image_models": ["mock-image"],
        "chat_models": ["mock-chat"],
        "video_models": ["mock-video"],
    },
    {
        "id": "modelscope",
        "name": "ModelScope",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "protocol": "openai",
        "enabled": True,
        "primary": False,
        "image_models": ["Tongyi-MAI/Z-Image-Turbo", "Qwen/Qwen-Image-2512"],
        "chat_models": ["Qwen/Qwen3-235B-A22B", "Qwen/Qwen2.5-72B-Instruct"],
        "video_models": ["Wan-AI/Wan2.1-T2V-14B"],
    },
]


# ---------- 供应商配置 ----------

def load_api_providers() -> List[Dict[str, Any]]:
    """从 JSON 文件加载 provider 配置；不存在或损坏时回退默认配置。加载后进行 Pydantic 校验。"""
    with _config_lock:
        if PROVIDERS_FILE.exists():
            try:
                data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return validate_providers(data)
                logger.warning("[ProviderConfig] api_providers.json 不是列表，回退默认配置")
            except Exception as e:
                logger.warning(f"[ProviderConfig] 读取配置失败: {e}，回退默认配置")
        return [dict(p) for p in DEFAULT_PROVIDERS]


def save_api_providers(providers: List[Dict[str, Any]]) -> None:
    """保存 provider 配置（原子写）"""
    with _config_lock:
        atomic_write_text(PROVIDERS_FILE, json.dumps(providers, ensure_ascii=False, indent=2))
    logger.info(f"[ProviderConfig] 已保存 {len(providers)} 个供应商配置")


# ---------- 画布配置共享（本地兜底 + 画布增强） ----------

# 缓存画布 provider id 集合（路由判断用）
_canvas_ids_cache: Optional[Set[str]] = None
_canvas_ids_cache_time: float = 0.0


def load_canvas_providers() -> List[Dict[str, Any]]:
    """从画布读取 provider 配置（HTTP 优先，文件兜底）。
    任何异常均静默返回 []，不影响 Agent 正常运行。"""
    # 1. 尝试 HTTP API
    try:
        resp = httpx.get(settings.canvas_providers_url, timeout=3.0, trust_env=False)
        if resp.status_code == 200:
            data = resp.json()
            providers = data.get("providers", [])
            if isinstance(providers, list) and providers:
                logger.debug(f"[ProviderConfig] 从画布 HTTP 读取到 {len(providers)} 个 provider")
                return providers
    except Exception:
        pass  # 画布不在线，静默跳过

    # 2. 兜底：读磁盘文件（环境变量未配置时跳过）
    try:
        if settings.canvas_providers_file:
            canvas_file = Path(settings.canvas_providers_file)
            if canvas_file.exists():
                data = json.loads(canvas_file.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    logger.debug(f"[ProviderConfig] 从画布文件读取到 {len(data)} 个 provider")
                    return data
    except Exception:
        pass  # 文件不存在或损坏，静默跳过

    return []


def load_merged_providers() -> List[Dict[str, Any]]:
    """合并本地 + 画布的 provider 列表（按 id 去重，画布优先 + 模型并集）。

    合并规则：
    - 两者 id 相同时，连接设置（base_url/protocol/name）用画布的（已验证）
    - 模型列表（image_models/chat_models/video_models）取并集去重
    - 画布没有而本地有的 provider，保留本地配置
    - 本地没有而画布有的 provider，追加画布配置
    同时更新 canvas_provider_ids 缓存供路由层使用。"""
    global _canvas_ids_cache, _canvas_ids_cache_time

    local = load_api_providers()
    canvas = load_canvas_providers()

    canvas_ids = {p.get("id") for p in canvas if p.get("id")}
    local_map = {p.get("id"): p for p in local if p.get("id")}

    _MODEL_FIELDS = ("image_models", "chat_models", "video_models")

    # 画布优先：id 相同时用画布版本，但模型列表取并集
    merged: List[Dict[str, Any]] = []
    for p in canvas:
        pid = p.get("id", "")
        if not pid:
            continue
        item = dict(p)
        item["_source"] = "canvas"
        # 如果本地也有同 id 的 provider，合并模型列表
        local_p = local_map.get(pid)
        if local_p:
            for field in _MODEL_FIELDS:
                canvas_models = list(item.get(field) or [])
                local_models = list(local_p.get(field) or [])
                # 并集去重（保持顺序：画布在前，本地补充）
                seen = set(canvas_models)
                union = list(canvas_models)
                for m in local_models:
                    if m not in seen:
                        union.append(m)
                        seen.add(m)
                item[field] = union
        merged.append(item)

    # 本地中 id 不在画布的追加（本地独有）
    for p in local:
        pid = p.get("id", "")
        if pid and pid not in canvas_ids:
            merged.append(p)

    # 更新缓存（路由层用于判断 provider 是否画布可处理）
    _canvas_ids_cache = canvas_ids
    _canvas_ids_cache_time = time.time()

    return merged


async def load_merged_providers_async() -> List[Dict[str, Any]]:
    """异步入口（聊天/工具/生成链路）：合并含画布 HTTP 拉取，事件循环内不阻塞。"""
    return await asyncio.to_thread(load_merged_providers)


def get_canvas_provider_ids() -> Set[str]:
    """获取画布的 provider id 集合（带缓存，供路由层判断用）"""
    global _canvas_ids_cache, _canvas_ids_cache_time
    cache_ttl = settings.canvas_health_cache_seconds
    if _canvas_ids_cache is None or (time.time() - _canvas_ids_cache_time) > cache_ttl:
        # 重新加载以刷新缓存
        load_merged_providers()
    return _canvas_ids_cache or set()


async def get_canvas_provider_ids_async() -> Set[str]:
    """异步版：获取画布 provider id 集合（带缓存，事件循环内不阻塞）"""
    await load_merged_providers_async()
    return _canvas_ids_cache or set()


def get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查找单个供应商配置（从合并列表中查找）"""
    if not provider_id:
        return None
    for p in load_merged_providers():
        if p.get("id") == provider_id:
            return p
    return None


async def get_provider_config_async(provider_id: str) -> Optional[Dict[str, Any]]:
    """异步版：按 id 查找单个供应商配置（从合并列表中查找）"""
    if not provider_id:
        return None
    for p in await load_merged_providers_async():
        if p.get("id") == provider_id:
            return p
    return None


def first_available_image_provider() -> Tuple[str, str]:
    """返回第一个可用的非 mock 生图供应商 (id, model)，无则返回空串。

    供调用方（如 image_generate 工具）在未指定供应商时兜底解析，
    避免 LLM 传空 provider 导致「供应商 '' 未配置」的生图失败。
    """
    for p in load_merged_providers():
        if not p.get("enabled", True):
            continue
        if p.get("protocol") == "mock":
            continue
        models = [m for m in (p.get("image_models") or []) if m]
        if models:
            return str(p.get("id") or ""), models[0]
    return "", ""


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
    """扫描项目状态中的规格文档（documents），解析出生成偏好 (provider_id, model)。

    优先级：规格文档是用户意志的结构化落盘，高于草稿自动回填的默认供应商；
    多个规格文档取首个命中；无命中返回空串。
    """
    try:
        from src.video_agent.core import prompt_gates
    except Exception:
        return "", ""
    for doc in (raw_state.get("documents") or []):
        if not isinstance(doc, dict):
            continue
        if not prompt_gates.is_spec_doc_name(str(doc.get("name") or "")):
            continue
        pid, model = extract_media_preference(str(doc.get("content") or ""), kind)
        if pid:
            return pid, model
    return "", ""


def spec_production_params(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    """从规格文档解析制作参数（图片分辨率/视频分辨率/分镜最大时长）。

    规格交互中用户选定的结构化落盘；agent 执行生图/出视频/拆分镜时
    据此主动填入对应参数栏（7777 二轮）。缺失项为空/None。
    """
    from src.video_agent.state.provider_prefs import resolve_spec_production_params

    return resolve_spec_production_params(raw_state)


def stamp_draft_spec_preference(raw_state: Dict[str, Any], draft: Dict[str, Any], cat_key: str) -> bool:
    """新建草稿时补印全局默认（8888 事故：草稿无值时被前端硬编码首选供应商回填污染）。

    补印顺序：分辨率/时长全局默认（草稿自带不覆盖）→ 供应商/模型
    （规格文档偏好优先，其次全局设置默认；仅当草稿未自带 providerId 时补印，
    audioItems 跳过供应商补印）。返回是否发生补印。"""
    if not isinstance(draft, dict):
        return False
    stamped = False
    # 分辨率/时长全局默认（与供应商无关，先补）
    if cat_key == "keyElements" and not str(draft.get("imageResolution") or "").strip():
        draft["imageResolution"] = settings.default_image_resolution
        stamped = True
    if cat_key == "shots" and str(draft.get("mediaType") or "").strip().lower() == "video":
        if not str(draft.get("resolution") or "").strip():
            draft["resolution"] = settings.default_video_resolution
            stamped = True
        if not str(draft.get("duration") or "").strip():
            draft["duration"] = f"{settings.max_shot_duration}s"
            stamped = True
    if str(draft.get("providerId") or "").strip():
        return stamped
    if cat_key == "audioItems":
        return stamped
    kind = "image"
    if cat_key == "shots" and str(draft.get("mediaType") or "").strip().lower() == "video":
        kind = "video"
    pid, model = spec_media_preference(raw_state, kind)
    if not pid:
        # 规格文档无偏好 → 全局设置默认渠道
        if kind == "image":
            pid, model = settings.default_image_provider_id, settings.default_image_model
        else:
            pid, model = settings.default_video_provider_id, settings.default_video_model
    if not pid:
        return stamped
    draft["providerId"] = pid
    stamped = True
    if model and not str(draft.get("model") or "").strip():
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


def is_mock_provider(provider_id: str, model: str = "") -> bool:
    """判定是否应走 mock 路径：仅当用户显式选择 mock（或什么都没配）"""
    if not provider_id or provider_id == "mock":
        return True
    if model.startswith("mock"):
        return True
    cfg = get_provider_config(provider_id)
    return bool(cfg and cfg.get("protocol") == "mock")


async def is_mock_provider_async(provider_id: str, model: str = "") -> bool:
    """异步版：判断是否为 mock 供应商"""
    return is_mock_provider(provider_id, model)


# ---------- API Key 管理 ----------

def provider_key_env(provider_id: str) -> str:
    """根据 provider id 生成环境变量名"""
    mapping = {
        "modelscope": "MODELSCOPE_API_KEY",
        "volcengine": "ARK_API_KEY",
        "gemini-cli": "GEMINI_API_KEY",
    }
    if provider_id in mapping:
        return mapping[provider_id]
    sanitized = re.sub(r"[^A-Z0-9_]", "_", provider_id.upper().replace("-", "_"))
    return f"API_PROVIDER_{sanitized}_KEY"


def read_env_keys() -> Dict[str, str]:
    """读取 .env 文件中所有键值对"""
    keys: Dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def _read_canvas_env_keys() -> Dict[str, str]:
    """读取画布的 API/.env 文件中的键值对（第三级 fallback）"""
    keys: Dict[str, str] = {}
    if not settings.canvas_env_file:
        return keys
    try:
        canvas_env = Path(settings.canvas_env_file)
        if canvas_env.exists():
            for line in canvas_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
    except Exception:
        pass
    return keys


def get_api_key(provider_id: str) -> str:
    """解析某供应商的 API Key：
    1. 进程环境变量
    2. Agent 本地 API/.env
    3. 画布 API/.env（仅对来源于画布的 provider 启用）
    """
    env_name = provider_key_env(provider_id)
    val = os.getenv(env_name, "")
    if val:
        return val
    val = read_env_keys().get(env_name, "")
    if val:
        return val
    # 第三级：如果该 provider 来源于画布，尝试读画布的 .env
    canvas_ids = get_canvas_provider_ids()
    if provider_id in canvas_ids:
        val = _read_canvas_env_keys().get(env_name, "")
        if val:
            logger.debug(f"[ProviderConfig] Key '{env_name}' 从画布 .env 解析")
            return val
    return ""


async def get_api_key_async(provider_id: str) -> str:
    """异步版：解析某供应商的 API Key（画布 id 集合走异步缓存路径）"""
    env_name = provider_key_env(provider_id)
    val = os.getenv(env_name, "")
    if val:
        return val
    val = read_env_keys().get(env_name, "")
    if val:
        return val
    canvas_ids = await get_canvas_provider_ids_async()
    if provider_id in canvas_ids:
        val = _read_canvas_env_keys().get(env_name, "")
        if val:
            return val
    return ""


def resolve_api_key(api_key: str, provider_id: str) -> str:
    """优先使用调用方传入的 key，否则按 provider 解析"""
    if api_key:
        return api_key
    if provider_id:
        return get_api_key(provider_id)
    return ""


def _sanitize_env_value(value: str) -> str:
    # 去掉换行/回车，防止一条 value 注入出第二个键值对
    return value.replace("\r", "").replace("\n", "").strip()


def update_env_key(env_name: str, value: str) -> None:
    """更新 .env 文件中的某个 key（消毒 + 加锁 + 原子写）"""
    if not _ENV_NAME_RE.match(env_name):
        raise ValueError(f"非法环境变量名: {env_name!r}")
    value = _sanitize_env_value(value)

    with _config_lock:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
        new_lines, found = [], False
        for line in lines:
            if line.strip().startswith(f"{env_name}="):
                new_lines.append(f"{env_name}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{env_name}={value}")
        atomic_write_text(ENV_FILE, "\n".join(new_lines) + "\n")
    os.environ[env_name] = value


def clear_env_key(env_name: str) -> None:
    """清除 .env 文件中的某个 key"""
    if not _ENV_NAME_RE.match(env_name):
        raise ValueError(f"非法环境变量名: {env_name!r}")
    with _config_lock:
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
            new_lines = [l for l in lines if not l.strip().startswith(f"{env_name}=")]
            atomic_write_text(ENV_FILE, "\n".join(new_lines) + "\n")
    os.environ.pop(env_name, None)


def get_key_preview(env_name: str) -> Tuple[bool, str]:
    """返回 (has_key, key_preview)，preview 只露末 4 位"""
    value = os.getenv(env_name, "") or read_env_keys().get(env_name, "")
    if value:
        return True, f"••••••••{value[-4:]}" if len(value) > 4 else "••••"
    return False, ""


# ---------- 模型分类 / 协议检测 ----------

IMAGE_KEYWORDS = ["image", "img", "flux", "sdxl", "dall", "kolors", "z-image",
                  "wanx", "cogview", "jimeng", "imagen", "gpt-image"]
VIDEO_KEYWORDS = ["video", "veo", "sora", "kling", "seedance", "wan2", "cogvideo",
                  "runway", "pika", "t2v", "i2v"]


def classify_models(all_models: List[str]) -> Dict[str, List[str]]:
    """自动将模型列表分类为 image/chat/video"""
    image_models: List[str] = []
    video_models: List[str] = []
    chat_models: List[str] = []
    for m in all_models:
        ml = m.lower()
        if any(kw in ml for kw in VIDEO_KEYWORDS):
            video_models.append(m)
        elif any(kw in ml for kw in IMAGE_KEYWORDS):
            image_models.append(m)
        else:
            chat_models.append(m)
    return {"image_models": image_models, "chat_models": chat_models, "video_models": video_models}


def detect_protocol(base_url: str, fallback: str = "openai") -> str:
    """根据 URL 特征检测协议类型"""
    bl = base_url.lower()
    if "runninghub" in bl:
        return "runninghub"
    if "volces.com" in bl or "volcengine" in bl or "ark.cn" in bl:
        return "volcengine"
    return fallback
