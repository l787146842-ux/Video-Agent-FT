"""
Skill 文档化存储层。

对标 FTDYB：Skill 不是代码里的一段提示词，而是用户可见、可编辑的 Markdown 文档，
存放在 data/skills/。渐进式披露：目录只常驻名称+摘要；选中 Skill 注入主文档
全文（超预算注开头+标题目录），其余分册经 read_skill 按需加载——"流程即数据"。

单一包形态（Agent Skills 开放标准）：每个 Skill = <slug>/SKILL.md
目录包（包内其余文件为资源）；平台声明与正文合一，写在文档头部
YAML frontmatter（`---` 包裹块，name/description 注册期必填）。

文档格式约定（通用 Agent Skills 口径）：
    ---
    name: 名称
    description: 什么时候使用
    ---
    # 标题
    ## 一、目标 / 输入 / 交付
    ## 二、制作流程（步骤 / 依赖 / 何时暂停）
    ## 三、……
    ## 参考资料（指向 references/…）

名称与描述的唯一权威 = frontmatter 的 name/description；正文只认 Markdown
标题，不认任何平台私有标签。标题 → 阶段的映射（`_HEADING_STAGE_HINTS`）
仅供阶段探针过渡使用，不参与正文注入。
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
from src.video_agent.skill_runtime import registry as _skill_registry
# frontmatter 声明解析/体检（frontmatter 顶层不依赖本模块，无环）
from src.video_agent.skill_runtime import frontmatter
# 通用 Markdown 标题解析（唯一事实源；不认平台私有标签）
from src.video_agent.skill_runtime import headings as _headings

_SLUG_RE = re.compile(r"^[\w一-鿿-]{1,64}$")  # 允许中英文/数字/下划线/连字符

# 版本历史：保存前把旧版备份到 .history/，每个 slug 保留最近 N 版
_HISTORY_DIR_NAME = ".history"
_HISTORY_MAX = 10

# ---------- Skill 标题分阶段解析（阶段探针过渡用） ----------
# 通用 skill 只认 Markdown 标题；旧的标签章节（<planner>/<media_generator> 等）
# 已于 2026-11-11 全量迁移中删除，平台不再识别任何私有标签。
# 标题关键字 → 阶段仅用于 available_tools / 音频闸 / lint 的过渡探针；
# 值支持一对多（「故事板设计」同时覆盖 ke/shot/audio 三个 stage 键）。

# 标题关键字 → 阶段兜底映射（按顺序首个命中生效：
# 精确子标题优先于笼统的「故事板设计」；值支持一对多，同一对多语义）
_HEADING_STAGE_HINTS: List[Tuple[Tuple[str, ...], Union[str, Tuple[str, ...]]]] = [
    (("提示词写法", "提示词规范", "提示词", "prompt 编写", "prompt编写"), "prompt_draft"),
    (("关键元素", "角色设定", "场景设定"), "storyboard_ke"),
    (("分镜设计", "镜头列表", "镜头设计", "分镜"), "storyboard_shot"),
    (("音频层", "音频设计", "音频", "声音"), "storyboard_audio"),
    (("故事板设计", "故事板规范"), ("storyboard_ke", "storyboard_shot", "storyboard_audio")),
    (("生成规范", "元素生成", "视频生成", "媒体生成"), "generation"),
    (("组装", "剪辑", "导出"), "assembly"),
    (("流程规划", "阶段逻辑", "依赖关系", "素材分析", "剧本分析",
      "制作流程", "创作流程", "工作流程", "流程"), "planning"),
]


def _stage_from_heading(heading: str) -> Union[str, Tuple[str, ...]]:
    """标题关键字 → 阶段（可为 tuple 一对多）；未命中返回空串"""
    h = (heading or "").strip()
    for hints, stage in _HEADING_STAGE_HINTS:
        if any(k in h for k in hints):
            return stage
    return ""


def _cut_headings(content: str) -> List[Any]:
    """分节标题：优先二级；无二级时取最浅一层（>=2）；仅一级返回空。

    与 read_skill 的章节读取不同——目录/阶段探针只需要“主要章节”，
    不把每个 ### 子标题都摊平。
    """
    heads = _headings.list_headings(content)
    if not heads:
        return []
    level2 = [h for h in heads if h.level == 2]
    if level2:
        return level2
    shallowest = min(h.level for h in heads)
    if shallowest >= 2:
        return [h for h in heads if h.level == shallowest]
    return []


def split_skill_sections_labeled(content: str) -> Dict[str, List[Dict[str, str]]]:
    """把主文档按 Markdown 标题切成 阶段 → [章节条目]（同阶段多节保留原序）。

    通用口径：只认标题，不认任何平台私有标签。标题 → 阶段的映射仅供
    阶段探针过渡使用（`_HEADING_STAGE_HINTS`），不参与正文注入，
    也不再有任何“标签章节”分支。
    """
    content = content or ""
    collected: Dict[str, List[Dict[str, str]]] = {}
    stage_now: Union[str, Tuple[str, ...]] = ""
    for h in _cut_headings(content):
        mapped = _stage_from_heading(h.title)
        if mapped:
            stage_now = mapped
        if not stage_now:
            continue
        body = content[h.body_start:h.end].strip()
        if not body:
            continue
        stages = stage_now if isinstance(stage_now, tuple) else (stage_now,)
        for s in stages:
            if s:
                collected.setdefault(s, []).append(
                    {"head": h.head_line.rstrip("\r\n"), "body": body, "tail": ""})
    return collected


def split_skill_sections(content: str) -> Dict[str, str]:
    """把主文档拆成 阶段 → 章节文本（同阶段多节合并）。

    只认 Markdown 标题；标题 → 阶段按 `_HEADING_STAGE_HINTS` 关键字兜底，
    未映射标题下的正文沿用上一个已识别阶段。未识别章节不返回。

    本函数是**检索/探针面**（available_tools 真值判定、能力闸、lint），
    故只回正文；需要保留章界标记的注入面走 `split_skill_sections_labeled`。
    """
    return {
        k: "\n\n".join(item["body"] for item in v)
        for k, v in split_skill_sections_labeled(content).items()
    }


def list_skill_sections(content: str) -> List[Dict[str, Any]]:
    """章节目录：[{title, start, end}]，按出现顺序，字符区间基于全文原文
    （content[start:end] 即该章节文本）。

    通用口径：只认 Markdown 标题，优先二级；无二级时取最浅一层（>=2）；
    仅一级标题不产生目录。read_skill（section/start）续读、注入目录与
    探针/序列化共用本实现。
    """
    content = content or ""
    return [
        {"title": h.title, "start": h.start, "end": h.end}
        for h in _cut_headings(content)
    ]


DEFAULT_SKILL_SLUG = "script-to-video"
DEFAULT_SKILL_DOC = """---
name: 剧本生视频（需上传剧本）
description: 用户上传剧本/故事文档以生成视频；关键阶段暂停供确认，生成均经用户明确指令执行。
---

