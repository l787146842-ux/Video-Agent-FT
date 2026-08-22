"""
Skill 文档化存储层。

对标 FTDYB：Skill 不是代码里的一段提示词，而是用户可见、可编辑的 Markdown 文档，
存放在 data/skills/。渐进式披露：上下文只注入 Skill 目录（名称+摘要），
全文由模型调 read_skill 按需加载——"流程即数据"。

插件包约定（任务#5）：单文件 <slug>.md 与目录包 <slug>/<slug>.md
（包内其余文件为资源）双形态兼容；平台声明与正文合一，写在文档头部
YAML frontmatter（`---` 包裹块），外置 JSON sidecar 已退役。

文档格式约定：
    ---
    （可选）YAML frontmatter 平台声明
    ---
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
from src.video_agent.config import settings
# 标题式解析静默沿用的降级遥测（顶层化，宪法第六章禁方法内 import）
from src.video_agent.core import live_metrics
# （审核）：pause_rules 解析定义下沉 skill_runtime.registry，本处顶层 re-export 保留兼容导入路径
from src.video_agent.skill_runtime.registry import parse_pause_rules, _PAUSE_RULES_BLOCK_RE  # noqa: 1
# frontmatter 声明解析/体检（frontmatter 顶层不依赖本模块，无环）
from src.video_agent.skill_runtime import frontmatter

_SLUG_RE = re.compile(r"^[\w一-鿿-]{1,64}$")  # 允许中英文/数字/下划线/连字符

# 外来工具名映射层（FOREIGN_TOOL_MAP + build_foreign_tool_note）
# 已删除（清偿，用户裁决）：运行时不再做工具名翻译；进项目的 Skill
# 必须在导入期改为本项目的工具名（归将来专用 Skill 系统职责）。

# 版本历史：保存前把旧版备份到 .history/，每个 slug 保留最近 N 版
_HISTORY_DIR_NAME = ".history"
_HISTORY_MAX = 10

# ---------- Skill 章节分阶段解析（分段聚焦注入用） ----------
# 外来 Skill（如 flova 导出）原生就是「每个工具一节」的结构（<planner>/<write_the_prompt>…），
# 它们的运行时把各节分别注入对应阶段的子工具；本系统把全文一次性注入单一编排模型，
# 只能靠「识别当前阶段 → 重复强调对应章节」来逼近同等遵循度。
# 值支持一对多：旧 tag（如 storyboard_designer）三拆重构后同时映射到全部拆分 stage，
# 保证存量 Skill 的整节内容对三个拆解执行器同等注入（与旧执行器语义一致）。
# 执行器名对齐批：本项目 skill 文档章节 tag 一律用真实执行器/工具名；
# 源平台遗留名（media_generator/storyboard_designer 等）仅作外来 Skill 兼容别名保留。
SECTION_TAG_STAGES: Dict[str, Union[str, Tuple[str, ...]]] = {
    "planner": "planning",
    # 兼容别名（源平台名，外来 Skill 用）→ 本项目执行器 script_analyze
    "resource_prepare_and_analyze": "planning",
    "multimodal_analyze_tool": "planning",
    "script_analyze": "planning",
    "text_editor": "planning",
    # 兼容别名（源平台名）→ 本项目三拆解执行器（一对多）
    "storyboard_designer": ("storyboard_ke", "storyboard_shot", "storyboard_audio"),
    "storyboard_key_elements": "storyboard_ke",
    "storyboard_shots": "storyboard_shot",
    "storyboard_audio": "storyboard_audio",
    "write_media_prompt": "prompt_draft",
    # 兼容别名（源平台名）→ 本项目执行器 write_media_prompt
    "write_the_prompt": "prompt_draft",
    # 兼容别名（源平台名）→ generation 阶段；本项目用真实工具名分节
    "media_generator": "generation",
    "generation": "generation",
    "image_generate": "generation",
    "generate_video": "generation",
    "audio_generate": "generation",
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
    # 静默沿用告警——连续 ≥3 节未命中关键字而沿用上一阶段时，
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


def list_skill_sections(content: str) -> List[Dict[str, Any]]:
    """章节目录：[{title, start, end}]，按出现顺序，字符区间基于全文原文
    （content[start:end] 即该章节文本）。

    与 split_skill_sections 同口径双格式：
    1. flova 原生 <tag>…</tag> 章节：title = tag 名，区间覆盖整个标签块；
    2. Markdown 标题式：title = 标题文本（去 # 前缀），区间从标题行到下一标题前。
    任务#36 B5：分级注入章节目录与 read_skill（section/start）续读共用。
    """
    content = content or ""
    out: List[Dict[str, Any]] = []
    tag_alt = "|".join(re.escape(t) for t in SECTION_TAG_STAGES)
    tag_re = re.compile(rf"<(?P<tag>{tag_alt})>(?P<body>.*?)</(?P=tag)>", re.S | re.I)
    found_tag = False
    for m in tag_re.finditer(content):
        found_tag = True
        out.append({"title": m.group("tag").lower(),
                    "start": m.start(), "end": m.end()})
    if found_tag:
        return out
    # Markdown 标题兜底：逐标题定位起点，end 回填到下一节起点
    for m in re.finditer(r"(?m)^#{1,4}[^\n]*", content):
        heading = m.group(0).lstrip("#").strip()
        if not heading:
            continue
        out.append({"title": heading, "start": m.start(), "end": m.end()})
    # 回填 end：每节到下一节起点（最后一节到全文末尾）
    for i, sec in enumerate(out):
        sec["end"] = out[i + 1]["start"] if i + 1 < len(out) else len(content)
    return out


DEFAULT_SKILL_SLUG = "script-to-video"
DEFAULT_SKILL_DOC = """---
schema_version: 3
version: "1.0"
gates:
  require_duration: true
  require_subtitle: true
  require_camera_language: true
  require_audio_layer: true
  require_at_ref: true
