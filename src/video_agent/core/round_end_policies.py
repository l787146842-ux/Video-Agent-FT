"""轮末策略状态机：agent_loop 轮末注入点收敛为单一声明式策略表。

- 策略按 priority 升序执行；
- kind 语义：arbitrable=竞争暂停卡（按现行「先到先得 + not confirmation 守卫」
  语义顺序求值）；post_process=副作用块（警告/选项覆盖/审计），全部执行；
- 仲裁可观测：命中候选与胜出者经 tracer.record_card_decision 入 trace，
  /api/agent/traces 可见（对话区暂不渲染，决策点）。

归属层：层 9 系统兜底卡唯一代码落点（AGENTS §八治理条款摘要）。FC 轨的 flow_gate_pause
仍由 agent_loop 在工具执行后早返处理，共用本表 policy_id。
agent_loop 保留 re-export 壳（测试 patch/导入路径不变）。

输入契约（2026-09-03 I-1 收敛）：各策略只消费 RoundEndContext 一等字段，
不 getattr 反射已退役 StateOperationExecutor 字段；生产唯一构造点
（agent_loop 纯文本收尾分支）必须真实填充各策略 requires 的输入字段
（集成回归见 tests/unit/test_fc_leak_fakestop.py）。

退役记录（2026-09-03 用户裁决 Q2）：
- 闸机自愈策略：文本轨退役后拦截列表恒空、执行计数恒 0，生产路径
  永不可达；FC 轨闸机拦截已由 fc_gates reject_message 结构化回喂闭环。
  防复活见 scripts/check_legacy_orchestration.py FORBIDDEN。
- 结构审阅卡死副本：getattr 反射已退役 executor 零写入点字段（恒假）；
  活实现唯一 = fc_reconcile._reconcile_stage_review_card（消费 BatchLedger）。
- 轮末工具失败汇总策略（同口径退役）：生产唯一构造点
  ledger 恒 None、FC 批轮永不到轮末，恒不可达；工具部分失败已由 FC 轨
  fc_feedback.compose_failure_feedback 逐步回喂承接，退役不改变任何
  可观测行为。防复活见 scripts/check_legacy_orchestration.py FORBIDDEN。
"""
import ast
import inspect
import re
from dataclasses import dataclass, field, fields as dc_fields
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from loguru import logger

from src.video_agent.utils import live_metrics
from src.video_agent.core import prompt_gates

if TYPE_CHECKING:
    from src.video_agent.core.tracer import AgentTracer

# 策略种类
KIND_ARBITRABLE = "arbitrable"
KIND_POST_PROCESS = "post_process"

# ---------- 虚报检测（唯一消费点 = false_claim_audit / agent_loop 确认轮审计） ----------

_STRUCTURE_CLAIM_RE = re.compile(
    r"(?:已完成|完成|已创建|已拆解|已写入)\s*(?:关键元素)?(?:拆解|拆分|分组|故事板)"
    r"|(?:关键元素)?(?:拆解|拆分)完成|已创建\s*\d+\s*个分组并写入故事板",
)
# 批 12 · 1000 正向修复：规格完成宣称句式（完成式；「现在写入/接下来写入」
# 类将来时交给 fakestop 延续承诺检测，完成态宣称才进对账）
_SPEC_CLAIM_RE = re.compile(
    r"已(?:经)?\s*写入[^。；\n]{0,16}(?:制片|制作)?规格"
    r"|(?:制片|制作)?规格(?:文档)?已(?:经)?(?:写入|确立|建立|完成|锁定)"
    r"|已锁定\s*(?:制片|制作)?规格参数",
)
_FUTURE_MARKER_RE = re.compile(r"确认后|接下来|之后|即将|下一步|先确认|先将")

# 产物对账映射（批 12）：宣称句式 → 产物空判定谓词 → 展示名。
# 「宣称完成 + 账本为空 → 警告」的通用机制（1000 实证：口播「已锁定规格
# 参数…写入制片规格文档」而规格从未落盘——拒因承诺落空后模型假完成收尾，
# 此前仅结构类有对账）。谓词只读 state，不拦人（警告层）。
_PRODUCT_AUDIT: List[Tuple[re.Pattern, Any, str]] = [
    (_STRUCTURE_CLAIM_RE, prompt_gates.storyboard_is_empty, "结构搭建"),
    (_SPEC_CLAIM_RE,
     lambda st: not prompt_gates.has_spec_document(st), "制片规格"),
]

