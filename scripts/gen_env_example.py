# -*- coding: utf-8 -*-
"""从 config.Settings 机械生成 .env.example（单一事实源 = config.py）。

设计：.env.example 不再手写维护——本脚本 AST 解析 src/video_agent/config.py 的
Settings 类，逐字段抽取 env 键 + 默认值 + 类型，并抓取字段上方的 # 注释作为文档，
按 config.SETTINGS_GROUPS 分组输出。config.py 改字段/改默认/改注释后重跑本脚本即可
让 .env.example 同步，杜绝「模板与代码漂移」。

口径：
- 只输出有 env 支撑的字段（_env_int / _env_bool / os.getenv / float(os.getenv)）；
  纯运行时热更新字段（skills_disabled / execution_preference / default_* /
  chat_image_enabled / max_shot_duration / model_policy 等，无 env 读取）跳过——
  它们经 /api/settings/runtime 通道写入，不属于 .env 配置面。
- 有代码默认值的运行参数以「# KEY=default」注释形态输出：复制为 .env 后按需
  取消注释/改值；未列出的键走代码内默认值（与不写该行等价）。
- 「必填但无代码默认值」的第三方凭据键（见 _REQUIRED_ACTIVE_KEYS，不在 Settings 内、
  经 provider_key_env 从进程环境变量 / API/.env 解析）以「激活态空值」输出
  （如 `OPENAI_API_KEY=`）：`cp .env.example .env` 后即为待填项，杜绝「cp 后全注释、
  无从下手」的上手回归。
- bool 默认渲染为 true/false（env 惯例小写）；str 空默认渲染为 KEY=（空值）。

用法：
    python scripts/gen_env_example.py           # 生成/覆写 .env.example
    python scripts/gen_env_example.py --check    # 校验是否与 config 同步（不同步退出码 1）
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONFIG_PY = os.path.join(ROOT, "src", "video_agent", "config.py")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")

# env 读取函数名 → 类型（用于默认值渲染口径）
_ENV_FUNCS = {"_env_int": "int", "_env_bool": "bool", "getenv": "str"}

# 「必填但无代码默认值」的第三方凭据键（不在 config.Settings 内，经
# provider_key_env 从进程环境变量 / API/.env 解析，无回落默认值）——以激活态空值
# 输出（cp .env.example .env 后即为待填项），与其余「有代码默认值、注释态」的运行
# 参数区分。敏感凭据亦可改放 API/.env（勿提交），二者取第一个非空值。
_REQUIRED_ACTIVE_KEYS = (
    ("OPENAI_API_KEY", "OpenAI 兼容供应商 API Key（进程环境变量优先，其次 API/.env）"),
    ("KLING_API_KEY", "可灵（Kling）视频生成 API Key"),
)

# 分组标题（SETTINGS_GROUPS 键 → 人读标题；缺省回落键名本身）
_GROUP_TITLES = {
    "server": "服务 / 关停",
    "security": "安全 / 认证 / 限流",
    "agent": "Agent 多步循环 / 执行偏好",
    "llm": "LLM 调用参数 / fallback / 模型分层",
    "context": "Token 预算 / 上下文治理 / 剪枝",
    "media": "图片 / 视频 / 音频生成 / 全局默认",
    "skills": "Skill 开关与目录",
    "tasks": "任务台账 / 快照 / trace 留存",
    "storage": "上传 / 存储后端 / 状态后端",
    "canvas": "画布集成（canvas-agent HTTP 协议）",
    "mcp": "MCP 外部工具接入层",
    "metrics": "遥测落盘",
}

_PREAMBLE = """\
# ============================================================
# .env.example — 由 scripts/gen_env_example.py 从 config.Settings 机械生成
# 单一事实源 = src/video_agent/config.py；请勿手改本文件。
# 改 config.py（字段/默认/注释）后重跑：python scripts/gen_env_example.py
#
# 用法：复制为根目录 .env，按需取消注释并填值；未列出的键走代码内默认值。
# 有代码默认值的运行参数以「# KEY=default」注释形态给出（default 即代码内默认值）；
# 「必填但无代码默认值」的第三方凭据键以激活态空值给出（如 OPENAI_API_KEY=），
# cp 后即为待填项。API Key 等敏感凭据亦可改放 API/.env（勿提交），二者取第一个非空值。
# ============================================================
"""


def _call_func_name(call: ast.Call) -> str:
    """返回调用的函数名（Name.id 或 Attribute.attr）。"""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _find_env_call(node: ast.AST):
    """在字段默认值表达式里定位 env 读取调用。

    返回 (env_key, default_node, kind)；无 env 支撑返回 None。
    兼容 _env_int("K", d) / _env_bool("K", d) / os.getenv("K", "d") /
    float(os.getenv("K", "d"))（后者取内层 getenv 的字符串默认）。
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        name = _call_func_name(sub)
        if name not in _ENV_FUNCS or not sub.args:
            continue
        key_node = sub.args[0]
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue
        default_node = sub.args[1] if len(sub.args) > 1 else None
        return key_node.value, default_node, _ENV_FUNCS[name]
    return None