flow:
  spec_wizard: true
  spec_stage_trim: true
  spec_gate: true
pause:
  stage_pause: true
---

# 剧本生视频（需上传剧本）

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
    has_any = any(SKILL_DOCS_DIR.glob("*.md")) or any(
        p.is_dir() and not p.name.startswith(".")
        and (p / f"{p.name}.md").exists() for p in SKILL_DOCS_DIR.iterdir()
    )
    if not has_any:
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
    # 在剥离 frontmatter 后的正文上找标题/描述（P2-3）：YAML 注释行
    # （`# ...`）与声明键混在全文扫描里会污染显示名
    body = frontmatter.strip_frontmatter(content)
    for line in body.splitlines():
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


def skill_doc_path(slug: str) -> Optional[Path]:
    """Skill 主文档路径解析（插件包约定双形态）：单文件优先，
    目录包 <slug>/<slug>.md 次之；均不存在返回 None。"""
    f = SKILL_DOCS_DIR / f"{slug}.md"
    if f.exists():
        return f
    pkg = SKILL_DOCS_DIR / slug / f"{slug}.md"
    if pkg.exists():
        return pkg
    return None


def list_skill_docs() -> List[Dict[str, Any]]:
    ensure_default_skill_docs()
    docs = []
    for f in sorted(SKILL_DOCS_DIR.glob("*.md")):
        try:
            # utf-8-sig：容忍 Windows 记事本回存的 BOM（写入侧保持 utf-8）
            docs.append(_parse_doc(f.stem, f.read_text(encoding="utf-8-sig")))
        except OSError as e:
            logger.warning(f"[SkillDocs] 读取失败 {f.name}: {e}")
    # 目录包形态（插件包约定）：主文档 = 包内同名 md，包内其余文件为资源
    for p in sorted(SKILL_DOCS_DIR.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or p.name.startswith("."):
            continue
        main = p / f"{p.name}.md"
        if not main.exists():
            continue
        try:
            docs.append(_parse_doc(p.name, main.read_text(encoding="utf-8-sig")))
        except OSError as e:
            logger.warning(f"[SkillDocs] 读取失败 {main}: {e}")
    return docs


def get_skill_doc(slug: str) -> Optional[Dict[str, Any]]:
    slug = _validate_slug(slug)
    f = skill_doc_path(slug)
    if f is None:
        return None
    return _parse_doc(slug, f.read_text(encoding="utf-8-sig"))


def save_skill_doc(slug: str, content: str) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    if not content.strip():
        raise ValueError("Skill 文档内容不能为空")
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # 已存在的目录包写回包内主文档；新建落单文件形态
    target = skill_doc_path(slug) or (SKILL_DOCS_DIR / f"{slug}.md")
    # 导入来源标记（插件包约定）：新建文档且含外来平台分析类章节 tag、
    # frontmatter 又未声明 source 时补 source="用户导入"（元数据头随注入
    # 下发信任提示）；本地词汇表文档与已有文档编辑不动，保证保存逐字节忠实
    if not target.exists():
        declaration, _body, _err = frontmatter.split_frontmatter(content)
        # 外来章节判定与 lint 口径一致（f"<{t}>" 章节 tag 存在）：
        # 裸子串匹配会把正文散文里提及的工具名误标为外来
        _has_foreign = any(f"<{t}>" in content for t in _FOREIGN_SECTION_TAGS)
        # 头部未闭合（_err 非空）时不前置新 frontmatter 块：保存原文，
        # 让 lint 警告暴露问题，避免新块掩盖未闭合头
        if not _err and _has_foreign and not (declaration or {}).get("source"):
            data = dict(declaration or {})
            data["source"] = "用户导入"
            content = frontmatter.render_frontmatter(data) + _body
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
        backup.write_text(target.read_text(encoding="utf-8-sig"), encoding="utf-8")
        # 裁剪：仅保留最近 _HISTORY_MAX 版（按文件名时间戳排序）
        versions = sorted(hdir.glob(f"{slug}-*.md"), key=lambda p: p.name)
        for old in versions[:-_HISTORY_MAX]:
            old.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"[SkillDocs] 版本备份失败 {slug}: {e}")