# fakestop：延续承诺措辞——正文声称要继续/正在做，却以 stop 收尾且零操作。
# 只覆盖任务流常见承诺句式，配合 applied==0 + skill 激活条件使用，防普通对话误触发。
_CONTINUATION_PROMISE_RE = re.compile(
    r"马上继续|继续推进|继续执行|现在(?:进行|执行|调用|写入|分析|拆解|开始)|"
    r"接下来(?:我|将|会)|即将开始|马上开始|立刻开始",
)


def _claims_structure_done(*texts: str) -> bool:
    """判定文本是否声称已完成故事板结构搭建（防虚报闸的文本检测）。

    - 每个文本段独立判定（正文结尾与暂停文案开头跨文本拼接不得误报）；
    - 含未来/预告措辞的段落不算声称（误伤措辞豁免）。
    """
    for t in texts:
        text = str(t or "")
        if _FUTURE_MARKER_RE.search(text):
            continue
        if _STRUCTURE_CLAIM_RE.search(text):
            return True
    return False


def claims_unbacked_products(*texts: str, state: Dict[str, Any]) -> List[str]:
    """批 12 对账扩展：返回「正文宣称已完成、但产物账本为空」的产物名列表。

    - 逐文本段独立判定 + 未来/预告措辞豁免（4444 误报校准基调不变）；
    - 产物族由 _PRODUCT_AUDIT 声明（结构搭建 / 制片规格，声明即对账）；
    - 只判定不处置：消费方（false_claim_audit / agent_loop 确认轮）附警告。
    """
    unbacked: List[str] = []
    for t in texts:
        text = str(t or "")
        if _FUTURE_MARKER_RE.search(text):
            continue
        for claim_re, empty_pred, label in _PRODUCT_AUDIT:
            if label in unbacked:
                continue
            if claim_re.search(text) and empty_pred(state or {}):
                unbacked.append(label)
    return unbacked


@dataclass
class RoundEndContext:
    """轮末策略求值上下文：承载 step 循环末尾的全部可读状态与可写字段。

    可写字段由各策略修改，run_round_end_policies 结束后由 agent_loop 回读。

    输入契约（2026-09-03 I-1，轮末失败汇总策略退役后收敛）：
    - applied：本回合已执行工具累计数（agent_loop 填 result.applied_actions；
      FC 批轮在循环内已 continue/break，到达轮末的只有纯文本收尾轮，
      填真实累计值而非死值 0，假停判定才可达）；
    - ledger 字段已随轮末失败汇总策略退役删除（生产恒不可达，
      工具成败归 FC 轨 fc_feedback 逐步回喂）；
    - 策略需要的新输入一律显式提升为本 dataclass 一等字段并登记进
      requires，禁止 getattr(ctx, ..., 默认值) 摸字段（I-1.4，登记期自检
      _validate_policy_table 机械拦截）。
    """
    step: int = 0
    executor: Any = None
    content: str = ""
    skill: str = ""
    # 输入态（agent_loop 填充）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    wants_continue: bool = False
    applied: int = 0
    # 输出态（策略写入，agent_loop 回读）
    hard_break: bool = False
    hard_break_finish: str = ""
    result_warnings: List[str] = field(default_factory=list)
    result_text: str = ""
    # fakestop：轮末策略机械追加的建议动作（agent_loop 回读并入 result）
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)
    # 仲裁记录（候选 + 胜出者）
    candidates: List[str] = field(default_factory=list)
    winner: str = ""


@dataclass
class RoundEndPolicy:
    """单条轮末策略：稳定 policy_id + 种类 + 优先级 + 条件 + 动作 + 依赖声明。

    apply 签名统一为 (ctx, emit)——需要发 SSE 状态的策略使用 emit，
    其余策略忽略 emit。

    requires：本策略条件/动作显式依赖的 RoundEndContext 字段名元组。
    登记期自检（_validate_policy_table）对 condition/apply 做 AST 扫描：
    实际访问的 ctx.<attr> 集合必须与 requires 一致且均为 dataclass 字段，
    并禁止 getattr(ctx, ..., 默认值) 形态（2026-09-03 I-1.4 强化：
    上一代自检只查 requires 名字存在性，声明 requires=("executor",) 即可
    100% 通过、对「getattr 摸 executor 上已退役属性拿默认假值」零覆盖）。
    """
    policy_id: str
    kind: str
    priority: int
    condition: Callable[[RoundEndContext], bool]
    apply: Callable[[RoundEndContext, Callable], Awaitable[None]]
    requires: tuple = ()