def _render_default(default_node, kind: str) -> str:
    """把默认值 AST 节点渲染为 .env 文本（bool 小写；str 原样；数值原样）。"""
    if default_node is None:
        return ""
    if isinstance(default_node, ast.Constant):
        v = default_node.value
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return ""
        return str(v)
    # 非常量默认（如表达式）——回退空串，交由代码内默认生效
    return ""


def _preceding_comments(lines, lineno: int):
    """抓取字段定义行上方连续的 # 注释行（机械提取 config.py 内联文档）。"""
    out = []
    i = lineno - 2  # 上一行（0-based）
    while i >= 0:
        s = lines[i].strip()
        if s.startswith("#"):
            out.append(s)
            i -= 1
        else:
            break
    return list(reversed(out))


def _extract_fields():
    """AST 解析 Settings 类，返回 field_name → (env_key, default_text, kind, comments)。"""
    with open(CONFIG_PY, encoding="utf-8-sig") as fh:
        source = fh.read()
    lines = source.splitlines()
    tree = ast.parse(source, filename=CONFIG_PY)

    settings_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            settings_cls = node
            break
    if settings_cls is None:
        raise SystemExit("[gen_env_example] 未在 config.py 找到 Settings 类")

    fields = {}
    for stmt in settings_cls.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        fname = stmt.target.id
        found = _find_env_call(stmt.value) if stmt.value is not None else None
        if not found:
            continue  # 无 env 支撑（纯热更新字段）——不属于 .env 配置面
        env_key, default_node, kind = found
        fields[fname] = (
            env_key,
            _render_default(default_node, kind),
            kind,
            _preceding_comments(lines, stmt.lineno),
        )
    return fields


def _load_groups():
    """从 config 导入 SETTINGS_GROUPS（分组顺序的单一事实源）。"""
    from src.video_agent.config import SETTINGS_GROUPS
    return SETTINGS_GROUPS


def build_content() -> str:
    """组装 .env.example 全文（确定性输出：按 SETTINGS_GROUPS 顺序 + 组内字段序）。"""
    fields = _extract_fields()
    groups = _load_groups()

    # field → group 反查；未被任何组收录的 env 字段归入末尾 misc 组（防遗漏）
    grouped = set()
    out = [_PREAMBLE]

    # 必填第三方凭据（激活态空值）：cp .env.example .env 后即为待填项，
    # 与注释态运行参数区分（无代码默认值，不填则对应供应商不可用）
    out.append("\n# ---------- credentials：必填第三方凭据（激活态，无代码默认值） ----------")
    out.append("# 以下键无代码默认值，须填入实际凭据方可启用对应供应商；")
    out.append("# 敏感凭据亦可改放 API/.env（勿提交），进程环境变量与 API/.env 取第一个非空值。")
    for _key, _desc in _REQUIRED_ACTIVE_KEYS:
        out.append(f"# {_desc}")
        out.append(f"{_key}=")

    for gname, gfields in groups.items():
        title = _GROUP_TITLES.get(gname, gname)
        block = []
        for fname in gfields:
            if fname not in fields:
                continue  # 该字段无 env 支撑（如 skills_disabled），跳过
            grouped.add(fname)
            env_key, default_text, _kind, comments = fields[fname]
            for c in comments:
                block.append(c)
            block.append(f"# {env_key}={default_text}")
        if block:
            out.append(f"\n# ---------- {gname}：{title} ----------")
            out.extend(block)

    # 兜底：有 env 但未归入任何组的字段（正常为空；防分组表漏项导致静默丢失）
    misc = [f for f in fields if f not in grouped]
    if misc:
        out.append("\n# ---------- misc：未分组 ----------")
        for fname in misc:
            env_key, default_text, _kind, comments = fields[fname]
            for c in comments:
                out.append(c)
            out.append(f"# {env_key}={default_text}")

    return "\n".join(out) + "\n"


def main() -> int:
    content = build_content()
    if "--check" in sys.argv:
        existing = ""
        if os.path.exists(ENV_EXAMPLE):
            with open(ENV_EXAMPLE, encoding="utf-8") as fh:
                existing = fh.read()
        if existing != content:
            print("[gen_env_example] FAIL: .env.example 与 config.Settings 不同步；"
                  "请重跑 python scripts/gen_env_example.py")
            return 1
        print("[gen_env_example] PASS: .env.example 与 config.Settings 同步")
        return 0
    with open(ENV_EXAMPLE, "w", encoding="utf-8") as fh:
        fh.write(content)
    # 从源 fields 计数（口径准确）：Settings 派生的 env 键 + 必填激活态凭据键；
    # 原从渲染文本反推（content.count("\n# ") - ...）会把说明性注释行误计/漏计
    n_keys = len(_extract_fields()) + len(_REQUIRED_ACTIVE_KEYS)
    print(f"[gen_env_example] 已生成 {os.path.relpath(ENV_EXAMPLE, ROOT)}"
          f"（{max(0, n_keys)} 条 env 键，源自 config.Settings + 必填凭据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
