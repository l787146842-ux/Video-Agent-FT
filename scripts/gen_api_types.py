"""从 FastAPI OpenAPI schema 生成前端 TS 类型（前后端契约一致性）。

用法：
    python scripts/gen_api_types.py          # 生成 src/web/types/api.generated.ts
    python scripts/gen_api_types.py --check  # 校验已有生成物与 schema 一致（CI 用，不一致退出码 1）

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

# 需要生成 TS 接口的 schema 名（OpenAPI components.schemas 子集，排除 FastAPI 内置）
_SKIP = {"HTTPValidationError", "ValidationError"}


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
            parts = [p for p in parts if p != "null"]
            if len(parts) == 1:
                return f"{parts[0]} | undefined" if "null" in [ts_type(s, components) for s in schema[key]] else parts[0]
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


def build_output() -> str:
    # 延迟导入：确保项目根在 sys.path（以模块方式运行时自动满足）
    from src.video_agent.web.app import app

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    chunks: List[str] = [
        "/**",
        " * 自动生成 —— 请勿手工编辑。",
        " * 来源：FastAPI OpenAPI schema（python scripts/gen_api_types.py）",
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

    # ===== SSE 事件载荷（整改批 3.2）：core/sse_events 单一事实源导出 =====
    # 事件帧模型不挂路由（不会出现在 OpenAPI components），显式枚举导出；
    # 嵌套子模型经各帧 model_json_schema 的 $defs 合并后按 $ref 解析。
    from src.video_agent.core.sse_events import TS_EVENT_FRAMES

    chunks.append("// ===== SSE 事件载荷（来源：core/sse_events.py TS_EVENT_FRAMES）=====")
    chunks.append("")
    for ts_name, model in TS_EVENT_FRAMES:
        schema = model.model_json_schema(by_alias=True)
        local = dict(components)
        for def_name, def_schema in (schema.get("$defs") or {}).items():
            local[def_name] = def_schema
        chunks.append(gen_interface(ts_name, schema, local))
        chunks.append("")
    return "\n".join(chunks)


def main(out_path: str = OUT_PATH) -> int:
    expected = build_output()
    if "--check" in sys.argv:
        try:
            with open(out_path, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            print(f"[gen_api_types] FAIL: {out_path} missing - run without --check first")
            return 1
        if current.strip() != expected.strip():
            print("[gen_api_types] FAIL: contract drift - run python scripts/gen_api_types.py")
            return 1
        print("[gen_api_types] OK: contract consistent")
        return 0
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(expected)
    print(f"[gen_api_types] OK: generated {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
