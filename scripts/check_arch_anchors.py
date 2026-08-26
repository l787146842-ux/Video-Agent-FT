"""宪法锚点校验门禁（任务 #12 批次2：ARCHITECTURE_RULES.md 关键不变量机械守门）。

宪法（ARCHITECTURE_RULES.md）以散文承载核心架构铁律，铁律落点（文件路径 +
关键不变量符号）一旦漂移，宪法即成空文。本门禁以 Policy-as-Data 方式登记
锚点清单（ANCHORS），逐项机械校验：

1. 锚点文件路径存在（宪法条款指向的承重文件不得被改名/删除而无同批修宪）；
2. 锚点符号存在（.py 锚点声明顶层符号时，用 ast 校验该文件定义了该符号
   ——类/函数/顶层赋值均可），防「文件在、承重符号搬走」的半漂移。

与 check_doc_pointers 的分工：doc_pointers 校验「文件地图路径 + 注释/docstring
指针」的存在性（广义指针漂移）；本门禁校验「宪法条款 → 不变量符号」的
承重绑定（锚点清单是人工审定的不变量登记表，不是全文指针扫描）。

退役条件（GOVERNANCE §13.14(c)）：宪法条款全面数据化（锚点并入
scaffold_registry/coupling_registry 机器可读登记表且本脚本清单清空），
或锚点漂移连续两季零检出、修宪同批更新锚点内化为开发惯例时裁决下账。

输出纯 ASCII 前缀（验收乱码误读教训）。用法：python scripts/check_arch_anchors.py
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 锚点登记表：(宪法条款, 相对路径, 顶层符号或 None 仅校验路径)。
# 增删宪法承重条款时必须同批更新本表（门禁冻结见 GOVERNANCE §13.14(f)）。
ANCHORS = [
    # Rule 1：Planner 唯一入口
    ("Rule1", "src/video_agent/core/planner.py", "Planner"),
    # Rule 2：节点内有界模型循环唯一实现 + MAX_STEPS 读 settings
    ("Rule2", "src/video_agent/core/agent_loop.py", "run_agent_loop"),
    # Rule 2：Workflow Runtime 账本+裁判数据层（主体回归，ADR-0004）
    ("Rule2", "src/video_agent/core/workflow_runtime.py", "WorkflowRuntime"),
    # Rule 2：动作语义唯一实现（故事板领域逻辑）
    ("Rule2", "src/video_agent/state/storyboard_ops.py", None),
    # Rule 2 层级例外清偿（D-01）：core 端口 + web 装配点注入
    ("Rule2-D01", "src/video_agent/core/ports.py", None),
    ("Rule2-D01", "src/video_agent/web/port_wiring.py", None),
    ("Rule2-D01", "src/video_agent/core/action_executor.py", None),
    # Rule 3：StateManager 唯一写入点
    ("Rule3", "src/video_agent/state/manager.py", "StateManager"),
    # Rule 4：外部调用必须走 Adapter
    ("Rule4", "src/video_agent/adapters/base_chat.py", "BaseChatAdapter"),
    ("Rule4", "src/video_agent/adapters/base.py", None),
    # Rule 5：Tool 统一注册（risk 分级 deny-by-default）
    ("Rule5", "src/video_agent/tools/base.py", "BaseTool"),
    # Rule 6：提示词外置单一事实源 + 闸机文案外置
    ("Rule6", "src/video_agent/utils/prompts.py", "load_prompt"),
    ("Rule6", "prompts/planner/system_fc.md", None),
    ("Rule6", "prompts/gates/messages.md", None),
    # Rule 7：画布边界（交互唯一封装）
    ("Rule7", "src/video_agent/adapters/canvas_adapter.py", None),
    # §2.0/§2.3：闸机管线唯一入口 + Policy-as-Data 注册表
    ("S2.0", "src/video_agent/core/guard_pipeline.py", None),
    ("S2.3", "src/video_agent/core/gate_registry.py", "GATE_RULES"),
    # §3：前端唯一入口（SolidJS SPA）与 web 装配
    ("S3", "src/web/app.tsx", None),
    ("S3", "src/video_agent/web/app.py", None),
    # 指令治理层（原第十三章迁出，与总纲同权）
    ("Ch13", "docs/GOVERNANCE.md", None),
]


def _top_level_names(path: pathlib.Path):
    """ast 提取模块顶层定义符号（类/函数/异步函数/赋值/注解赋值）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return None  # 解析失败按漂移处理由调用方报错（不静默放行）
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def main() -> int:
    fails = []
    for clause, rel, symbol in ANCHORS:
        p = ROOT / rel
        if not p.exists():
            fails.append(f"[{clause}] anchor path missing: {rel}")
            continue
        if symbol is None or not rel.endswith(".py"):
            continue
        names = _top_level_names(p)
        if names is None:
            fails.append(f"[{clause}] anchor file not parseable: {rel}")
        elif symbol not in names:
            fails.append(
                f"[{clause}] invariant symbol '{symbol}' not defined in {rel}")
    if fails:
        for h in fails:
            print(f"[check_arch_anchors]   {h}")
        print(
            f"[check_arch_anchors] FAIL: {len(fails)} anchor drift issue(s). "
            "ARCHITECTURE_RULES anchors (paths + invariant symbols) must "
            "be updated in the same batch as the constitutional change."
        )
        return 1
    print(
        f"[check_arch_anchors] PASS: {len(ANCHORS)} constitutional anchors "
        "intact (paths exist; invariant symbols defined)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