# 输出态字段（策略写入/追加，agent_loop 回读）：对其基对象的读取
# （ctx.result_warnings.append / ctx.result_text 拼接）属契约行为，
# 不计入 requires 一致性比对的「输入依赖」
_OUTPUT_FIELDS = frozenset({
    "hard_break", "hard_break_finish", "result_warnings", "result_text",
    "suggested_actions", "candidates", "winner",
})


class _CtxAccessScanner(ast.NodeVisitor):
    """收集策略代码对 ctx 的实际访问（I-1.4）。

    - 绑定名默认 ctx（RoundEndContext 形参约定名），经局部赋值/形参改名
      的绑定同样跟踪；
    - getattr(ctx, "attr", 默认值) 是死规则入口形态（摸已退役属性拿
      默认假值静默恒假）：直接标记违规；两参 getattr（无默认，缺失即抛）
      按访问的字段名收集；
    - 只收集属性**读取**（ast.Load）：策略对输出态字段的写入
      （ctx.result_warnings.append 等）属契约行为，不算输入依赖。
    """

    def __init__(self) -> None:
        self.ctx_names: Set[str] = {"ctx"}
        self.attrs: Set[str] = set()
        self.getattr_default_hits: List[str] = []

    def visit_FunctionDef(self, node):
        self._bind_args(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def _bind_args(self, node) -> None:
        args = getattr(node, "args", None)
        if args is None:
            return
        for a in list(getattr(args, "args", [])) + list(getattr(args, "kwonlyargs", [])):
            name = getattr(a, "arg", "")
            if isinstance(name, str) and name:
                self.ctx_names.add(name)

    def visit_Assign(self, node):
        # 别名绑定（alias = ctx）同样跟踪
        if isinstance(node.value, ast.Name) and node.value.id in self.ctx_names:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    self.ctx_names.add(tgt.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # 写入目标（ctx.result_text = ...）不算读取依赖；
        # 但其内层表达式仍须递归（ctx.a.b = v 中 ctx.a 是读取）
        if isinstance(node.ctx, ast.Load):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in self.ctx_names
            ):
                self.attrs.add(node.attr)
            self.generic_visit(node)
        else:
            self.visit(node.value)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in self.ctx_names
        ):
            key = (
                node.args[1].value
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                else "<非字面量>"
            )
            if len(node.args) >= 3:
                self.getattr_default_hits.append(str(key))
            elif isinstance(key, str):
                self.attrs.add(key)
        self.generic_visit(node)


def _parse_normalized(text: str) -> Optional[ast.AST]:
    """按首行缩进归一后尝试 ast.parse（失败返回 None）。"""
    lines = text.splitlines()
    if not lines:
        return None
    first_indent = len(lines[0]) - len(lines[0].lstrip())
    normalized = "\n".join(
        (ln[first_indent:] if len(ln) >= first_indent else ln.lstrip())
        for ln in lines
    )
    try:
        return ast.parse(normalized)
    except SyntaxError:
        return None


def _policy_func_source_tree(func) -> Optional[ast.AST]:
    """取策略 condition/apply 的 AST（lambda 亦可）。

    - 命名函数：inspect.getsource 直接可解析；
    - lambda（测试策略表常见形态，可能带尾逗号/多行续行）：从定义行起
      按递增前缀尝试解析，首个成功的平衡前缀即 lambda 本体；
    - 源码不可得（exec/REPL 动态生成）返回 None——调用方显式拒绝，
      不留「取不到源码即跳过扫描」的绕过面。
    """
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):
        src = None
    if src:
        tree = _parse_normalized(src)
        if tree is not None:
            return tree
    # 宽容提取（lambda/尾逗号形态）：从 co_firstlineno 起逐行扩展前缀解析
    code = getattr(func, "__code__", None)
    try:
        filename = code.co_filename if code else inspect.getsourcefile(func)
        with open(filename, "r", encoding="utf-8") as fh:
            file_lines = fh.read().splitlines()
    except (OSError, TypeError, AttributeError):
        return None
    if not code or code.co_firstlineno <= 0:
        return None
    start = code.co_firstlineno - 1
    for end in range(start + 1, min(start + 50, len(file_lines)) + 1):
        tree = _parse_normalized("\n".join(file_lines[start:end]))
        if tree is not None:
            return tree
    return None