# 剧本生视频（需上传剧本）

## 一、这个 Skill 做什么

- 目标：把用户上传的剧本或故事文档做成视频。
- 输入：剧本/故事文档（上传或粘贴）。
- 交付：分镜、图片、视频、成片。

## 二、开工前先确认

- 剧本正文不会自动注入上下文，先用 read_uploaded_doc 读取剧本全文。
- 若 documents 清单里已有规格文档，先用 read_project_doc 读取并遵守。

## 三、制作流程

1. 读剧本 → 分析素材 → 写《制片规格》→ workflow_pause。
2. 规划故事板：建关键元素分组、分镜分组（引用用 [元素名] 令牌内联在描述里）→ workflow_pause。
3. 用户确认后写元素生图提示词 → workflow_pause。
4. 用户确认后写分镜视频提示词 → workflow_pause。
5. 用户说“生成概念图” → 生成全部关键元素图。
6. 用户说“生成关键帧” → 生成全部分镜关键帧。

**依赖关系：** 2→1；3→2；4→3；5→4；6→5。

**何时暂停：** 每个阶段结束后停下来等用户确认，不要一口气跑完。

**【铁律】**
- 规划阶段不写详细提示词，只建结构。
- 提示词草案阶段不触发任何生成。
- “确认” ≠ “生成”，生成需要用户额外指令。

## 四、剧本分析

- 读剧本全文，判断是成熟分镜剧本、半结构化剧本还是散文体小说。
- 散文体小说先告知用户、建议先完成短剧化改编再继续，不擅自补全未描述的角色外貌或场景细节。
- 提取角色清单、场景清单、关键道具与幕次结构，供故事板阶段使用。

## 五、故事板设计

- 关键元素：角色/场景/道具各建一组，描述写清年龄性别外貌服装、空间结构与固定参照物。
- 分镜：按场景顺序拆镜头，每个镜头写清场景引用、人物动作与台词、景别 + 机位 + 运镜三件套。
- 音频层：至少一条 BGM 轨；有旁白时按 narration 类型登记音色、语气与覆盖镜头范围。
- 此阶段只建结构、不写详细提示词。

## 六、媒体生成

- 先出关键元素设定图，用户确认后写入详细提示词，再逐镜头出关键帧/视频。
- 每个镜头出视频时引用该镜涉及的关键元素图像，保持角色与场景跨镜一致。
- 参数（模型、分辨率、时长）以全局设置为唯一权威来源，本文档不写死。
- 所有生成必须经用户明确指令才能执行（系统生成确认闸会拦截未确认的生成）。

