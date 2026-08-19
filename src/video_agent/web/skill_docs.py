"""
Skill 文档化存储层。

对标 FTDYB：Skill 不是代码里的一段提示词，而是用户可见、可编辑的 Markdown 文档，
存放在 data/skills/。渐进式披露：上下文只注入 Skill 目录（名称+摘要），
全文由模型调 read_skill 按需加载——"流程即数据"。

文档格式约定：
    # Skill 名称
    > 调用规则：一句话说明何时使用本 Skill
    ## 流程规划
    ……正文……
"""
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import SKILL_DOCS_DIR
# 五轮 S6：标题式解析静默沿用的降级遥测（顶层化，宪法第六章禁方法内 import）
from src.video_agent.core import live_metrics
# N7（三轮审核）：pause_rules 解析定义下沉 skill_runtime.registry，本处顶层 re-export 保留兼容导入路径
from src.video_agent.skill_runtime.registry import parse_pause_rules, _PAUSE_RULES_BLOCK_RE  # noqa: F401

_SLUG_RE = re.compile(r"^[\w一-鿿-]{1,64}$")  # 允许中英文/数字/下划线/连字符

# audit-0819d：外来工具名映射层（FOREIGN_TOOL_MAP + build_foreign_tool_note）
# 已删除（S15 清偿，用户裁决）：运行时不再做工具名翻译；进项目的 Skill
# 必须在导入期改为本项目的工具名（归将来专用 Skill 系统职责）。

# 版本历史：保存前把旧版备份到 .history/，每个 slug 保留最近 N 版
_HISTORY_DIR_NAME = ".history"
_HISTORY_MAX = 10

# ---------- Skill 章节分阶段解析（分段聚焦注入用） ----------
# 外来 Skill（如 flova 导出）原生就是「每个工具一节」的结构（<planner>/<write_the_prompt>…），
# 它们的运行时把各节分别注入对应阶段的子工具；本系统把全文一次性注入单一编排模型，
# 只能靠「识别当前阶段 → 重复强调对应章节」来逼近同等遵循度。
# 值支持一对多：旧 tag（如 storyboard_designer）三拆重构后同时映射到全部拆分 stage，
# 保证存量 Skill 的整节内容对三个拆解执行器同等注入（与旧执行器语义一致）
SECTION_TAG_STAGES: Dict[str, Union[str, Tuple[str, ...]]] = {
    "planner": "planning",
    "resource_prepare_and_analyze": "planning",
    "multimodal_analyze_tool": "planning",
    "script_analyze": "planning",
    "text_editor": "planning",
    "storyboard_designer": ("storyboard_ke", "storyboard_shot", "storyboard_audio"),
    "storyboard_key_elements": "storyboard_ke",
    "storyboard_shots": "storyboard_shot",
    "storyboard_audio": "storyboard_audio",
    "write_media_prompt": "prompt_draft",
    "write_the_prompt": "prompt_draft",
    "media_generator": "generation",
    "generation": "generation",
    "video_assembler": "assembly",
    "reply_to_user": "",
}

# 本地改写版 Skill（标题式）的标题关键字 → 阶段兜底映射（按顺序首个命中生效：
# 精确子标题优先于笼统的「故事板设计」；值支持一对多，同 tag 映射语义）
_HEADING_STAGE_HINTS: List[Tuple[Tuple[str, ...], Union[str, Tuple[str, ...]]]] = [
    (("提示词写法", "提示词规范", "prompt 编写", "prompt编写"), "prompt_draft"),
    (("关键元素",), "storyboard_ke"),
    (("分镜设计", "镜头列表", "镜头设计", "分镜"), "storyboard_shot"),
    (("音频层", "音频设计"), "storyboard_audio"),
    (("故事板设计", "故事板规范"), ("storyboard_ke", "storyboard_shot", "storyboard_audio")),
    (("生成规范", "元素生成", "视频生成"), "generation"),
    (("组装", "导出"), "assembly"),
    (("流程规划", "阶段逻辑", "依赖关系"), "planning"),
]


def _stage_from_heading(heading: str) -> Union[str, Tuple[str, ...]]:
    """标题关键字 → 阶段（可为 tuple 一对多）；未命中返回空串"""
    h = (heading or "").strip()
    for hints, stage in _HEADING_STAGE_HINTS:
        if any(k in h for k in hints):
            return stage
    return ""