def _scan_policy_ctx_access(policy: RoundEndPolicy) -> Tuple[Set[str], List[str]]:
    """AST 扫描策略 condition/apply，返回（实际读取的 ctx 字段集，
    getattr-带默认值违规清单）。源码不可得即 RuntimeError（拒绝注册，
    扫描不可绕过）。"""
    accessed: Set[str] = set()
    violations: List[str] = []
    for func in (policy.condition, policy.apply):
        tree = _policy_func_source_tree(func)
        if tree is None:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' 的 "
                f"{getattr(func, '__name__', func)!r} 源码不可得，"
                "无法执行 ctx 访问 AST 自检（登记期拒绝，扫描不可绕过）"
            )
        scanner = _CtxAccessScanner()
        scanner.visit(tree)
        accessed |= scanner.attrs
        violations.extend(scanner.getattr_default_hits)
    return accessed, violations


def _validate_policy_table(table: List[RoundEndPolicy]) -> None:
    """登记期依赖自检（I-1.4 强化）：

    1. requires 声明的字段必须存在于 RoundEndContext；
    2. AST 扫描 condition/apply 实际读取的 ctx.<attr> 集合，断言与
       requires 一致（多声明 = 幽灵依赖，少声明 = 隐藏依赖，均拒收）；
    3. 禁止 getattr(ctx, "...", 默认值)——上一代死副本的真死因形态，
       声明合法 requires 即可绕过旧自检，此处机械拦截。

    在模块加载时对 ROUND_END_POLICIES 执行一次；违规即 RuntimeError
    （import 期报错，不留到运行期静默恒假）。
    """
    ctx_field_names = {f.name for f in dc_fields(RoundEndContext)}
    for policy in table:
        missing = set(policy.requires) - ctx_field_names
        if missing:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' 声明依赖的字段不存在于 "
                f"RoundEndContext: {sorted(missing)}（登记期自检拒绝）"
            )
        accessed, getattr_hits = _scan_policy_ctx_access(policy)
        if getattr_hits:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' 使用带默认值的 "
                f"getattr(ctx, ..., 默认)（死规则入口形态，禁止）: "
                f"{sorted(set(getattr_hits))}——需要的字段请显式提升为 "
                "RoundEndContext 一等字段并登记进 requires"
            )
        req = set(policy.requires)
        # (b1) 实际访问的字段均必须是 dataclass 一等字段（摸已退役/
        #      不存在属性即拒绝）
        unknown = accessed - ctx_field_names
        if unknown:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' 访问了 RoundEndContext "
                f"不存在的字段: {sorted(unknown)}（登记期自检拒绝）"
            )
        # (b2) requires 声明的依赖必须真被访问（防幽灵/陈旧声明）
        ghost = req - accessed
        if ghost:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' requires 声明了实际未访问的 "
                f"字段（幽灵依赖）: {sorted(ghost)}（登记期自检拒绝）"
            )
        # (b3) 访问但未声明的字段必须是已知输出态（策略写入/回读）；
        #      输入依赖（非输出态字段的读取）必须登记进 requires，否则为隐藏依赖
        hidden = accessed - req - _OUTPUT_FIELDS
        if hidden:
            raise RuntimeError(
                f"[RoundEnd] 策略 '{policy.policy_id}' 访问了输入依赖字段但未登记进 "
                f"requires（隐藏依赖）: {sorted(hidden)}（登记期自检拒绝）"
            )


async def run_round_end_policies(
    ctx: RoundEndContext,
    emit: Callable[[Dict[str, Any]], Awaitable[None]],
    tracer: Optional["AgentTracer"] = None,
    policies: Optional[List[RoundEndPolicy]] = None,
) -> RoundEndContext:
    """按优先级顺序执行策略表。

    仲裁可观测：arbitrable 策略条件为真即入候选名单；最终 confirmation
    非空时记录胜出者（第一个真正写入 confirmation 的策略）。
    """
    table = policies if policies is not None else ROUND_END_POLICIES
    for policy in sorted(table, key=lambda p: p.priority):
        try:
            hit = policy.condition(ctx)
        except Exception as e:
            # 策略条件求值失败入遥测（防闸机接线静默断裂）
            live_metrics.record_degradation(f"round_end.{policy.policy_id}")
            logger.warning(f"[RoundEnd] 策略 {policy.policy_id} 条件求值失败（跳过）: {e}")
            continue
        if not hit:
            continue
        if policy.kind == KIND_ARBITRABLE:
            ctx.candidates.append(policy.policy_id)
        before = bool(ctx.confirmation)
        await policy.apply(ctx, emit)
        if (
            policy.kind == KIND_ARBITRABLE
            and not ctx.winner
            and ctx.confirmation
            and not before
        ):
            ctx.winner = policy.policy_id
        if ctx.hard_break:
            break
    if tracer is not None and (ctx.candidates or ctx.winner):
        tracer.record_card_decision(ctx.step, ctx.candidates, ctx.winner)
    return ctx


