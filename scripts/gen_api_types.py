"""从 FastAPI OpenAPI schema + SSE sidecar 契约生成前端 TS 类型（前后端契约一致性）。

用法：
    python scripts/gen_api_types.py          # 生成 sidecar + src/web/types/api.generated.ts
    python scripts/gen_api_types.py --check  # 校验两份产物与后端契约一致（CI 用，漂移退出码 1）

产物（--check 双门禁，同批漂移同批修）：
1. src/web/types/sse.schema.json —— SSE 契约 sidecar（后端 Pydantic 模型/错误语义/
   工具展示档元数据的 JSON 导出，本脚本生成模式自动重写，禁止手改）；
2. src/web/types/api.generated.ts —— TS 类型（OpenAPI components + sidecar 全部契约）。

生成的类型覆盖路由层请求/响应模型（components.schemas）；前端 API 边界
类型以本生成物为唯一来源（tsc 编译期即契约门禁），视图态类型
（ChatMessage/Draft 等纯 UI 形态）继续手工维护于 types/index.ts。

输出约定：成败信息一律带 ASCII 前缀（OK: / FAIL:），
防 Windows GBK 终端乱码把失败误读成通过——验收只认退出码，不人眼读文案。
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 保证从任意工作目录运行时都能导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_PATH = "src/web/types/api.generated.ts"
# SSE 契约 sidecar（任务 #4）：后端契约模型 → JSON 单一事实源 → 本脚本消费生成 TS
SIDECAR_PATH = "src/web/types/sse.schema.json"

# 需要生成 TS 接口的 schema 名（OpenAPI components.schemas 子集，排除 FastAPI 内置）
_SKIP = {"HTTPValidationError", "ValidationError"}

# 非工具的时间线内部条目（展示档恒定 none，不经工具元数据；
# 其余未知名走默认档 output——新工具至少留输出痕迹）
_TOOL_DETAIL_INTERNAL_NONE = ("model_reasoning",)


def ts_type(schema: Dict[str, Any], components: Dict[str, Any]) -> str:
    """把 JSON Schema 片段转译为 TS 类型字符串"""
    if not isinstance(schema, dict):
        return "unknown"
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return name
    # 字面量判别列（整改批 3.2）：Literal["x"] → JSON Schema const/单值 enum，
    # 生成 TS 字面量类型，前端联合类型可收窄
    if "const" in schema:
        v = schema["const"]
        return f"'{v}'" if isinstance(v, str) else json.dumps(v)
    if "enum" in schema and isinstance(schema["enum"], list) and len(schema["enum"]) == 1:
        v = schema["enum"][0]
        return f"'{v}'" if isinstance(v, str) else json.dumps(v)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [ts_type(s, components) for s in schema[key]]
            # Optional[X] 会产生 X | null：收敛为 X | undefined 更贴合 TS 习惯
            has_null = "null" in parts
            parts = [p for p in parts if p != "null"]
            parts = list(dict.fromkeys(parts))  # 去重保序（int/float 同映射 number）
            if len(parts) == 1:
                return f"{parts[0]} | undefined" if has_null else parts[0]
            return " | ".join(parts)
    t = schema.get("type")
    if t == "null":
        return "null"
    if t == "array":
        return f"{ts_type(schema.get('items', {}), components)}[]"
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "object":
        props = schema.get("properties")
        if not props:
            # Dict[str, X] 投影：additionalProperties 有 schema 时收窄值类型
            # （Dict[str, Any] 的 additionalProperties 为空对象，退化为 unknown）
            addl = schema.get("additionalProperties")
            if isinstance(addl, dict) and addl:
                return f"Record<string, {ts_type(addl, components)}>"
            return "Record<string, unknown>"
        # 内联对象（少见）：展开为索引签名
        return "Record<string, unknown>"
    return "unknown"


def gen_interface(name: str, schema: Dict[str, Any], components: Dict[str, Any]) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for pname, pschema in props.items():
        optional = "" if pname in required else "?"
        desc = pschema.get("description") if isinstance(pschema, dict) else None
        if desc:
            lines.append(f"  /** {desc.splitlines()[0]} */")
        lines.append(f"  {pname}{optional}: {ts_type(pschema, components)};")
    lines.append("}")
    return "\n".join(lines)


# ===== SSE sidecar（任务 #4 批 1）：后端契约模型 → JSON 导出 =====

def _collect_tool_tiers() -> tuple[Dict[str, str], Dict[str, str]]:
    """工具元数据确定性采集：不依赖调用时刻的全局注册态。
    返回 (展示档表, 审批档表)，两表同一次隔离注册态上采集（任务 P2-5）。

    全量 pytest 会话中其他测试会向 ToolManager 增删注册（如 MCP 目录工具），
    直接读全局态会让 sidecar 随测试顺序漂移。故在隔离注册态上重放全部
    标准注册入口（与 app 启动期 plugins.py 口径一致）采集，完成后原样恢复。
    """
    import src.video_agent.tools  # noqa: F401 基础工具注册（import 副作用，仅保模块就绪）
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.canvas_tools import register_canvas_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.manager import ToolManager
    from src.video_agent.tools.mcp.catalog import McpToolCatalogTool
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    from src.video_agent.tools.video.generate_video import GenerateVideoTool

    saved = dict(ToolManager._tools)  # noqa: SLF001 隔离采集：快照 + 恢复
    try:
        ToolManager.reset()
        ToolManager.register(GenerateVideoTool())
        register_storyboard_tools()
        register_document_tools()
        register_analysis_tools()
        register_canvas_tools()
        ToolManager.register(McpToolCatalogTool())  # 运行时按需注册，契约面须覆盖
        return ToolManager.get_tool_detail_tiers(), ToolManager.get_tool_approval_tiers()
    finally:
        ToolManager.reset()
        for tool in saved.values():
            ToolManager.register(tool)


def build_sidecar() -> Dict[str, Any]:
    """从后端契约模型装配 sidecar（生成模式的权威来源；check 模式的漂移基准）。

    内容六段：事件帧 schema（core/sse_events TS_EVENT_FRAMES）、错误语义契约
    （web/error_payload：ErrorPayload 模型 + kind 封闭集 + legacy 桥接表）、
    工具时间线展示档（各工具 detail_tier 声明）、默认档/内部 none 名单、
    工具审批分级档（任务 P2-5：生效 approval_tier 表 + 默认档）、
    执行偏好三档枚举（批 B：config 白名单 + 默认档）、
    执行模式四档枚举（2026-09-06 Flova 对齐批：config 白名单 + 默认档）。
    """
    # 延迟导入：确保项目根在 sys.path（以模块方式运行时自动满足）
    from src.video_agent.config import (
        EXECUTION_MODE_DEFAULT,
        EXECUTION_MODE_VALUES,
        EXECUTION_PREFERENCE_DEFAULT,
        EXECUTION_PREFERENCE_VALUES,
    )
    from src.video_agent.core.sse_events import TS_EVENT_FRAMES
    from src.video_agent.web import error_payload as ep

    frames = [
        {"name": ts_name, "schema": model.model_json_schema(by_alias=True)}
        for ts_name, model in TS_EVENT_FRAMES
    ]
    detail_tiers, approval_tiers = _collect_tool_tiers()
    return {
        "version": 1,
        "source": (
            "生成物勿手改：python scripts/gen_api_types.py。事实源 = "
            "core/sse_events.py TS_EVENT_FRAMES + web/error_payload.py + "
            "工具 detail_tier/approval_tier 声明"
        ),
        "frames": frames,
        "error_contract": {
            "payload_schema": ep.ErrorPayload.model_json_schema(),
            "kinds": list(ep.ALL_KINDS),
            "legacy_code_map": {
                k: {"kind": kind, "code": code}
                for k, (kind, code) in sorted(ep.LEGACY_CODE_MAP.items())
            },
        },
        "tool_detail_tiers": dict(sorted(detail_tiers.items())),
        "tool_detail_tier_default": "output",
        "tool_detail_internal_none": list(_TOOL_DETAIL_INTERNAL_NONE),
        # 任务 P2-5：生效审批分级（显式声明 + 推导档统一收录）；默认档
        # confirm = 未登记工具按 high risk 口径 deny-by-default
        "tool_approval_tiers": dict(sorted(approval_tiers.items())),
        "tool_approval_tier_default": "confirm",
        # 批 B：执行偏好三档白名单（事实源 = config.EXECUTION_PREFERENCE_VALUES）
        "execution_preference": {
            "values": list(EXECUTION_PREFERENCE_VALUES),
            "default": EXECUTION_PREFERENCE_DEFAULT,
        },
        # 2026-09-06：执行模式四档白名单（事实源 = config.EXECUTION_MODE_VALUES）
        "execution_mode": {
            "values": list(EXECUTION_MODE_VALUES),
            "default": EXECUTION_MODE_DEFAULT,
        },
    }


def sidecar_text(sidecar: Dict[str, Any]) -> str:
    return json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n"


# ===== TS 渲染：OpenAPI components + sidecar 契约 =====

def _render_sse_section(sidecar: Dict[str, Any]) -> List[str]:
    """sidecar → TS 分节：逐帧 interface + SseEvent 联合 + 错误契约常量 + 工具展示档常量"""
    chunks: List[str] = [
        f"// ===== SSE 事件载荷（sidecar：{SIDECAR_PATH}）=====",
        "",
    ]
    # 帧内嵌套子模型统一汇入 components，供 $ref 解析（与 OpenAPI 段同机制）
    components: Dict[str, Any] = {}
    for frame in sidecar["frames"]:
        for def_name, def_schema in (frame["schema"].get("$defs") or {}).items():
            components[def_name] = def_schema
    event_members: List[str] = []
    for frame in sidecar["frames"]:
        schema = {k: v for k, v in frame["schema"].items() if k != "$defs"}
        chunks.append(gen_interface(frame["name"], schema, components))
        chunks.append("")
        type_schema = schema.get("properties", {}).get("type", {})
        if isinstance(type_schema.get("const"), str):
            event_members.append(frame["name"])
    chunks.append("/** SSE 事件联合类型（判别列 = type 字面量；后端帧模型自动生成） */")
    chunks.append("export type SseEvent =")
    chunks.append("  | " + "\n  | ".join(event_members) + ";")
    chunks.append("")

    ec = sidecar["error_contract"]
    chunks.append("// ===== 错误语义契约（来源：web/error_payload.py，sidecar 导出）=====")
    chunks.append("")
    chunks.append(gen_interface("ErrorPayloadContract", ec["payload_schema"], components))
    chunks.append("")
    kinds = ec["kinds"]
    chunks.append("/** 错误归类封闭集合（后端 ALL_KINDS 生成，改动自动同步） */")
    chunks.append("export const SSE_ERROR_KINDS = [" + ", ".join(f"'{k}'" for k in kinds) + "] as const;")
    chunks.append("export type SseErrorKind = (typeof SSE_ERROR_KINDS)[number];")
    chunks.append("/** legacy error_code → kind/code 桥接表（后端 LEGACY_CODE_MAP 生成） */")
    chunks.append("export const SSE_LEGACY_ERROR_CODES: Record<string, { kind: SseErrorKind; code: string }> = {")
    for legacy, pair in ec["legacy_code_map"].items():
        chunks.append(f"  {legacy}: {{ kind: '{pair['kind']}', code: '{pair['code']}' }},")
    chunks.append("};")
    chunks.append("")

    chunks.append("// ===== 工具时间线展示档（来源：各工具 detail_tier 声明，sidecar 导出）=====")
    chunks.append("")
    chunks.append("/** 工具名 → 展示档（expand=展开输入+结果 / output=仅输出留痕） */")
    chunks.append("export const TOOL_DETAIL_TIERS: Record<string, 'expand' | 'output'> = {")
    for tool, tier in sidecar["tool_detail_tiers"].items():
        chunks.append(f"  {tool}: '{tier}',")
    chunks.append("};")
    chunks.append("/** 未登记工具/未知名的默认档（新工具至少留输出痕迹） */")
    chunks.append(f"export const TOOL_DETAIL_TIER_DEFAULT = '{sidecar['tool_detail_tier_default']}' as const;")
    chunks.append("/** 非工具内部条目（恒定 none，不经元数据） */")
    internal = ", ".join(f"'{n}'" for n in sidecar["tool_detail_internal_none"])
    chunks.append(f"export const TOOL_DETAIL_INTERNAL_NONE: readonly string[] = [{internal}] as const;")
    chunks.append("")

    # 任务 P2-5：审批分级正交轴（与展示档正交；前端确认卡/审批交互映射依据）
    chunks.append("// ===== 工具审批分级档（来源：各工具 approval_tier 声明/推导，sidecar 导出）=====")
    chunks.append("")
    chunks.append("/** 工具名 → 生效审批档（none=无需审批 / confirm=执行前确认卡 / review=人工审批复核） */")
    chunks.append("export const TOOL_APPROVAL_TIERS: Record<string, 'none' | 'confirm' | 'review'> = {")
    for tool, tier in sidecar["tool_approval_tiers"].items():
        chunks.append(f"  {tool}: '{tier}',")
    chunks.append("};")
    chunks.append("/** 未登记工具的默认档（high risk 口径，deny-by-default） */")
    chunks.append(f"export const TOOL_APPROVAL_TIER_DEFAULT = '{sidecar['tool_approval_tier_default']}' as const;")
    chunks.append("")

    # 批 B：执行偏好三档（花钱生成动作是否先弹确认卡；前端设置页三选与契约收窄同引用）
    chunks.append("// ===== 执行偏好三档（来源：config.py 白名单枚举，sidecar 导出）=====")
    chunks.append("")
    ep = sidecar["execution_preference"]
    chunks.append("/** 执行偏好三档枚举（花钱生成动作是否先弹确认卡） */")
    chunks.append("export const EXECUTION_PREFERENCE_VALUES = ["
                  + ", ".join(f"'{v}'" for v in ep["values"]) + "] as const;")
    chunks.append("export type ExecutionPreference = (typeof EXECUTION_PREFERENCE_VALUES)[number];")
    chunks.append("/** 默认档（= 现状行为：每次花钱生成前弹确认卡） */")
    chunks.append(f"export const EXECUTION_PREFERENCE_DEFAULT = '{ep['default']}' as const;")
    chunks.append("")

    # 2026-09-06：执行模式四档（流程推进的暂停策略；前端设置页四选与契约收窄同引用）
    chunks.append("// ===== 执行模式四档（来源：config.py 白名单枚举，sidecar 导出）=====")
    chunks.append("")
    em = sidecar["execution_mode"]
    chunks.append("/** 执行模式四档枚举（流程推进的暂停策略） */")
    chunks.append("export const EXECUTION_MODE_VALUES = ["
                  + ", ".join(f"'{v}'" for v in em["values"]) + "] as const;")
    chunks.append("export type ExecutionMode = (typeof EXECUTION_MODE_VALUES)[number];")
    chunks.append("/** 默认档（= 现状行为：停不停由模型按 Skill 散文与当场情况判断） */")
    chunks.append(f"export const EXECUTION_MODE_DEFAULT = '{em['default']}' as const;")
    chunks.append("")
    return chunks


def build_output(sidecar: Dict[str, Any] | None = None) -> str:
    # 延迟导入：确保项目根在 sys.path（以模块方式运行时自动满足）
    from src.video_agent.web.app import app

    if sidecar is None:
        sidecar = build_sidecar()

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    chunks: List[str] = [
        "/**",
        " * 自动生成 —— 请勿手工编辑。",
        " * 来源：FastAPI OpenAPI schema + SSE sidecar（python scripts/gen_api_types.py）",
        " * 用途：前端 API 边界类型的唯一来源；",
        " * 视图态类型（ChatMessage 等纯 UI 形态）见手写 src/web/types/index.ts。",
        " */",
        "",
    ]
    for name in sorted(components.keys()):
        if name in _SKIP:
            continue
        schema = components[name]
        if schema.get("type") != "object" and "properties" not in schema:
            continue
        chunks.append(gen_interface(name, schema, components))
        chunks.append("")

    chunks.extend(_render_sse_section(sidecar))
    return "\n".join(chunks)


def main(out_path: str = OUT_PATH, sidecar_path: str | None = None) -> int:
    # sidecar 默认与 TS 产物同目录（双产物成对；tmp 目录注入时跟随 out_path）
    if sidecar_path is None:
        sidecar_path = str(Path(out_path).parent / Path(SIDECAR_PATH).name)
    sidecar_expected = build_sidecar()
    expected = build_output(sidecar_expected)
    if "--check" in sys.argv:
        # 先比 TS 产物（漂移金丝雀测试只构造 TS 一侧，顺序保证先命中 TS 失败）
        try:
            with open(out_path, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            print(f"[gen_api_types] FAIL: {out_path} missing - run without --check first")
            return 1
        if current.strip() != expected.strip():
            print("[gen_api_types] FAIL: contract drift - run python scripts/gen_api_types.py")
            return 1
        # 再比 sidecar 产物（后端模型/元数据漂移第二道闸）
        try:
            with open(sidecar_path, encoding="utf-8") as f:
                current_sidecar = f.read()
        except FileNotFoundError:
            print(f"[gen_api_types] FAIL: {sidecar_path} missing - run without --check first")
            return 1
        if current_sidecar.strip() != sidecar_text(sidecar_expected).strip():
            print(f"[gen_api_types] FAIL: sidecar drift ({sidecar_path}) - run python scripts/gen_api_types.py")
            return 1
        print("[gen_api_types] OK: contract consistent (ts + sidecar)")
        return 0
    Path(sidecar_path).parent.mkdir(parents=True, exist_ok=True)
    with open(sidecar_path, "w", encoding="utf-8") as f:
        f.write(sidecar_text(sidecar_expected))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(expected)
    print(f"[gen_api_types] OK: generated {out_path} + {sidecar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