def split_skill_sections(content: str) -> Dict[str, str]:
    """把 Skill 全文拆成 阶段 → 章节文本（同阶段多节合并）。

    支持两种格式：
    1. flova 原生 <tag>…</tag> 章节（tag 按 SECTION_TAG_STAGES 映射到阶段）；
    2. 本地改写的 Markdown 标题式（按 _HEADING_STAGE_HINTS 关键字兜底，
       未映射标题下的正文沿用上一个已识别阶段）。
    未识别章节不返回（全文本就整体注入，本函数只服务于分阶段聚焦再强调）。
    """
    content = content or ""
    collected: Dict[str, List[str]] = {}

    def _add(stage: Union[str, Tuple[str, ...]], body: str) -> None:
        body = (body or "").strip()
        if not body:
            return
        stages = stage if isinstance(stage, tuple) else (stage,)
        for s in stages:
            if s:
                collected.setdefault(s, []).append(body)

    # 1) <tag> 章节（flova 原生格式）
    tag_alt = "|".join(re.escape(t) for t in SECTION_TAG_STAGES)
    tag_re = re.compile(rf"<(?P<tag>{tag_alt})>(?P<body>.*?)</(?P=tag)>", re.S | re.I)
    found_tag = False
    for m in tag_re.finditer(content):
        found_tag = True
        _add(SECTION_TAG_STAGES.get(m.group("tag").lower(), ""), m.group("body"))
    if found_tag:
        return {k: "\n\n".join(v) for k, v in collected.items()}

    # 2) Markdown 标题兜底
    parts = re.split(r"(?m)^(#{1,4}[^\n]*)$", content)
    stage_now = ""
    # 五轮 S6/#6：静默沿用告警——连续 ≥3 节未命中关键字而沿用上一阶段时，
    # 说明该 Skill 的标题体系可能整体未映射（章节会被静默归错阶段），
    # 记 warning + 降级遥测供排查（不阻断解析）
    _inherit_run = 0
    _inherit_warned = False
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("#").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        mapped = _stage_from_heading(heading)
        if mapped:
            stage_now = mapped
            _inherit_run = 0
        elif stage_now:
            _inherit_run += 1
            if _inherit_run >= 3 and not _inherit_warned:
                _inherit_warned = True
                logger.warning(
                    f"[SkillDocs] 标题式章节解析连续 {_inherit_run} 节未命中阶段关键字"
                    f"（沿用「{stage_now}」），章节可能归错阶段：请核查该 Skill 的标题体系"
                )
                live_metrics.record_degradation("skill_docs.heading_fallback")
        _add(stage_now, body)
    return {k: "\n\n".join(v) for k, v in collected.items()}

DEFAULT_SKILL_SLUG = "script-to-video"
DEFAULT_SKILL_DOC = """# 剧本生视频（需上传剧本）

```json skill_manifest
{
  "gates": {
    "require_duration": true,
    "require_subtitle": true,
    "require_camera_language": true,
    "require_audio_layer": true,
    "require_at_ref": true
  },
  "flow": {
    "spec_wizard": true,
    "spec_stage_trim": true,
    "spec_gate": true
  },
  "pause": {
    "stage_pause": true
  }
}
```

> 调用规则：用户上传剧本/故事文档以生成视频时使用。在关键阶段暂停以供用户确认；
> 所有图片/视频/音频生成必须经用户明确指令才能执行，Agent 不自动触发（系统生成确认闸会拦截未确认的生成）。

## 流程规划（三段式：规划 → 提示词草案 → 生成）

### 第一段：规划结构
1. 剧本正文不会自动注入上下文：先用 read_uploaded_doc 读取剧本全文；
   若 documents 清单里已有规格文档，先用 read_project_doc 读取并遵守；
   然后分析素材 → document_write(制片规格.md) → workflow_pause
2. 规划故事板：storyboard_create_group keyElement(只写 title+desc) + storyboard_create_group shot(只写 title+shotType+sceneRefs+roughDesc+duration)
   此阶段不写详细提示词 → workflow_pause "故事板已建立，请审阅"

### 第二段：提示词草案
3. 用户确认后：为关键元素写入详细生图提示词(storyboard_patch_draft) → workflow_pause "尚未生成任何画面"
4. 用户确认后：为分镜写入详细视频提示词(storyboard_patch_draft) → workflow_pause

### 第三段：生成（用户明确发起）
5. 用户说"生成概念图" → image_generate(target="all_keyElements")
6. 用户说"生成关键帧" → image_generate(target="all_shots")，自动注入 sceneRefs 参考图

### 【铁律】
- 规划阶段不写详细提示词，只建结构
- 提示词草案阶段不触发任何生成
- "确认" ≠ "生成"，生成需要用户额外指令

## 提示词写法
- 中文分层描述 + 英文风格标签收尾
- 只写客观可见画面，禁止解释角色内心
- 关键元素 prompt ≥ 100 字，分镜关键帧 ≥ 60 字
- 视频提示词必含镜头运动指令 + 时间节奏
"""