# ---------- 各策略实现 ----------

# 轮末工具失败汇总策略已退役（2026-09-03，同闸机自愈策略口径）：
# 生产唯一构造点（agent_loop 纯文本收尾分支）永无 FC 账本可消费，恒不可达；
# 工具部分失败已由 FC 轨 fc_feedback.compose_failure_feedback 逐步回喂承接。
# 防复活见 scripts/check_legacy_orchestration.py FORBIDDEN。


def _cond_false_claim_audit(ctx: RoundEndContext) -> bool:
    # 虚报检测与正文拼接收纳在同一块内；正文即模型可见文本，无需清洗
    return bool((ctx.content or "").strip())


async def _apply_false_claim_audit(ctx: RoundEndContext, emit: Callable) -> None:
    visible = (ctx.content or "").strip()
    if visible:
        # 对账扩展（批 12 · 1000 正向修复）：宣称完成任一产物（结构/规格…）
        # 而产物账本为空 → 警告（不拦人）。纯文本轮同样承重——1000 实录：
        # 混合轮被拦后续轮纯文本口播「已写入制片规格」收尾，此前仅确认轮
        # 有结构对账。逐段未来时豁免防误报（4444 校准基调）。
        unbacked = claims_unbacked_products(
            visible, state=(ctx.executor.state if ctx.executor else {}))
        if unbacked:
            ctx.result_warnings.append(
                "检测到虚报：正文声称已完成" + "、".join(unbacked)
                + "，但项目状态中对应产物实际缺失；请以工作台实际产物为准。"
            )
        ctx.result_text = (
            f"{ctx.result_text}\n\n{visible}".strip() if ctx.result_text else visible
        )


def _cond_aborted_continuation_audit(ctx: RoundEndContext) -> bool:
    # fakestop：模型说「马上继续/现在进行…」却零操作、无暂停地收尾，
    # 用户会困惑「怎么停了」。确定性三问全中（状态可算、机器可判、无创作空间），收归系统。
    return (
        bool(ctx.skill)
        and ctx.applied == 0
        and not ctx.confirmation
        and not ctx.wants_continue
        and not ctx.suggested_actions
        and bool(_CONTINUATION_PROMISE_RE.search(ctx.content or ""))
    )


async def _apply_aborted_continuation_audit(ctx: RoundEndContext, emit: Callable) -> None:
    # 批 3 · B4 拆伪按钮：label 固定「继续」——不再取平台统一 8 节点图算
    # 节点标题（异构 skill 恒失真，3333 同款误导源；"下一步"归模型聊天自述）。
    # 本策略只保留假停兜底语义（模型承诺继续却零操作 → 机械给继续按钮）。
    ctx.suggested_actions.append({"kind": "continue", "label": "继续", "value": "继续"})
    logger.info("[RoundEnd] audit-0819-fakestop: 延续承诺措辞且零操作，机械追加继续按钮")


# （批 3 · B4 拆伪按钮：状态驱动的"下一步建议"函数族整体退役——平台统一
# 8 节点图量异构 skill 必失真；UI 只保留"已有什么"展示（事件卡时间线/
# 画布/素材面板），"下一步"由模型聊天自述。防复活符号字面归
# scripts/check_legacy_orchestration.py FORBIDDEN，本文件不再出现。）


# 策略表（优先级升序执行；登记期自检见 _validate_policy_table：
# requires 与实际 ctx 访问 AST 扫描一致 + 禁 getattr 带默认值）
ROUND_END_POLICIES: List[RoundEndPolicy] = [
    RoundEndPolicy("false_claim_audit", KIND_POST_PROCESS, 120,
                   _cond_false_claim_audit, _apply_false_claim_audit,
                   requires=("content", "executor")),
    RoundEndPolicy("aborted_continuation_audit", KIND_POST_PROCESS, 130,
                   _cond_aborted_continuation_audit, _apply_aborted_continuation_audit,
                   requires=("skill", "applied", "confirmation", "wants_continue",
                             "suggested_actions", "content")),
]

# 登记期依赖自检（模块加载即执行；引用不存在字段的死策略在 import 期报错）
_validate_policy_table(ROUND_END_POLICIES)