def prune_all_skill_history() -> int:
    """：启动时裁剪全部 Skill 历史——每 slug 只保留最近 _HISTORY_MAX 版。

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
            content = f.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        # 版本名 = 文件名去掉 slug 前缀（即时间戳部分）
        version = f.stem[len(slug) + 1:]
        items.append({"version": version, "content": content})
    return items


def delete_skill_doc(slug: str) -> None:
    """删除指定 Skill 文档（单文件或目录包主文档），不存在时抛出 ValueError"""
    slug = _validate_slug(slug)
    f = skill_doc_path(slug)
    if f is None:
        raise ValueError(f"Skill 文档 '{slug}' 不存在")
    f.unlink()
    logger.info(f"[SkillDocs] 已删除 Skill 文档: {f}")
    try:
        from src.video_agent.skill_runtime.registry import unregister_skill

        unregister_skill(slug)
    except Exception as e:
        logger.warning(f"[SkillDocs] Skill 执行器注销失败 {slug}: {e}")


# Skill 暂停点显式声明解析已下沉 skill_runtime.registry，本文件经顶部 import re-export。
# gate_rules 块格式校验用（与 prompt_gates.parse_gate_rules 的正则保持一致）
_GATE_RULES_LINT_RE = re.compile(
    r"```(?:json|js)?\s*gate_rules\s*\n(.*?)```", re.S | re.I
)

# Skill 平台行为统一声明块正则（声明已迁文档头部 frontmatter，
# 本正则仅用于 lint 提示「文档内 manifest 块不再消费」）
_SKILL_MANIFEST_BLOCK_RE = re.compile(
    r"```(?:json|js)?\s*skill_manifest\s*\n(.*?)```", re.S | re.I
)

# 用户裁决：Skill 内写死的模型能力参数检测（厂商/模型/分辨率/时长），
# 保存/导入时 lint 提示「已作废，以全局设置为准」；运行时一律忽略
_MODEL_PARAM_LINT_RE = re.compile(
    r"(Seedance|GPT\s*Image|Kling|可灵|即梦|Midjourney|Flux|SDXL|"
    r"Runway|Vidu|Sora|Veo|Pika|Hailuo|海螺|万相|通义|1K|2K|4K|"
    r"480p|720p|1080p|4K高清|60fps|24fps)"
)


def lint_skill_content(content: str, slug: str = "") -> Dict[str, Any]:
    """Skill 文档保存时 lint：把注册结果/规则合法性提示前移到编辑时。

    返回 {"available_tools": [...], "warnings": [...]}；不阻断保存，
    由路由层随 PUT 响应下发，前端以 toast/详情展示。
    含 frontmatter 声明体检（解析/schema 编辑期预警，只告警不阻断）。
    """
    from src.video_agent.skill_runtime.registry import (
        CAPABILITY_TOOL_STAGES,
        PIPELINE_CAPABILITY_TOOLS,
    )

    warnings: List[str] = []
    content = content or ""
    # frontmatter 体检：解析/schema 问题编辑期预警（注册期仍 fail-hard 拒注册）
    declaration, body, fm_err = frontmatter.split_frontmatter(content)
    if fm_err:
        warnings.append(f"frontmatter 声明解析失败：{fm_err}（注册期将拒注册）")
    elif declaration:
        for issue in frontmatter.validate_manifest(declaration):
            warnings.append(f"frontmatter 声明问题：{issue}")
    sections = split_skill_sections(body)
    available = [
        t for t in PIPELINE_CAPABILITY_TOOLS
        if any((sections.get(s) or "").strip()
               for s in CAPABILITY_TOOL_STAGES.get(t, ()))
    ]
    if not available:
        warnings.append(
            "未识别到任何管线能力章节：选中该 Skill 时按自由型处理（全文直注，无阶段裁剪）"
        )
    # 三拆部分缺失：故事板章节只覆盖了部分拆解能力
    split_tools = ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")
    present = [t for t in split_tools if t in available]
    if present and len(present) < 3:
        missing = [t for t in split_tools if t not in available]
        warnings.append("故事板章节仅覆盖部分拆解能力，未声明：" + "、".join(missing))
    # gate_rules 块格式校验（非法时 prompt_gates 静默回落默认，这里显式告知）
    gm = _GATE_RULES_LINT_RE.search(content)
    if gm:
        try:
            data = json.loads(gm.group(1))
            if not isinstance(data, dict):
                warnings.append("gate_rules 不是 JSON 对象，已回落默认闸机规则")
        except Exception:
            warnings.append("gate_rules JSON 解析失败，已回落默认闸机规则")
    # 声明迁 frontmatter——文档内 manifest 块不再消费，显式提示
    if _SKILL_MANIFEST_BLOCK_RE.search(content):
        warnings.append(
            "skill_manifest 块不再消费：平台声明已迁文档头部 frontmatter，请从正文移除该块"
        )
    elif gm or _PAUSE_RULES_BLOCK_RE.search(content):
        warnings.append(
            "检测到旧式 gate_rules/pause_rules 块：建议迁移为文档头部 frontmatter 声明"
            "（并存时两块各自表述属于指令分身）"
        )
    # 外来平台章节 tag 信任提示（导入 Skill 的来源标记通道；只告警不阻断）
    _foreign = sorted({t for t in _FOREIGN_SECTION_TAGS if f"<{t}>" in content})
    if _foreign:
        warnings.append(
            "检测到外来平台章节 tag（" + "、".join(_foreign)
            + "）：本平台按兼容别名映射，请核对工具名与导入来源"
        )
    # 导入来源信任提示：声明了 source（外部导入标记）即提示核对
    if (declaration or {}).get("source"):
        warnings.append(
            f"外部导入 Skill（来源：{declaration['source']}）：指令与本项目铁律/"
            "全局设置冲突时以后者为准，请核对工具名与流程声明"
        )
    # 暂停声明检测（仅提示不阻断；frontmatter pause.stage_pause/pause_points
    # 与正文关键词/pause_rules 任一声明即视为已覆盖）
    _fm_pause = bool((declaration or {}).get("pause")) or bool(
        (declaration or {}).get("pause_points"))
    if (
        not _fm_pause
        and parse_pause_rules(content) is None
        and "何时暂停" not in content
        and "强制暂停点" not in content
    ):
        warnings.append(
            "未检测到阶段暂停声明（可加 ```json pause_rules {\"stage_pause\": true}``` 或写明「何时暂停」），"
            "阶段完成后将不会主动邀请用户确认"
        )
    # 用户裁决：模型能力参数唯一权威源 = 全局设置——Skill 内写死的
    # 厂商/模型/分辨率/时长参数一律作废（运行时忽略，仅提示迁移）
    _hard_params = _MODEL_PARAM_LINT_RE.findall(content)
    if _hard_params:
        warnings.append(
            "检测到写死的模型能力参数（" + "、".join(sorted(set(_hard_params))[:6])
            + " 等）：已作废——出图/出视频渠道、分辨率、时长以「全局设置」为唯一权威源，"
            "运行时不会采用本文档中的这些参数"
        )
    # 对标 Flova 固定组成：体量预算预警（legacy 全文注入截断阈值前 20%）
    _budget_warn = int(settings.max_doc_chars * 0.8)
    if len(content) > _budget_warn:
        warnings.append(
            f"文档体量 {len(content)} 字符超过建议预算 {_budget_warn}（全文注入截断阈值 "
            f"{settings.max_doc_chars} 的 80%）：超长将按阶段截断，建议精简或拆分章节"
        )
    # 章节完整性对照 Flova 组成（流程型 Skill 缺核心段才告警，自由型不误伤）
    warnings.extend(_lint_flova_composition(content, sections, bool(available)))
    # 散文含对话义务而 frontmatter 未声明 pause → 显性化分歧（只告警不阻断）
    warnings.extend(_lint_prose_obligations(content, slug))
    return {"available_tools": available, "warnings": warnings}


# Flova 组成核心段（自由型 Skill 无流程章节时不检查）：阶段键 + 正文关键词兜底
_FLOVA_CORE_PARTS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("故事板设计", ("storyboard_ke", "storyboard_shot", "storyboard_audio"),
     ("故事板", "分镜", "关键元素")),
    ("媒体生成", ("generation",), ("生成", "参考图", "设定图")),
    ("提示词写法", ("prompt_draft",), ("提示词写法", "提示词规范", "Prompt")),
)


def _lint_flova_composition(
    content: str, sections: Dict[str, str], has_executors: bool,
) -> List[str]:
    """流程型 Skill 的核心组成缺失提示（对标 Flova：只写会改变流程的规则，
    但流程/故事板/生成/提示词四段是工作流骨架）；非流程型不告警。"""
    if not has_executors and "planning" not in sections:
        return []
    missing: List[str] = []
    for part, stage_keys, keywords in _FLOVA_CORE_PARTS:
        if any((sections.get(k) or "").strip() for k in stage_keys):
            continue
        if any(kw in content for kw in keywords):
            continue
        missing.append(part)
    if not missing:
        return []
    return ["对照视频 Skill 标准组成，未识别到：" + "、".join(missing)
            + "（若本 Skill 确不涉及可忽略；涉及建议补对应章节，避免运行时靠启发式归段）"]


# 外来平台章节 tag（lint 信任提示用）：仅取不在「视频 Skill 标准组成」
# 词汇表内的分析类源平台遗留名；storyboard_designer/write_the_prompt/
# media_generator 是组成词汇表兼容名，本地文档合法使用不告警（防误报）
_FOREIGN_SECTION_TAGS = (
    "resource_prepare_and_analyze", "multimodal_analyze_tool",
)

# 散文对话义务标记（<planner> 含确认/询问/暂停类义务词）
_PROSE_OBLIGATION_RE = re.compile(r"确认|询问|暂停|问用户|请用户")


def _lint_prose_obligations(content: str, slug: str) -> List[str]:
    """散文含对话义务而 frontmatter 未声明 pause → 告警显性化分歧。

    平台以机械卡/闸兜底对话义务；Skill 散文与 frontmatter 声明
    分歧时不再静默丢弃（P1 单一家原则的编辑期提示），只告警不阻断。
    """
    if not slug:
        return []
    sections = split_skill_sections(content or "")
    planner = (sections.get("planning") or sections.get("planner") or "")
    if not _PROSE_OBLIGATION_RE.search(planner):
        return []
    try:
        data = frontmatter.load_manifest(slug)
    except Exception:
        return []
    if (data or {}).get("pause") or (data or {}).get("pause_points"):
        return []
    return ["<planner> 散文含对话义务（确认/询问/暂停）而 frontmatter 未声明 pause："
            "平台将以机械卡/闸形态兜底；建议补 pause.stage_pause 声明或接受平台卡形态"]


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
    返回 (display_name, content)，未命中返回 ("", "")；content 已剥离
    frontmatter（声明经元数据头单独注入，正文注入不携带 YAML 头）。
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
            return str(c.get("name", "")), frontmatter.strip_frontmatter(
                str(c.get("content", "")))
    for c in candidates:
        if any(_norm_skill_name(n) == wn for n in names(c) if n):
            return str(c.get("name", "")), frontmatter.strip_frontmatter(
                str(c.get("content", "")))
    if len(wn) >= 2:
        for c in candidates:
            for n in names(c):
                nn = _norm_skill_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    return str(c.get("name", "")), frontmatter.strip_frontmatter(
                        str(c.get("content", "")))
    return "", ""