def ensure_default_skill_docs() -> None:
    """启动时确保至少存在默认 Skill 文档"""
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not any(SKILL_DOCS_DIR.glob("*.md")):
        atomic_write_text(SKILL_DOCS_DIR / f"{DEFAULT_SKILL_SLUG}.md", DEFAULT_SKILL_DOC)
        logger.info(f"[SkillDocs] 已生成默认 Skill 文档: {DEFAULT_SKILL_SLUG}.md")
    _refresh_runtime_registry()


def _refresh_runtime_registry() -> None:
    """把 data/skills 与 skill_runtime 注册表同步（上传/编辑/删除/启动均调用）。"""
    try:
        from src.video_agent.skill_runtime.registry import sync_all

        sync_all()
    except Exception as e:  # 注册失败不阻断文档系统
        logger.warning(f"[SkillDocs] Skill 执行器注册表同步失败: {e}")


def _parse_doc(slug: str, content: str) -> Dict[str, Any]:
    name = slug
    description = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# ") and name == slug:
            name = line[2:].strip()
        elif line.startswith(">") and not description:
            description = line.lstrip("> ").strip()
        if name != slug and description:
            break
    return {"id": f"doc:{slug}", "slug": slug, "name": name,
            "description": description, "content": content}


def _validate_slug(slug: str) -> str:
    slug = slug.strip()
    if not _SLUG_RE.match(slug) or slug in (".", ".."):
        raise ValueError(f"非法 Skill 标识: {slug!r}")
    return slug


def list_skill_docs() -> List[Dict[str, Any]]:
    ensure_default_skill_docs()
    docs = []
    for f in sorted(SKILL_DOCS_DIR.glob("*.md")):
        try:
            docs.append(_parse_doc(f.stem, f.read_text(encoding="utf-8")))
        except OSError as e:
            logger.warning(f"[SkillDocs] 读取失败 {f.name}: {e}")
    return docs


def get_skill_doc(slug: str) -> Optional[Dict[str, Any]]:
    slug = _validate_slug(slug)
    f = SKILL_DOCS_DIR / f"{slug}.md"
    if not f.exists():
        return None
    return _parse_doc(slug, f.read_text(encoding="utf-8"))


def save_skill_doc(slug: str, content: str) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    if not content.strip():
        raise ValueError("Skill 文档内容不能为空")
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    target = SKILL_DOCS_DIR / f"{slug}.md"
    # 覆盖前备份旧版（版本历史，供文档面板查看/回滚）
    if target.exists():
        _backup_skill_doc(slug, target)
    atomic_write_text(target, content)
    logger.info(f"[SkillDocs] 已保存 Skill 文档: {slug}.md")
    try:
        from src.video_agent.skill_runtime.registry import refresh_skill

        refresh_skill(slug)
    except Exception as e:
        logger.warning(f"[SkillDocs] Skill 执行器注册刷新失败 {slug}: {e}")
    return _parse_doc(slug, content)


def _backup_skill_doc(slug: str, target: Path) -> None:
    """把旧版备份到 .history/{slug}-{毫秒时间戳}.md，并只保留最近 _HISTORY_MAX 版。

    用毫秒时间戳命名（位数固定）：字典序 = 时序，同毫秒冲突时递增。
    """
    try:
        hdir = SKILL_DOCS_DIR / _HISTORY_DIR_NAME
        hdir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        backup = hdir / f"{slug}-{stamp}.md"
        while backup.exists():
            stamp += 1
            backup = hdir / f"{slug}-{stamp}.md"
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        # 裁剪：仅保留最近 _HISTORY_MAX 版（按文件名时间戳排序）
        versions = sorted(hdir.glob(f"{slug}-*.md"), key=lambda p: p.name)
        for old in versions[:-_HISTORY_MAX]:
            old.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"[SkillDocs] 版本备份失败 {slug}: {e}")