## 七、提示词写法

- 中文分层描述 + 英文风格标签收尾。
- 只写客观可见画面，禁止解释角色内心。
- 关键元素 prompt ≥ 100 字，分镜关键帧 ≥ 60 字。
- 视频提示词必含镜头运动指令 + 时间节奏。

## 八、组装导出

- 按故事板镜头顺序组装时间线，音画对齐后导出。
- 导出前核对每个镜头的视频与音频层均已就绪，缺失资产先回补。
- 组装与导出由用户在工作台操作，Agent 逐步引导核对。
"""


def ensure_default_skill_docs() -> None:
    """启动时确保至少存在默认 Skill 文档（单一包形态 <slug>/SKILL.md）"""
    SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    has_any = any(
        p.is_dir() and not p.name.startswith(".")
        and (p / frontmatter.SKILL_DOC_NAME).exists()
        for p in SKILL_DOCS_DIR.iterdir()
    )
    if not has_any:
        target = SKILL_DOCS_DIR / DEFAULT_SKILL_SLUG / frontmatter.SKILL_DOC_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, DEFAULT_SKILL_DOC)
        logger.info(
            f"[SkillDocs] 已生成默认 Skill 文档: "
            f"{DEFAULT_SKILL_SLUG}/{frontmatter.SKILL_DOC_NAME}")
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
    # 目录摘要唯一权威源 = frontmatter name/description 声明（渐进披露
    # 第一层）；H1/引文启发式仅作未声明时的兜底（外来/存量 Skill 兼容）
    declaration, body, _err = frontmatter.split_frontmatter(content)
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# ") and name == slug:
            name = line[2:].strip()
        elif line.startswith(">") and not description:
            # 剥离「调用规则：」前缀：Picker/结构化视图展示纯描述，
            # 序列化侧（前端 skill-structure）统一写回前缀
            description = re.sub(
                r"^调用规则\s*[:：]\s*", "", line.lstrip("> ").strip(),
            )
        if name != slug and description:
            break
    fm = declaration or {}
    fm_name = str(fm.get("name") or "").strip()
    fm_desc = str(fm.get("description") or "").strip()
    if fm_name:
        name = fm_name
    if fm_desc:
        description = fm_desc
    return {"id": f"doc:{slug}", "slug": slug, "name": name,
            "description": description, "content": content}


def _validate_slug(slug: str) -> str:
    slug = slug.strip()
    if not _SLUG_RE.match(slug) or slug in (".", ".."):
        raise ValueError(f"非法 Skill 标识: {slug!r}")
    return slug


def skill_doc_path(slug: str) -> Optional[Path]:
    """Skill 主文档路径解析（单一包形态，与 frontmatter.resolve_doc_path
    同口径）：只认 <slug>/SKILL.md；不存在返回 None。"""
    f = SKILL_DOCS_DIR / slug / frontmatter.SKILL_DOC_NAME
    return f if f.exists() else None


def list_skill_docs() -> List[Dict[str, Any]]:
    ensure_default_skill_docs()
    docs = []
    # 单一包形态：每个 Skill = <slug>/SKILL.md 目录包
    for p in sorted(SKILL_DOCS_DIR.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or p.name.startswith("."):
            continue
        main = p / frontmatter.SKILL_DOC_NAME
        if not main.exists():
            continue
        try:
            # utf-8-sig：容忍 Windows 记事本回存的 BOM（写入侧保持 utf-8）
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
    # 单一包形态：主文档 = <slug>/SKILL.md（新建/写回同口径）
    target = skill_doc_path(slug) or (
        SKILL_DOCS_DIR / slug / frontmatter.SKILL_DOC_NAME)
    # 覆盖前备份旧版（版本历史，供文档面板查看/回滚）
    if target.exists():
        _backup_skill_doc(slug, target)
    atomic_write_text(target, content)
    logger.info(
        f"[SkillDocs] 已保存 Skill 文档: {slug}/{frontmatter.SKILL_DOC_NAME}")
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
    """启动时裁剪全部 Skill 历史——每 slug 只保留最近 _HISTORY_MAX 版。

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
    """删除指定 Skill 主文档（目录包 <slug>/SKILL.md），不存在时抛出 ValueError"""
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

