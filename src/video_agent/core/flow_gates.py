"""Skill 声明式流程门禁（硬校验）。

背景：提示词层的「请遵守流程」对模型无约束力——模型可以把多个阶段合并到
一轮做完、用正文「请确认」冒充暂停信号。本模块把流程控制权从模型手里收回到
代码手里：

- Skill 文档用固定格式声明检查点（== 流程检查点 == 段落），例如：
    - 写入分镜提示词 需要: 关键元素提示词已写入, 关键元素已确认
    - 触发生成 需要: 关键元素已确认
- 系统在执行每个 action / FC 工具前评估前置条件（实时读取工作台状态），
  不满足 → 拦截该操作并把原因回给模型；本轮出现拦截 → 强制补发确认暂停，
  无论模型是否自觉停下。
- 未声明检查点的 Skill 完全不受影响（from_skill 返回 None）。

条件词表是封闭的（代码可判定），Skill 作者只能用列表里的条件，
保证「声明即执行」。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

# ---------- 条件词表（封闭集） ----------
# key → (中文标签, 判定函数名)。判定函数统一签名 cond_xxx(state) -> bool。
COND_LABELS = {
    "spec_doc_exists": "规格文档已写入",
    "script_present": "剧本原料已提供（上传文档或分析摘要）",
    "keyelement_prompts_written": "关键元素提示词已写入",
    "keyelements_confirmed": "关键元素已确认",
    "keyelements_generated": "关键元素已生成图像",
    "shot_prompts_written": "分镜提示词已写入",
    "shots_confirmed": "分镜已确认",
    "shots_generated": "分镜已生成视频",
    "audio_prompts_written": "音频提示词已写入",
}

# 中文/别名 → 条件 key（Skill 作者可写中文）
COND_ALIASES: Dict[str, str] = {}
for _k, _label in COND_LABELS.items():
    COND_ALIASES[_k] = _k
    COND_ALIASES[_label] = _k
COND_ALIASES.update({
    "关键元素的提示词已写入": "keyelement_prompts_written",
    "关键元素提示词写入": "keyelement_prompts_written",
    "关键元素确认": "keyelements_confirmed",
    "分镜的提示词已写入": "shot_prompts_written",
    "分镜提示词写入": "shot_prompts_written",
    "分镜确认": "shots_confirmed",
    "规格文档存在": "spec_doc_exists",
    "规格已写入": "spec_doc_exists",
})

# ---------- 操作分类（封闭集） ----------
OP_WRITE_KEYELEMENT_PROMPT = "write_keyelement_prompt"
OP_WRITE_SHOT_PROMPT = "write_shot_prompt"
OP_WRITE_AUDIO_PROMPT = "write_audio_prompt"
OP_GENERATE = "generate"
# 814G5：结构拆解（建分组/草稿骨架，执行器整包拆解同属此类）
OP_BUILD_STRUCTURE = "build_structure"

OP_LABELS = {
    OP_WRITE_KEYELEMENT_PROMPT: "写入关键元素提示词",
    OP_WRITE_SHOT_PROMPT: "写入分镜提示词",
    OP_WRITE_AUDIO_PROMPT: "写入音频提示词",
    OP_GENERATE: "触发生成",
    OP_BUILD_STRUCTURE: "拆解结构（建分组/草稿）",
}

_SECTION_MARKERS = ("== 流程检查点", "【流程检查点", "## 流程检查点")
_REQUIRE_SEPS = ("需要:", "需要：", "requires:", "前置:")


def _all_drafts(state: Dict[str, Any], cat: str) -> List[Dict[str, Any]]:
    drafts: List[Dict[str, Any]] = []
    for g in state.get(cat, []) or []:
        drafts.extend(g.get("drafts", []) or [])
    return drafts


def _cond_spec_doc_exists(state):
    # 814G5：只认规格命名文档（项目默认文档/铁律不得冒充规格）
    try:
        from src.video_agent.core import prompt_gates
        return bool(prompt_gates.has_spec_document(state))
    except Exception:
        return bool(state.get("documents"))


def _cond_prompts_written(state, cat):
    drafts = _all_drafts(state, cat)
    return bool(drafts) and all((d.get("prompt") or "").strip() for d in drafts)


def _cond_all_confirmed(state, cat):
    drafts = _all_drafts(state, cat)
    return bool(drafts) and all(d.get("confirmed") for d in drafts)


def _cond_all_media(state, cat, *fields):
    drafts = _all_drafts(state, cat)
    return bool(drafts) and all(any((d.get(f) or "").strip() for f in fields) for d in drafts)


def evaluate_condition(cond_key: str, state: Dict[str, Any]) -> bool:
    """按条件 key 实时判定工作台状态"""
    if cond_key == "spec_doc_exists":
        return _cond_spec_doc_exists(state)
    if cond_key == "script_present":
        # 814H9：剧本原料客观判定（uploadedDocs 或 analysis 摘要）
        try:
            from src.video_agent.core.prompt_gates import script_present
            return script_present(state)
        except Exception:
            return bool((state or {}).get("uploadedDocs"))
    if cond_key == "keyelement_prompts_written":
        return _cond_prompts_written(state, CAT_KEY_ELEMENTS)
    if cond_key == "keyelements_confirmed":
        return _cond_all_confirmed(state, CAT_KEY_ELEMENTS)
    if cond_key == "keyelements_generated":
        return _cond_all_media(state, CAT_KEY_ELEMENTS, "imgUrl")
    if cond_key == "shot_prompts_written":
        return _cond_prompts_written(state, CAT_SHOTS)
    if cond_key == "shots_confirmed":
        return _cond_all_confirmed(state, CAT_SHOTS)
    if cond_key == "shots_generated":
        return _cond_all_media(state, CAT_SHOTS, "videoUrl", "imgUrl")
    if cond_key == "audio_prompts_written":
        return _cond_prompts_written(state, CAT_AUDIO_ITEMS)
    logger.warning(f"[FlowGates] 未知条件: {cond_key}")
    return True  # 未知条件不拦截，避免误伤


@dataclass
class Gate:
    """一条检查点声明：这些操作需要全部前置条件满足才可执行"""
    ops: Set[str] = field(default_factory=set)
    requires: List[str] = field(default_factory=list)
    raw: str = ""


def _classify_op_from_text(desc: str) -> Set[str]:
    """从声明行左侧的中文描述识别操作类型"""
    ops: Set[str] = set()
    d = desc.lower()
    has_prompt = ("提示词" in desc) or ("prompt" in d) or ("草案" in desc)
    if has_prompt or "写" in desc:
        if ("关键元素" in desc) or ("keyelement" in d):
            ops.add(OP_WRITE_KEYELEMENT_PROMPT)
        if ("分镜" in desc) or ("镜头" in desc) or ("shot" in d):
            ops.add(OP_WRITE_SHOT_PROMPT)
        if ("音频" in desc) or ("audio" in d):
            ops.add(OP_WRITE_AUDIO_PROMPT)
    if ("生成" in desc) or ("generate" in d):
        ops.add(OP_GENERATE)
    # 814G5：拆解/建立结构类描述（不含提示词写入语义）
    if not ops and any(k in desc for k in ("拆解", "拆分", "建立", "创建", "登记")):
        ops.add(OP_BUILD_STRUCTURE)
    return ops


def parse_flow_gates(skill_content: str) -> List[Gate]:
    """解析 Skill 文档中的 == 流程检查点 == 段落。

    行格式：- <操作描述> 需要: <条件1>, <条件2>
    无法识别的条件跳过并告警；整段缺失返回空列表。
    """
    lines = (skill_content or "").splitlines()
    start = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if any(s.startswith(m) for m in _SECTION_MARKERS):
            start = i
            break
    if start < 0:
        return []

    gates: List[Gate] = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if not s:
            continue
        # 段落结束：遇到下一个标题/分隔
        if s.startswith(("==", "【", "##", "# ")):
            break
        if not s.startswith(("- ", "* ", "· ")):
            continue
        body = s.lstrip("-*· ").strip()
        sep_pos, sep_len = -1, 0
        for sep in _REQUIRE_SEPS:
            p = body.find(sep)
            if p >= 0:
                sep_pos, sep_len = p, len(sep)
                break
        if sep_pos < 0:
            continue
        ops = _classify_op_from_text(body[:sep_pos])
        if not ops:
            logger.warning(f"[FlowGates] 无法识别操作描述: {body[:sep_pos]!r}")
            continue
        requires: List[str] = []
        for tok in body[sep_pos + sep_len:].replace("，", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            key = COND_ALIASES.get(tok) or COND_ALIASES.get(tok.lower())
            if key:
                requires.append(key)
            else:
                logger.warning(f"[FlowGates] 未知条件词: {tok!r}（已忽略）")
        if requires:
            gates.append(Gate(ops=ops, requires=requires, raw=body))
    return gates


class FlowGateSet:
    """一次对话生效的门禁集（由选中 Skill 解析而来）。

    blocked_count 按轮统计：任何路径（FC/文本）拦截后 mark_blocked()，
    agent_loop 本轮结束前 consume_blocked() 决定是否强制暂停。
    """

    def __init__(self, gates: List[Gate]):
        self.gates = gates
        self._blocked_this_step = 0
        self._last_reasons: List[str] = []

    @classmethod
    def from_skill(cls, skill_content: str) -> Optional["FlowGateSet"]:
        gates = parse_flow_gates(skill_content)
        return cls(gates) if gates else None

    @classmethod
    def ensure_script_gate(cls, existing: Optional["FlowGateSet"]) -> "FlowGateSet":
        """814H9 剧本原料闸：需剧本 Skill 原料缺失时，拆解结构必须等原料。

        执行侧强制（拦 agent 越阶工具调用，不拦用户输入；
        用户豁免/坚持时 planner 不构建本门禁）。"""
        gates = list(existing.gates) if existing else []
        if not any(OP_BUILD_STRUCTURE in g.ops and "script_present" in g.requires for g in gates):
            gates.append(Gate(
                ops={OP_BUILD_STRUCTURE},
                requires=["script_present"],
                raw="系统：剧本原料未提供前不得拆解结构",
            ))
        return cls(gates)

    @classmethod
    def ensure_spec_gate(cls, existing: Optional["FlowGateSet"]) -> "FlowGateSet":
        """814G5：规格向导启用时追加「拆解结构 需要 规格文档已写入」门禁。

        执行侧强制（拦 agent 越阶工具调用，不拦用户输入；
        用户「本次放行」/坚持时 planner 不构建门禁，照做并附警告）。"""
        gates = list(existing.gates) if existing else []
        if not any(OP_BUILD_STRUCTURE in g.ops and "spec_doc_exists" in g.requires for g in gates):
            gates.append(Gate(
                ops={OP_BUILD_STRUCTURE},
                requires=["spec_doc_exists"],
                raw="系统：规格文档未写入前不得拆解结构",
            ))
        return cls(gates)

    # ---------- 操作分类 ----------

    @staticmethod
    def classify_action(action: Dict[str, Any]) -> Optional[str]:
        """studio-actions 文本路径的操作分类"""
        name = str(action.get("action", "")).lower()
        if name in ("generate_image", "generate_video"):
            return OP_GENERATE
        # 814G5：执行器整包拆解同属结构操作
        if name in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio"):
            return OP_BUILD_STRUCTURE
        if name in ("update_draft", "add_draft"):
            prompt = ""
            patch = action.get("patch") or {}
            draft = action.get("draft") or {}
            prompt = str(patch.get("prompt") or draft.get("prompt") or "")
            if not prompt.strip():
                return None
            dtype = str(action.get("draft_type") or action.get("group_type") or "").lower()
            if dtype.startswith("key"):
                return OP_WRITE_KEYELEMENT_PROMPT
            if dtype.startswith("shot"):
                return OP_WRITE_SHOT_PROMPT
            if dtype.startswith("audio"):
                return OP_WRITE_AUDIO_PROMPT
            return None
        if name == "add_group":
            drafts = action.get("drafts") or ([action["draft"]] if action.get("draft") else [])
            has_prompt = any((d.get("prompt") or "").strip() for d in drafts)
            if not has_prompt:
                return OP_BUILD_STRUCTURE  # 814G5：纯建骨架也是结构操作
            gtype = str(action.get("group_type") or "").lower()
            if gtype.startswith("key"):
                return OP_WRITE_KEYELEMENT_PROMPT
            if gtype.startswith("shot"):
                return OP_WRITE_SHOT_PROMPT
            if gtype.startswith("audio"):
                return OP_WRITE_AUDIO_PROMPT
            return None
        return None

    @staticmethod
    def classify_fc(name: str, args: Dict[str, Any]) -> Optional[str]:
        """FC 工具调用的操作分类"""
        if name in ("generate_image", "image_generate", "generate_video"):
            return OP_GENERATE
        # 814G5：执行器整包拆解同属结构操作（规格未定稿时执行侧拦截）
        if name in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio"):
            return OP_BUILD_STRUCTURE
        if name in ("storyboard_patch_draft",):
            prompt = str((args.get("patch") or {}).get("prompt") or "")
            if not prompt.strip():
                return None
            dtype = str(args.get("draft_type") or "").lower()
            if dtype.startswith("key"):
                return OP_WRITE_KEYELEMENT_PROMPT
            if dtype.startswith("shot"):
                return OP_WRITE_SHOT_PROMPT
            if dtype.startswith("audio"):
                return OP_WRITE_AUDIO_PROMPT
            return None  # 类型未知不拦截（防误伤）
        if name in ("storyboard_add_draft", "storyboard_create_group"):
            draft = args.get("draft") or {}
            drafts = args.get("drafts") or ([draft] if draft else [])
            if not any((d.get("prompt") or "").strip() for d in drafts):
                return OP_BUILD_STRUCTURE  # 814G5：纯建骨架也是结构操作
            gtype = str(args.get("group_type") or args.get("draft_type") or "").lower()
            if gtype.startswith("key"):
                return OP_WRITE_KEYELEMENT_PROMPT
            if gtype.startswith("shot"):
                return OP_WRITE_SHOT_PROMPT
            if gtype.startswith("audio"):
                return OP_WRITE_AUDIO_PROMPT
            return None
        return None

    # ---------- 门禁判定 ----------

    def check_op(self, op: Optional[str], state: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """返回 (是否放行, 未满足条件的中文标签列表)"""
        if not op:
            return True, []
        missing: List[str] = []
        for g in self.gates:
            if op not in g.ops:
                continue
            for cond in g.requires:
                if not evaluate_condition(cond, state):
                    label = COND_LABELS.get(cond, cond)
                    if label not in missing:
                        missing.append(label)
        return (len(missing) == 0), missing

    def block_reason(self, op: str, missing: List[str]) -> str:
        return (
            f"【流程门禁拦截】{OP_LABELS.get(op, op)}被阻止：前置条件未满足 —— "
            f"{'、'.join(missing)}。请先完成并确认当前阶段，不要跳过流程。"
        )

    # ---------- 拦截计数（按轮） ----------

    def mark_blocked(self, reason: str) -> None:
        self._blocked_this_step += 1
        self._last_reasons.append(reason)

    def consume_blocked(self) -> int:
        n = self._blocked_this_step
        self._blocked_this_step = 0
        return n

    def pause_message(self) -> str:
        reasons = "；".join(self._last_reasons[:3]) or "存在越阶操作"
        self._last_reasons = []
        return (
            f"（系统强制暂停）本轮有操作被流程门禁拦截：{reasons}。"
            f"请按 Skill 声明的流程先完成当前阶段并取得确认，再继续下一步。"
        )