def prune_all_skill_history() -> int:
    """B6/F44：启动时裁剪全部 Skill 历史——每 slug 只保留最近 _HISTORY_MAX 版。

    历史文件的堆积来自保存时的增量裁剪与旧版本遗留；此函数按 slug 分组
    （文件名 `{slug}-{毫秒时间戳}.md`）做一次全量收敛，返回删除数。"""
    hdir = SKILL_DOCS_DIR / _HISTORY_DIR_NAME
    if not hdir.exists():
        return 0
    removed = 0
    by_slug: Dict[str, List[Any]] = {}
    for f in hdir.glob("*.md"):
        base = f.name
        if "-" not in base:
            continue
        slug = base.rsplit("-", 1)[0]
        by_slug.setdefault(slug, []).append(f)
    for slug, files in by_slug.items():
        files.sort(key=lambda p: p.name, reverse=True)
        for old in files[_HISTORY_MAX:]:
            try:
                old.unlink(missing_ok=True)
                removed += 1
            except OSError as _e:
                logger.debug("[skill_docs] 忽略异常: {}", _e)
    if removed:
        logger.info(f"[SkillDocs] 历史版本收敛：删除 {removed} 个过期备份")
    return removed


def list_skill_doc_history(slug: str) -> List[Dict[str, Any]]:
    """列出某 Skill 文档的历史版本（新→旧，含全文，供查看/回滚）"""
    slug = _validate_slug(slug)
    hdir = SKILL_DOCS_DIR / _HISTORY_DIR_NAME
    if not hdir.exists():
        return []
    items: List[Dict[str, Any]] = []
    for f in sorted(hdir.glob(f"{slug}-*.md"), key=lambda p: p.name, reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # 版本名 = 文件名去掉 slug 前缀（即时间戳部分）
        version = f.stem[len(slug) + 1:]
        items.append({"version": version, "content": content})
    return items


def delete_skill_doc(slug: str) -> None:
    """删除指定 Skill 文档，不存在时抛出 ValueError"""
    slug = _validate_slug(slug)
    f = SKILL_DOCS_DIR / f"{slug}.md"
    if not f.exists():
        raise ValueError(f"Skill 文档 '{slug}' 不存在")
    f.unlink()
    logger.info(f"[SkillDocs] 已删除 Skill 文档: {slug}.md")
    try:
        from src.video_agent.skill_runtime.registry import unregister_skill

        unregister_skill(slug)
    except Exception as e:
        logger.warning(f"[SkillDocs] Skill 执行器注销失败 {slug}: {e}")


# Skill 暂停点显式声明解析已下沉 skill_runtime.registry（N7），本文件经顶部 import re-export。
# gate_rules 块格式校验用（与 prompt_gates.parse_gate_rules 的正则保持一致）
_GATE_RULES_LINT_RE = re.compile(
    r"```(?:json|js)?\s*gate_rules\s*\n(.*?)```", re.S | re.I
)

# Skill 平台行为统一声明块正则（0818 B4：声明已迁 sidecar，
# 本正则仅用于 lint 提示「文档内 manifest 不再消费」）
_SKILL_MANIFEST_BLOCK_RE = re.compile(
    r"```(?:json|js)?\s*skill_manifest\s*\n(.*?)```", re.S | re.I
)

# B7 用户裁决：Skill 内写死的模型能力参数检测（厂商/模型/分辨率/时长），
# 保存/导入时 lint 提示「已作废，以全局设置为准」；运行时一律忽略
_MODEL_PARAM_LINT_RE = re.compile(
    r"(Seedance|GPT\s*Image|Kling|可灵|即梦|Midjourney|Flux|SDXL|"
    r"Runway|Vidu|Sora|Veo|Pika|Hailuo|海螺|万相|通义|1K|2K|4K|"
    r"480p|720p|1080p|4K高清|60fps|24fps)"
)


def lint_skill_content(content: str) -> Dict[str, Any]:
    """Skill 文档保存时 lint：把注册结果/规则合法性提示前移到编辑时。

    返回 {"available_tools": [...], "warnings": [...]}；不阻断保存，
    由路由层随 PUT 响应下发，前端以 toast/详情展示。
    """
    from src.video_agent.skill_runtime.registry import SKILL_EXECUTOR_TOOLS, TOOL_STAGES

    warnings: List[str] = []
    content = content or ""
    sections = split_skill_sections(content)
    available = [
        t for t in SKILL_EXECUTOR_TOOLS
        if any((sections.get(s) or "").strip() for s in TOOL_STAGES.get(t, ()))
    ]
    if not available:
        warnings.append(
            "未识别到任何执行器章节：选中该 Skill 时将回退全文注入模式，无独立执行器可用"
        )
    # 三拆部分缺失：故事板章节只覆盖了部分拆解执行器
    split_tools = ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")
    present = [t for t in split_tools if t in available]
    if present and len(present) < 3:
        missing = [t for t in split_tools if t not in available]
        warnings.append("故事板章节仅覆盖部分拆解执行器，未注册：" + "、".join(missing))
    # gate_rules 块格式校验（非法时 prompt_gates 静默回落默认，这里显式告知）
    gm = _GATE_RULES_LINT_RE.search(content)
    if gm:
        try:
            data = json.loads(gm.group(1))
            if not isinstance(data, dict):
                warnings.append("gate_rules 不是 JSON 对象，已回落默认闸机规则")
        except Exception:
            warnings.append("gate_rules JSON 解析失败，已回落默认闸机规则")
    # 0818 B4：声明迁 sidecar——文档内 manifest 块不再消费，显式提示
    if _SKILL_MANIFEST_BLOCK_RE.search(content):
        warnings.append(
            "skill_manifest 块不再消费：平台声明已迁 sidecar（data/skills_manifests/），请从文档移除该块"
        )
    elif gm or _PAUSE_RULES_BLOCK_RE.search(content):
        warnings.append(
            "检测到旧式 gate_rules/pause_rules 块：建议迁移为 sidecar 声明"
            "（并存时两块各自表述属于指令分身）"
        )
    # 暂停声明检测（仅提示不阻断；sidecar pause.stage_pause 在注册期校验，
    # 编辑期只看正文关键词/pause_rules）
    if (
        parse_pause_rules(content) is None
        and "何时暂停" not in content
        and "强制暂停点" not in content
    ):
        warnings.append(
            "未检测到阶段暂停声明（可加 ```json pause_rules {\"stage_pause\": true}``` 或写明「何时暂停」），"
            "执行器完成后将不会主动邀请用户确认"
        )
    # B7 用户裁决：模型能力参数唯一权威源 = 全局设置——Skill 内写死的
    # 厂商/模型/分辨率/时长参数一律作废（运行时忽略，仅提示迁移）
    _hard_params = _MODEL_PARAM_LINT_RE.findall(content)
    if _hard_params:
        warnings.append(
            "检测到写死的模型能力参数（" + "、".join(sorted(set(_hard_params))[:6])
            + " 等）：已作废——出图/出视频渠道、分辨率、时长以「全局设置」为唯一权威源，"
            "运行时不会采用本文档中的这些参数"
        )
    return {"available_tools": available, "warnings": warnings}


def _norm_skill_name(s: str) -> str:
    """Skill 名称归一化：去空格/后缀/大小写"""
    s = (s or "").strip().casefold()
    for ext in (".md", ".txt"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.replace(" ", "")


def resolve_skill_content(wanted: str) -> tuple:
    """按名称解析 Skill 全文（仅文档 Skill，模糊匹配）。

    read_skill 工具与 Planner 选中项硬注入共用同一套解析，保证两处行为一致。
    代码内置 Skill（编剧/分镜师/制片）已彻底移除，不再是解析来源。
    返回 (display_name, content)，未命中返回 ("", "")。
    """
    wanted = (wanted or "").strip()
    wn = _norm_skill_name(wanted)
    if not wn:
        return "", ""

    candidates: List[Dict[str, Any]] = []
    try:
        candidates += [
            {"name": d.get("name", ""), "alias": d.get("slug", ""), "content": d.get("content", "")}
            for d in list_skill_docs()
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SkillDocs] Skill 目录读取失败: {e}")

    def names(c: Dict[str, Any]) -> List[str]:
        return [str(c.get("name", "")), str(c.get("alias", ""))]

    # 1. 精确 → 2. 归一化相等 → 3. 双向包含（防单字误匹配）
    for c in candidates:
        if wanted in names(c):
            return str(c.get("name", "")), str(c.get("content", ""))
    for c in candidates:
        if any(_norm_skill_name(n) == wn for n in names(c) if n):
            return str(c.get("name", "")), str(c.get("content", ""))
    if len(wn) >= 2:
        for c in candidates:
            for n in names(c):
                nn = _norm_skill_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    return str(c.get("name", "")), str(c.get("content", ""))
    return "", ""