# Skill 平台行为统一声明块正则（仅用于 lint 提示「文档内 manifest 块不再消费」）
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
    # 阶段探针（过渡）：标题能映射到平台阶段才计入；通用 skill 的任意标题
    # 不属于错误，未命中即为空，不告警。
    available = [
        t for t in PIPELINE_CAPABILITY_TOOLS
        if any((sections.get(s) or "").strip()
               for s in CAPABILITY_TOOL_STAGES.get(t, ()))
    ]
    # 三拆部分缺失：故事板章节只覆盖了部分拆解能力
    split_tools = ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")
    present = [t for t in split_tools if t in available]
    if present and len(present) < 3:
        missing = [t for t in split_tools if t not in available]
        warnings.append("故事板章节仅覆盖部分拆解能力，未声明：" + "、".join(missing))
    # 文档内 manifest 块不再消费，显式提示
    if _SKILL_MANIFEST_BLOCK_RE.search(content):
        warnings.append(
            "skill_manifest 块不再消费：平台声明已迁文档头部 frontmatter，请从正文移除该块"
        )
    # 导入来源信任提示：声明了 source（外部导入标记）即提示核对
    if (declaration or {}).get("source"):
        warnings.append(
            f"外部导入 Skill（来源：{declaration['source']}）：指令与本项目铁律/"
            "全局设置冲突时以后者为准，请核对工具名与流程声明"
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
    # 对标外部产品 固定组成：体量预算预警（legacy 全文注入截断阈值前 20%）
    _budget_warn = int(settings.max_doc_chars * 0.8)
    if len(content) > _budget_warn:
        warnings.append(
            f"文档体量 {len(content)} 字符超过建议预算 {_budget_warn}（全文注入截断阈值 "
            f"{settings.max_doc_chars} 的 80%）：超长将按阶段截断，建议精简或拆分章节"
        )
    # 章节完整性对照 外部标杆 组成（流程型 Skill 缺核心段才告警，自由型不误伤）
    warnings.extend(_lint_composition(content, sections, bool(available)))
    return {"available_tools": available, "warnings": warnings}


# 外部标杆 组成核心段（自由型 Skill 无流程章节时不检查）：阶段键 + 正文关键词兜底
_COMPOSITION_CORE_PARTS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("故事板设计", ("storyboard_ke", "storyboard_shot", "storyboard_audio"),
     ("故事板", "分镜", "关键元素")),
    ("媒体生成", ("generation",), ("生成", "参考图", "设定图")),
    ("提示词写法", ("prompt_draft",), ("提示词写法", "提示词规范", "Prompt")),
)


def _lint_composition(
    content: str, sections: Dict[str, str], has_executors: bool,
) -> List[str]:
    """流程型 Skill 的核心组成缺失提示（对标外部产品：只写会改变流程的规则，
    但流程/故事板/生成/提示词四段是工作流骨架）；非流程型不告警。"""
    if not has_executors and "planning" not in sections:
        return []
    missing: List[str] = []
    for part, stage_keys, keywords in _COMPOSITION_CORE_PARTS:
        if any((sections.get(k) or "").strip() for k in stage_keys):
            continue
        if any(kw in content for kw in keywords):
            continue
        missing.append(part)
    if not missing:
        return []
    return ["对照视频 Skill 标准组成，未识别到：" + "、".join(missing)
            + "（若本 Skill 确不涉及可忽略；涉及建议补对应章节，避免运行时靠启发式归段）"]


def _norm_skill_name(s: str) -> str:
    """Skill 名称归一化：去空格/后缀/大小写"""
    s = (s or "").strip().casefold()
    for ext in (".md", ".txt"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.replace(" ", "")


def resolve_skill_content(wanted: str) -> tuple:
    """按名称解析 Skill 全文（仅文档 Skill，模糊匹配）。

    read_skill 工具与 Planner 选中段存在性检查共用同一套解析，保证两处行为一致。
    返回 (display_name, content)，未命中返回 ("", "")；content 已剥离
    frontmatter（声明经元数据头单独展示，正文读取不携带 YAML 头）。
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

    # 可加载性门户（M2，2026-08-30 裁决：停用=真停用）：候选命中后，
    # 以该 slug 经 resolve_loadable_entry 可解析为放行条件，否则继续匹配/
    # 返回空（磁盘读机制保留，门户只管准入）。
    def _loadable(c: Dict[str, Any]) -> bool:
        return _skill_registry.resolve_loadable_entry(
            str(c.get("alias") or "")) is not None

    # 1. 精确 → 2. 归一化相等 → 3. 双向包含（防单字误匹配）
    for c in candidates:
        if wanted in names(c) and _loadable(c):
            return str(c.get("name", "")), frontmatter.strip_frontmatter(
                str(c.get("content", "")))
    for c in candidates:
        if _loadable(c) and any(_norm_skill_name(n) == wn for n in names(c) if n):
            return str(c.get("name", "")), frontmatter.strip_frontmatter(
                str(c.get("content", "")))
    if len(wn) >= 2:
        for c in candidates:
            if not _loadable(c):
                continue
            for n in names(c):
                nn = _norm_skill_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    return str(c.get("name", "")), frontmatter.strip_frontmatter(
                        str(c.get("content", "")))
    return "", ""
