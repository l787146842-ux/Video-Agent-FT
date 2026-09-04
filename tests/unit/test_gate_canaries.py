# -*- coding: utf-8 -*-
"""整改批 1.4：治理门禁 canary 制度化（acceptance.py GATES 全部道双向可失败性）。

元教训：恒真基线/恒真门禁（永不失败）比缺门禁更危险——批次 1.1 的 scaffold
与 FRONTEND_OVER_BASELINE 动态自算事故同构。本文件为 GATES 表每道门禁
各写「故意违规 → 非 0 + 干净语料 → 0」双向断言：违规侧证明门禁真的会咬人，
干净侧证明不反噬。扫描面一律 monkeypatch 指向 tmp_path，不触碰真实仓库。

退役编排符号（check_legacy_orchestration FORBIDDEN 清单）在本文件内一律
运行时拼接（如 "Flow"+"GateSet"），防本门禁自身扫描命中本文件。
"""
import json
import re
import sys
from pathlib import Path

import pytest

# ---------- 门禁表完整性（防静默掉闸） ----------

_EXPECTED_GATE_NAMES = [
    "contract",
    "semantic_colors", "func_imports", "category_keys",
    "legacy_orchestration", "web_chat_bypass", "fc_tool_name_literals",
    "layer_imports", "ref_integrity", "prompt_literals",
    # 批 4 · 漂移 lint（V3-3 收窄口径）：Skill 章节锚点存在性
    "skill_anchor_lint",
]

# I-4 修复：覆盖率关卡从 GATES 移到 RATCHETS（后置断言，读 SUITES 本轮新鲜产物）
_EXPECTED_RATCHET_NAMES = [
    "cov_ratchet", "fe_cov_ratchet",
]


def test_acceptance_gates_table_complete():
    """GATES 表门禁一个不少（掉闸 = 治理失明）。"""
    from scripts.acceptance import GATES
    assert [name for name, _ in GATES] == _EXPECTED_GATE_NAMES


def test_acceptance_ratchets_table_complete():
    """RATCHETS 表覆盖率后置断言一个不少（I-4 时序修复）。"""
    from scripts.acceptance import RATCHETS
    assert [name for name, _ in RATCHETS] == _EXPECTED_RATCHET_NAMES


# ---------- 1) contract：gen_api_types --check ----------

def test_canary_contract_drift_fails(monkeypatch, tmp_path):
    from scripts.gen_api_types import main
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])
    stale = tmp_path / "api.generated.ts"
    stale.write_text("// stale content\n", encoding="utf-8")
    assert main(out_path=str(stale)) == 1


def test_canary_contract_consistent_passes(monkeypatch):
    from scripts.gen_api_types import main, OUT_PATH
    monkeypatch.setattr(sys, "argv", ["gen_api_types.py", "--check"])
    assert main(out_path=OUT_PATH) == 0


# ---------- 2) prompt_budget 已随 C1a 裁决 2026-08-31 退役删除（组5） ----------


# ---------- 3/4) file_lines 后端档 + 前端档 ----------

def test_canary_file_lines_oversize_fails(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.py").write_text("x = 1\n" * (gate.MAX_LINES + 1), encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SRC", src)
    assert gate.main() == 1


def test_canary_file_lines_clean_passes(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    src = tmp_path / "src"
    src.mkdir()
    (src / "small.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SRC", src)
    assert gate.main() == 0


def test_canary_file_lines_frontend_oversize_fails(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "big.tsx").write_text("// x\n" * (gate.FRONTEND_MAX_LINES + 1),
                                 encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.run_frontend() == 1


def test_canary_file_lines_frontend_clean_passes(tmp_path, monkeypatch):
    import scripts.check_file_lines as gate
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "small.tsx").write_text("// x\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.run_frontend() == 0


# ---------- 5) semantic_colors ----------

def _colors_scaffold(tmp_path, monkeypatch):
    import scripts.check_semantic_colors as gate
    styles = tmp_path / "styles"
    styles.mkdir()
    monkeypatch.setattr(gate, "STYLES", styles)
    monkeypatch.setattr(gate, "WHITELIST", {})
    monkeypatch.setattr(gate, "TOTAL_BASELINE", 0)
    monkeypatch.setattr(gate, "FONT_SIZE_WHITELIST", {})
    monkeypatch.setattr(gate, "FONT_SIZE_TOTAL_BASELINE", 0)
    monkeypatch.setattr(gate, "Z_INDEX_WHITELIST", {})
    monkeypatch.setattr(gate, "Z_INDEX_TOTAL_BASELINE", 0)
    return gate, styles


def test_canary_semantic_colors_hardcode_fails(tmp_path, monkeypatch):
    gate, styles = _colors_scaffold(tmp_path, monkeypatch)
    (styles / "rogue.css").write_text(".a { color: #ff0000; }\n", encoding="utf-8")
    assert gate.main() == 1


def test_canary_semantic_colors_token_passes(tmp_path, monkeypatch):
    gate, styles = _colors_scaffold(tmp_path, monkeypatch)
    (styles / "clean.css").write_text(
        ".a { color: var(--color-danger); }\n", encoding="utf-8")
    assert gate.main() == 0


# ---------- 6) func_imports ----------

def _func_imports_scaffold(tmp_path, monkeypatch, py_text, baseline=""):
    import scripts.check_func_imports as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text(py_text, encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text(baseline, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", str(tmp_path))
    monkeypatch.setattr(gate, "BASELINE", str(base))
    monkeypatch.setattr(sys, "argv", ["check_func_imports.py"])
    return gate


def test_canary_func_imports_new_hit_fails(tmp_path, monkeypatch):
    gate = _func_imports_scaffold(
        tmp_path, monkeypatch, "def f():\n    import os\n    return os\n")
    assert gate.main() == 1


def test_canary_func_imports_top_level_passes(tmp_path, monkeypatch):
    gate = _func_imports_scaffold(
        tmp_path, monkeypatch, "import os\n\ndef f():\n    return os\n")
    assert gate.main() == 0


# ---------- 8) category_keys ----------

def test_canary_category_keys_literal_fails(tmp_path, monkeypatch):
    import scripts.check_category_keys as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text('x = "keyElements"\n', encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIR", pkg)
    assert gate.main() == 1


def test_canary_category_keys_constant_passes(tmp_path, monkeypatch):
    import scripts.check_category_keys as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("x = CAT_KEY_ELEMENTS\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIR", pkg)
    assert gate.main() == 0


def test_canary_category_keys_missing_scan_dir_fail_closed(tmp_path, monkeypatch):
    """S5: 后端扫描目录不存在 = 扫描面失效 → 非 0（不得当作「没硬编码」）。"""
    import scripts.check_category_keys as gate
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIR", tmp_path / "src" / "video_agent")
    assert not gate.SCAN_DIR.exists()
    assert gate.main() == 1


# ---------- 9) legacy_orchestration（退役符号运行时拼接） ----------

def test_canary_legacy_orchestration_revival_fails(tmp_path, monkeypatch):
    import scripts.check_legacy_orchestration as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    symbol = "Flow" + "GateSet"  # 运行时拼接，防本文件自身被门禁命中
    (pkg / "bad.py").write_text(f"x = '{symbol}'\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ["src/video_agent"])
    assert gate.main() == 1


def test_canary_legacy_orchestration_clean_passes(tmp_path, monkeypatch):
    import scripts.check_legacy_orchestration as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    (pkg / "ok.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", ["src/video_agent"])
    assert gate.main() == 0


# ---------- 9b) web_chat_bypass（I-2：web 层禁直接构造 *ChatAdapter 旁路） ----------

def _web_chat_scaffold(tmp_path, monkeypatch, py_text):
    import scripts.check_web_chat_bypass as gate
    web = tmp_path / "src" / "video_agent" / "web"
    web.mkdir(parents=True)
    (web / "mod.py").write_text(py_text, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "WEB_DIR", web)
    monkeypatch.setattr(gate, "WHITELIST", set())
    return gate


def test_canary_web_chat_bypass_direct_construction_fails(tmp_path, monkeypatch):
    """web 层直接构造具体 *ChatAdapter（旁路 Planner）→ 非 0（门禁会咬人）。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter\n"
        "def f():\n"
        "    return OpenAICompatChatAdapter(base_url='u', api_key='k', model='m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_injected_adapter_passes(tmp_path, monkeypatch):
    """正当工具性调用（history_compact 同形）：接收上游传入 adapter 调 .chat()，
    自身不构造 adapter（小写属性调用不命中）→ 0（不反噬）。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "async def f(adapter):\n"
        "    return await adapter.chat([{'role': 'user', 'content': 'x'}])\n")
    assert gate.main() == 0


# ---- 9b-2) S6 名字后缀判定→导入符号表判定（别名漏报 + 工厂方法误报） ----

def test_canary_web_chat_bypass_alias_import_construction_fails(tmp_path, monkeypatch):
    """S6: `import ... as A` 别名构造逃逸（后缀匹配对别名全盲）→ 非 0。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters.openai_compat import "
        "OpenAICompatChatAdapter as OCA\n"
        "def f():\n"
        "    return OCA(base_url='u', api_key='k', model='m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_module_attr_construction_fails(tmp_path, monkeypatch):
    """S6: `mod.XChatAdapter(...)`（value 形如模块名）同样命中。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters import openai_compat\n"
        "def f():\n"
        "    return openai_compat.OpenAICompatChatAdapter(model='m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_assignment_alias_construction_fails(tmp_path, monkeypatch):
    """S6: 赋值别名 `_A = XChatAdapter` 后 `_A(...)` 构造 → 非 0（传递闭包）。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter\n"
        "_A = OpenAICompatChatAdapter\n"
        "def f():\n"
        "    return _A(model='m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_getattr_dynamic_construction_fails(tmp_path, monkeypatch):
    """S6: `getattr(mod, \"...ChatAdapter\")(...)` 动态构造逃逸 → 非 0。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "import importlib\n"
        "def f():\n"
        "    mod = importlib.import_module('src.video_agent.adapters.openai_compat')\n"
        "    cls = getattr(mod, 'OpenAICompatChatAdapter')\n"
        "    return getattr(mod, 'OpenAICompatChatAdapter')(model='m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_local_class_construction_fails(tmp_path, monkeypatch):
    """S6: web 层自定义 *ChatAdapter 类并构造（不经 factory）→ 非 0。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "class RogueChatAdapter:\n"
        "    def __init__(self, model):\n"
        "        self.model = model\n"
        "def f():\n"
        "    return RogueChatAdapter('m')\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_factory_method_call_passes(tmp_path, monkeypatch):
    """S6 PASS 侧不反噬：`factory.buildChatAdapter()` / `getChatAdapter()` 是工厂方法
    调用（返回 adapter，非直接构造），attr 不在导入符号表 → 0。

    旧的 endswith(\"ChatAdapter\") 后缀匹配会把这两个调用误报成旁路。
    """
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters.factory import AdapterFactory\n"
        "def f(factory):\n"
        "    a = factory.buildChatAdapter('m')\n"
        "    b = factory.getChatAdapter()\n"
        "    c = AdapterFactory().create_chat_adapter('m')\n"
        "    return a, b, c\n")
    assert gate.main() == 0


def test_canary_web_chat_bypass_annotation_and_cast_passes(tmp_path, monkeypatch):
    """S6 PASS 侧不反噬：仅用作类型注解 / cast 参数（非构造调用）→ 0。

    对齐真实代码：web/chat_service.py、web/chat_opening.py 均仅将
    BaseChatAdapter 用于 `Optional[BaseChatAdapter]` 类型注解。
    """
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from typing import Optional, cast\n"
        "from src.video_agent.adapters.base_chat import BaseChatAdapter\n"
        "def f(body) -> Optional[BaseChatAdapter]:\n"
        "    return cast(BaseChatAdapter, body.get('adapter'))\n")
    assert gate.main() == 0


# ---- 9b-3) S5 fail-closed：「扫不动」不得当作「没问题」 ----

def test_canary_web_chat_bypass_syntax_error_fail_closed(tmp_path, monkeypatch):
    """S5: 语法解析失败必须计违规（旧行为：except (OSError, SyntaxError) continue）。"""
    gate = _web_chat_scaffold(tmp_path, monkeypatch, "def f(:\n    pass\n")
    assert gate.main() == 1


def test_canary_web_chat_bypass_unreadable_file_fail_closed(tmp_path, monkeypatch):
    """S5: 读不动的路径（名为 *.py 的目录）必须计违规，不得静默跳过。"""
    gate = _web_chat_scaffold(tmp_path, monkeypatch, "X = 1\n")
    (gate.WEB_DIR / "unreadable.py").mkdir()
    assert gate.main() == 1


def test_canary_web_chat_bypass_missing_web_dir_fail_closed(tmp_path, monkeypatch):
    """S5: 声明的扫描目录（web/）不存在 = 扫描面失效 → 非 0。"""
    import scripts.check_web_chat_bypass as gate
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "WEB_DIR", tmp_path / "src" / "video_agent" / "web")
    monkeypatch.setattr(gate, "WHITELIST", set())
    assert not gate.WEB_DIR.exists()
    assert gate.main() == 1


def test_canary_web_chat_bypass_whitelist_still_honoured(tmp_path, monkeypatch):
    """WHITELIST 语义保留：登记的相对路径仍豁免 → 0（修复不改变既有豁免面）。"""
    gate = _web_chat_scaffold(
        tmp_path, monkeypatch,
        "from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter\n"
        "def f():\n"
        "    return OpenAICompatChatAdapter(model='m')\n")
    monkeypatch.setattr(gate, "WHITELIST",
                        {"src/video_agent/web/mod.py"})
    assert gate.main() == 0


# ---------- 9c) fc_tool_name_literals（I-3：调度器禁硬编码 provider 工具名） ----------

def _fc_tool_name_scaffold(tmp_path, monkeypatch, runner_text):
    import scripts.check_fc_tool_name_literals as gate
    tools = tmp_path / "src" / "video_agent" / "tools"
    tools.mkdir(parents=True)
    # 事实源桩：声明 provider_kind 的工具类（与真实工具声明同形）
    (tools / "gen.py").write_text(
        "class ImageGenerateTool:\n"
        "    name = \"image_generate\"\n"
        "    provider_kind = \"image\"\n",
        encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(runner_text, encoding="utf-8")
    monkeypatch.setattr(gate, "TOOLS_DIR", tools)
    monkeypatch.setattr(gate, "RUNNER", runner)
    return gate


def test_canary_fc_tool_name_literal_fails(tmp_path, monkeypatch):
    """调度器对 provider 工具名写 if 特例分支（字符串常量）→ 非 0（会咬人）。"""
    gate = _fc_tool_name_scaffold(
        tmp_path, monkeypatch,
        "def execute(name):\n"
        "    if name == \"image_generate\":\n"
        "        return None\n")
    assert gate.main() == 1


def test_canary_fc_tool_name_declaration_driven_passes(tmp_path, monkeypatch):
    """声明驱动：调度器只在注释里提工具名（AST 忽略注释）、无字符串常量→ 0。"""
    gate = _fc_tool_name_scaffold(
        tmp_path, monkeypatch,
        "def execute(name):\n"
        "    # 消除 image_generate / generate_video 特例，改走声明分派\n"
        "    return provider_injection.inject(name)\n")
    assert gate.main() == 0


# ---------- 10) layer_imports（R-8 裁决校正：层间导入方向闸） ----------

def _layer_imports_scaffold(tmp_path, monkeypatch):
    """layer_imports 闸脚手架：ROOT 指向 tmp，基线/放行清空。"""
    import scripts.check_layer_imports as gate
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "R2_BASELINE", frozenset())
    monkeypatch.setattr(gate, "R3_ALLOWED_CORE_MODULES", frozenset())
    return gate


def test_canary_layer_imports_core_to_web_fails(tmp_path, monkeypatch):
    """R1: core/tools → web 禁止（故意违规 → 非 0）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "tools"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from src.video_agent.web.skill_docs import list_skill_docs\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/tools",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_core_to_adapters_fails(tmp_path, monkeypatch):
    """R2: core → adapters 新增边禁止（基线外 → 非 0）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "core"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from src.video_agent.adapters.factory import AdapterFactory\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ("src/video_agent/core",))
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_adapters_to_core_impl_fails(tmp_path, monkeypatch):
    """R3: adapters → core 具体实现禁止（放行列表外 → 非 0）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "adapters"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from src.video_agent.core.agent_loop import run_agent_loop\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ("src/video_agent/adapters",))
    assert gate.main() == 1


def test_canary_layer_imports_clean_passes(tmp_path, monkeypatch):
    """干净语料：adapters → utils 放行 + core/tools 无反向依赖 → 0。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    # tools 干净
    tools = tmp_path / "src" / "video_agent" / "tools"
    tools.mkdir(parents=True)
    (tools / "ok.py").write_text(
        "from src.video_agent.storage.media_urls import resolve_injectable_url\n",
        encoding="utf-8")
    # adapters 引用 utils（合法）
    adapters = tmp_path / "src" / "video_agent" / "adapters"
    adapters.mkdir(parents=True)
    (adapters / "ok.py").write_text(
        "from src.video_agent.utils.stop_signal import is_stop_requested\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/tools",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ("src/video_agent/adapters",))
    assert gate.main() == 0


def test_canary_layer_imports_adapters_to_core_port_passes(tmp_path, monkeypatch):
    """放行：adapters → core 端口/接口模块（allowlist 内）→ 0。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "R3_ALLOWED_CORE_MODULES",
                        frozenset({"src.video_agent.core.provider_config"}))
    adapters = tmp_path / "src" / "video_agent" / "adapters"
    adapters.mkdir(parents=True)
    (adapters / "ok.py").write_text(
        "from src.video_agent.core.provider_config import CLI_PROTOCOLS\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ("src/video_agent/adapters",))
    assert gate.main() == 0


# ---- 10b) W1 相对导入失明修复：level>=1 必须还原为绝对模块名再入判定 ----

def test_canary_layer_imports_relative_import_bypass_fails(tmp_path, monkeypatch):
    """W1: `from ..adapters.factory import X` 相对导入接回 core→adapters 环边 → 非 0。

    R2_BASELINE 已收缩为空集，若相对导入被丢弃（level>=1 失明），这条环边会静默通过。
    """
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "core"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from ..adapters.factory import AdapterFactory\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ("src/video_agent/core",))
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_relative_import_deep_bypass_fails(tmp_path, monkeypatch):
    """W1: 三级上溯 `from ...web.skill_docs import x`（tools→web）同样必须命中。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "tools" / "sub"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "from ...web.skill_docs import list_skill_docs\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/tools",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_relative_import_allowlisted_passes(tmp_path, monkeypatch):
    """W1 PASS 侧不反噬：相对导入还原后落在放行面（端口模块 / utils）→ 0。

    证明还原是「还原成正确的绝对名再判定」，不是「凡相对导入一律违规」。
    """
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "R3_ALLOWED_CORE_MODULES",
                        frozenset({"src.video_agent.core.chat_port"}))
    adapters = tmp_path / "src" / "video_agent" / "adapters"
    adapters.mkdir(parents=True)
    (adapters / "ok_port.py").write_text(
        "from ..core.chat_port import ChatResponse\n", encoding="utf-8")
    (adapters / "ok_utils.py").write_text(
        "from ..utils.stop_signal import is_stop_requested\n", encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ("src/video_agent/adapters",))
    assert gate.main() == 0


# ---- 10c) S5 fail-closed：「扫不动」不得当作「没问题」 ----

def test_canary_layer_imports_syntax_error_fail_closed(tmp_path, monkeypatch):
    """S5: 语法解析失败的文件必须计违规（旧行为：except 静默跳过 → 假 PASS）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "core"
    pkg.mkdir(parents=True)
    (pkg / "broken_syntax.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/core",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_unreadable_file_fail_closed(tmp_path, monkeypatch):
    """S5: 读不动的路径（此处为名为 *.py 的目录）必须计违规，不得静默跳过。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "core"
    pkg.mkdir(parents=True)
    (pkg / "unreadable.py").mkdir()
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/core",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_missing_scan_dir_fail_closed(tmp_path, monkeypatch):
    """S5: 声明的扫描目录不存在 = 扫描面失效 → 非 0（不得当作合规）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ("src/video_agent/ghost_layer",))
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 1


def test_canary_layer_imports_fail_closed_clean_surface_passes(tmp_path, monkeypatch):
    """S5 PASS 侧不反噬：扫描面完好且语料干净 → 0（fail-closed 不误伤）。"""
    gate = _layer_imports_scaffold(tmp_path, monkeypatch)
    pkg = tmp_path / "src" / "video_agent" / "core"
    pkg.mkdir(parents=True)
    (pkg / "ok.py").write_text(
        "from ..utils.stop_signal import is_stop_requested\n", encoding="utf-8")
    monkeypatch.setattr(gate, "R1_SCAN_DIRS", ())
    monkeypatch.setattr(gate, "R2_SCAN_DIRS", ("src/video_agent/core",))
    monkeypatch.setattr(gate, "R3_SCAN_DIRS", ())
    assert gate.main() == 0


# ---------- 11) ref_integrity（doc_pointers + arch_anchors 合并） ----------
def _doc_pointers_scaffold(tmp_path, monkeypatch):
    import scripts.check_doc_pointers as gate
    pkg = tmp_path / "src" / "video_agent"
    pkg.mkdir(parents=True)
    # 锚点布局：合并后 main() 含宪法锚点校验，脚手架锚点指向 tmp 内真文件，
    # 防真实 ANCHORS 在 tmp ROOT 下恒失败（防静默掉闸的双向可失败性不变）。
    (pkg / "anchor.py").write_text("AnchorSym = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    # 基线数字镜像锁已随 2026-09-02「治理闸机减负」裁决解除，
    # tmp 宪法仅需文件地图空块供 check_arch_map 扫描。
    (tmp_path / "ARCHITECTURE_RULES.md").write_text(
        "## 文件地图\n```\n```\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "ADR_DIR", tmp_path / "docs" / "adr")
    monkeypatch.setattr(gate, "ARCH_RULES", tmp_path / "ARCHITECTURE_RULES.md")
    monkeypatch.setattr(gate, "PKG", pkg)
    monkeypatch.setattr(gate, "ANCHORS",
                        [("Rule1", "src/video_agent/anchor.py", "AnchorSym")])
    return gate, pkg


def test_canary_doc_pointers_dead_pointer_fails(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# 参考 core/ghost_module.py 实现\nx = 1\n",
                              encoding="utf-8")
    assert gate.main() == 1


def test_canary_doc_pointers_clean_passes(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 0


def test_canary_ref_integrity_anchor_missing_fails(tmp_path, monkeypatch):
    """宪法锚点合并后仍双向可失败：承重路径缺失即漂移。"""
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gate, "ANCHORS", [("Rule1", "src/video_agent/core/ghost.py", "Ghost")])
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 1


def test_canary_ref_integrity_anchor_symbol_missing_fails(tmp_path, monkeypatch):
    """半漂移（文件在、承重符号搬走）必须命中。"""
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "moved.py").write_text("OtherSym = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        gate, "ANCHORS", [("Rule1", "src/video_agent/moved.py", "AnchorSym")])
    assert gate.main() == 1


def test_canary_ref_integrity_anchor_intact_passes(tmp_path, monkeypatch):
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    assert gate.main() == 0


def test_canary_gov_script_pointer_missing_fails(tmp_path, monkeypatch):
    """Q27 治理防腐：治理文档提及的闸机脚本已删 → 漂移命中。"""
    gate, pkg = _doc_pointers_scaffold(tmp_path, monkeypatch)
    (pkg / "a.py").write_text("# plain\nx = 1\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "| 1 | 闸机 | 实现参照 scripts/check_ghost_gate.py |\n",
        encoding="utf-8")
    assert gate.main() == 1


# ---------- 11b) prompt_literals（R-4：A3 硬编码 prose 完整性闸） ----------

def _prompt_literals_scaffold(tmp_path, monkeypatch, py_text):
    import scripts.check_prompt_literals as gate
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "mod.py").write_text(py_text, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", [scan])
    return gate


def test_canary_prompt_literals_hardcoded_prose_fails(tmp_path, monkeypatch):
    """模块级硬编码 CJK prose（≥8 字、未登记）→ 非 0（门禁会咬人）。"""
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch,
        "MSG = \"\u8fd9\u662f\u4e00\u6bb5\u672a\u5916\u7f6e\u7684\u786c\u7f16\u7801\u63d0\u793a\u8bcd\u6b63\u6587\"\n")
    assert gate.main() == 1


def test_canary_prompt_literals_handler_data_passes(tmp_path, monkeypatch):
    """函数体内字符串（运行时 handler 数据，结构豁免）→ 0（不反噬）。"""
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch,
        "def f():\n    return \"\u8fd9\u662f\u4e00\u6bb5\u672a\u5916\u7f6e\u7684\u786c\u7f16\u7801\u63d0\u793a\u8bcd\u6b63\u6587\"\n")
    assert gate.main() == 0


# ---- 11b-2) W4 双向前缀漏报修复：完整字面量精确相等，前缀项仅单向且需显式登记 ----

# 登记面采用 monkeypatch 注入，使断言钉在**判定逻辑**上而不随真实登记表漂移。
_W4_REGISTERED = "已登记为结构化数据的一段完整提示词正文"


def test_canary_prompt_literals_truncated_declared_literal_fails(tmp_path, monkeypatch):
    """W4: 登记项的**真前缀截短串**须 FAIL（旧双向 startswith 会把它豁免）。"""
    truncated = _W4_REGISTERED[:10]  # 10 个 CJK 字，过 _MIN_LEN 门槛
    assert len(truncated) >= 8 and truncated != _W4_REGISTERED
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch, 'MSG = "%s"\n' % truncated)
    monkeypatch.setattr(gate, "_DECLARED_SET", {_W4_REGISTERED})
    monkeypatch.setattr(gate, "_DECLARED_PREFIX_SET", set())
    assert gate.main() == 1


def test_canary_prompt_literals_novel_prose_sharing_prefix_fails(tmp_path, monkeypatch):
    """W4: 以登记项开头的全新长 prose 不得整条豁免（反向/同向前缀放宽已砍）。"""
    novel = _W4_REGISTERED + "，后面接的是一整段全新的产品文案正文应当外置到提示词目录"
    assert novel.startswith(_W4_REGISTERED)
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch, 'MSG = "%s"\n' % novel)
    monkeypatch.setattr(gate, "_DECLARED_SET", {_W4_REGISTERED})
    monkeypatch.setattr(gate, "_DECLARED_PREFIX_SET", set())
    assert gate.main() == 1


def test_canary_prompt_literals_exact_declared_passes(tmp_path, monkeypatch):
    """W4 PASS 侧不反噬：完整字面量精确相等 → 0（登记面仍是合法豁免口）。"""
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch, 'MSG = "%s"\n' % _W4_REGISTERED)
    monkeypatch.setattr(gate, "_DECLARED_SET", {_W4_REGISTERED})
    monkeypatch.setattr(gate, "_DECLARED_PREFIX_SET", set())
    assert gate.main() == 0


def test_canary_prompt_literals_explicit_prefix_entry_passes(tmp_path, monkeypatch):
    """W4 PASS 侧不反噬：显式登记的前缀项允许单向 startswith（长多行模板豁免）→ 0。"""
    prefix = "你是一个文档格式化专家"
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch,
        'TMPL = "%s\\n后续多行模板正文与输出要求"\n' % prefix)
    monkeypatch.setattr(gate, "_DECLARED_SET", set())
    monkeypatch.setattr(gate, "_DECLARED_PREFIX_SET", {prefix})
    assert gate.main() == 0


# ---- 11b-3) S5 fail-closed：「扫不动」不得当作「没问题」 ----

def test_canary_prompt_literals_syntax_error_fail_closed(tmp_path, monkeypatch):
    """S5: 语法解析失败必须计违规（旧行为：except SyntaxError return [] → 假 PASS）。"""
    gate = _prompt_literals_scaffold(
        tmp_path, monkeypatch, "def f(:\n    pass\n")
    assert gate.main() == 1


def test_canary_prompt_literals_unreadable_file_fail_closed(tmp_path, monkeypatch):
    """S5: 读不动的路径（名为 *.py 的目录）必须计违规，不得静默跳过。"""
    gate = _prompt_literals_scaffold(tmp_path, monkeypatch, "X = 1\n")
    (gate.SCAN_DIRS[0] / "unreadable.py").mkdir()
    assert gate.main() == 1


def test_canary_prompt_literals_missing_scan_dir_fail_closed(tmp_path, monkeypatch):
    """S5: 声明的扫描目录不存在 = 扫描面失效 → 非 0（不得静默 continue）。"""
    gate = _prompt_literals_scaffold(tmp_path, monkeypatch, "X = 1\n")
    monkeypatch.setattr(gate, "SCAN_DIRS", [tmp_path / "ghost_scan_dir"])
    assert gate.main() == 1


def test_canary_prompt_literals_fail_closed_clean_surface_passes(tmp_path, monkeypatch):
    """S5 PASS 侧不反噬：扫描面完好且无未登记 prose → 0。"""
    gate = _prompt_literals_scaffold(tmp_path, monkeypatch, "X = 1\n")
    assert gate.main() == 0


# ---------- 11c) ci.yml ↔ acceptance.GATES 名集对账（任务26：自我声明与事实双向钉死） ----------
# 机械身份 = 被调用的脚本路径（GATES 的 name 是标签、ci step 的 name 是自由散文，
# 二者不可直接比；唯一稳定可比的是两边都跑的 scripts/*.py）。
# 正向：GATES 登记的脚本必须全部在 ci.yml 接线（漏接 = 自我声明与事实脱钩）。
# 反向：ci.yml 调用的脚本必须全部在 acceptance.py 登记（GATES 或 RATCHETS/EVAL/
#       EVAL_WARN/E2E 等已知非-GATES 组件），否则为孤儿 step（接了线却未登记）。

_CI_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _extract_script(cmd):
    """从命令列表中取出被调用的 scripts/*.py（无则 None）。"""
    for el in cmd:
        if isinstance(el, str) and el.startswith("scripts/") and el.endswith(".py"):
            return el
    return None


def _scripts_from_tables(tables):
    """从多个 (name, cmd) 表中收集全部 scripts/*.py 路径。"""
    out = set()
    for table in tables:
        for _name, cmd in table:
            script = _extract_script(cmd)
            if script:
                out.add(script)
    return out


def _parse_ci_scripts(ci_text):
    """从 ci.yml 非注释行提取所有 scripts/*.py 调用。"""
    found = set()
    for line in ci_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        found.update(re.findall(r"scripts/[A-Za-z0-9_./-]+\.py", line))
    return found


def _reconcile(ci_scripts, gate_scripts, known_other_scripts):
    """返回 (missing_in_ci, orphan_in_ci)：漏接的 gate / 未登记的孤儿 step。"""
    missing_in_ci = gate_scripts - ci_scripts
    orphan_in_ci = ci_scripts - gate_scripts - known_other_scripts
    return missing_in_ci, orphan_in_ci


def _real_reconcile_inputs():
    from scripts import acceptance
    gate_scripts = _scripts_from_tables([acceptance.GATES])
    other_scripts = _scripts_from_tables([
        acceptance.RATCHETS, acceptance.EVAL,
        acceptance.EVAL_WARN, acceptance.E2E,
    ])
    ci_scripts = _parse_ci_scripts(_CI_PATH.read_text(encoding="utf-8"))
    return ci_scripts, gate_scripts, other_scripts


def test_canary_ci_gates_reconcile_real_consistent():
    """正例：真实 ci.yml ↔ acceptance.GATES 名集一致（无漏接、无孤儿）。"""
    ci_scripts, gate_scripts, other_scripts = _real_reconcile_inputs()
    missing, orphan = _reconcile(ci_scripts, gate_scripts, other_scripts)
    assert not missing, f"GATES 登记却漏在 ci.yml 接线: {sorted(missing)}"
    assert not orphan, f"ci.yml 有 step 却未在 acceptance.py 登记: {sorted(orphan)}"


def test_canary_ci_gates_reconcile_missing_gate_fails():
    """反例（正向）：ci.yml 漏接一个已登记 gate → missing 非空（对账会咬人）。"""
    ci_scripts, gate_scripts, other_scripts = _real_reconcile_inputs()
    dropped = sorted(gate_scripts)[0]
    ci_scripts.discard(dropped)
    missing, _orphan = _reconcile(ci_scripts, gate_scripts, other_scripts)
    assert dropped in missing


def test_canary_ci_gates_reconcile_orphan_step_fails():
    """反例（反向）：ci.yml 多接一个未登记脚本 → orphan 非空（对账会咬人）。"""
    ci_scripts, gate_scripts, other_scripts = _real_reconcile_inputs()
    ci_scripts.add("scripts/check_ghost_gate.py")
    _missing, orphan = _reconcile(ci_scripts, gate_scripts, other_scripts)
    assert "scripts/check_ghost_gate.py" in orphan


# ---------- 12/13) cov_ratchet / fe_cov_ratchet（固定容差地板） ----------

def _write_cov_xml(path: Path, line_rate: float):
    path.write_text(f'<coverage line-rate="{line_rate}" version="1"/>',
                    encoding="utf-8")


def test_canary_cov_ratchet_below_floor_fails(tmp_path, monkeypatch):
    """低于固定地板 → FAIL（地板真的会咬人）。"""
    import scripts.check_cov_ratchet as gate
    xml = tmp_path / "coverage.xml"
    _write_cov_xml(xml, (gate.COVERAGE_FLOOR - 5) / 100)
    monkeypatch.setattr(sys, "argv",
                        ["check_cov_ratchet.py", "--cov-xml", str(xml)])
    assert gate.main() == 1


def test_canary_cov_ratchet_above_floor_passes(tmp_path, monkeypatch):
    """高于固定地板 → PASS（不反噬）。"""
    import scripts.check_cov_ratchet as gate
    xml = tmp_path / "coverage.xml"
    _write_cov_xml(xml, (gate.COVERAGE_FLOOR + 5) / 100)
    monkeypatch.setattr(sys, "argv",
                        ["check_cov_ratchet.py", "--cov-xml", str(xml)])
    assert gate.main() == 0


def _write_fe_summary(path: Path, pct: float):
    path.write_text(json.dumps({"total": {"lines": {"pct": pct}}}),
                    encoding="utf-8")


def test_canary_fe_cov_ratchet_below_floor_fails(tmp_path, monkeypatch):
    import scripts.check_fe_cov_ratchet as gate
    summary = tmp_path / "coverage-summary.json"
    _write_fe_summary(summary, gate.COVERAGE_FLOOR - 5)
    monkeypatch.setattr(sys, "argv",
                        ["check_fe_cov_ratchet.py", "--summary", str(summary)])
    assert gate.main() == 1


def test_canary_fe_cov_ratchet_above_floor_passes(tmp_path, monkeypatch):
    import scripts.check_fe_cov_ratchet as gate
    summary = tmp_path / "coverage-summary.json"
    _write_fe_summary(summary, gate.COVERAGE_FLOOR + 5)
    monkeypatch.setattr(sys, "argv",
                        ["check_fe_cov_ratchet.py", "--summary", str(summary)])
    assert gate.main() == 0


def test_canary_fe_cov_ratchet_corrupted_summary_fails(tmp_path, monkeypatch,
                                                       capsys):
    """回归：损坏的 coverage-summary.json 曾让本闸误红无诊断；
    现要求损坏/缺字段一律判红并给出「重跑前端覆盖率」诊断。"""
    import scripts.check_fe_cov_ratchet as gate
    for content in ("{ not json", '{"total": {}}',
                    json.dumps({"total": {"lines": {"pct": "abc"}}})):
        summary = tmp_path / "coverage-summary.json"
        summary.write_text(content, encoding="utf-8")
        monkeypatch.setattr(sys, "argv",
                            ["check_fe_cov_ratchet.py", "--summary",
                             str(summary)])
        with pytest.raises(SystemExit):
            gate.main()
        out = capsys.readouterr().out
        assert "coverage summary file corrupted or missing" in out, "损坏产物须报明确诊断"
        assert "rerun frontend coverage" in out, "诊断须指引重跑前端覆盖率"


def test_canary_fe_cov_ratchet_nonfinite_pct_fails(tmp_path, monkeypatch,
                                                   capsys):
    """回归（任务 #5）：json.loads/float 均接受裸 Infinity/NaN，
    inf/NaN 会污染判定、null 则须归入非有效数值；
    三种产物一律判红并报「非有效数值」诊断。"""
    import scripts.check_fe_cov_ratchet as gate
    for content in ('{"total": {"lines": {"pct": Infinity}}}',
                    '{"total": {"lines": {"pct": NaN}}}',
                    '{"total": {"lines": {"pct": null}}}'):
        summary = tmp_path / "coverage-summary.json"
        summary.write_text(content, encoding="utf-8")
        monkeypatch.setattr(sys, "argv",
                            ["check_fe_cov_ratchet.py", "--summary",
                             str(summary)])
        with pytest.raises(SystemExit):
            gate.main()
        out = capsys.readouterr().out
        assert "not a valid number" in out, "Infinity/NaN/null 须报非有效数值"
        assert "rerun frontend coverage" in out, "诊断须指引重跑前端覆盖率"


# ---------- scan_skills --gate 诊断扫描（客观结构探针双向钉死） ----------
# 正文句式扫描（内容卫生/语言宣称探针）已按用户裁决 R-3 退役，
# 退出码仅由客观结构问题决定；FAIL/通过双向行为仍钉死，
# 防诊断函数自身恒真/恒假。

def _skills_gate_scaffold(tmp_path, monkeypatch, md_name, md_text):
    import scripts.scan_skills as gate
    skills = tmp_path / "data" / "skills"
    # 批 3 单一包形态：<slug>/SKILL.md；name/description 注册期必填，
    # name 取正文 H1 与显示名口径一致。
    slug = md_name[:-3] if md_name.endswith(".md") else md_name
    pkg = skills / slug
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        f"---\nname: {md_text.splitlines()[0].lstrip('# ').strip()}\n"
        f"description: 诊断扫描测试桩\n---\n" + md_text, encoding="utf-8")
    # run_gate 按 __file__ 相对定位 data/skills：指向 tmp 布局
    monkeypatch.setattr(gate, "__file__", str(tmp_path / "scripts" / "scan_skills.py"))
    return gate


def test_canary_skill_scan_broken_frontmatter_fails(tmp_path, monkeypatch):
    """结构探针：frontmatter 声明块未闭合 → 退出码 1（FAIL 路径仍会咬人）。"""
    import scripts.scan_skills as gate
    pkg = tmp_path / "data" / "skills" / "坏结构样例"
    pkg.mkdir(parents=True)
    # 首行 `---` 开栏但无收尾 `---`：split_frontmatter 报解析错误→结构 FAIL
    (pkg / "SKILL.md").write_text(
        "---\nname: 坏结构\ndescription: 未闭合的声明块\n# 正文\n",
        encoding="utf-8")
    monkeypatch.setattr(gate, "__file__",
                        str(tmp_path / "scripts" / "scan_skills.py"))
    assert gate.run_gate() == 1


def test_canary_skill_scan_clean_passes(tmp_path, monkeypatch):
    """干净仓 → 退出码 0（不反噬）；正文句式不再参与判定，
    含历史宣称句式的正文也不阻断（R-3：句式扫描退役）。"""
    gate = _skills_gate_scaffold(
        tmp_path, monkeypatch, "干净样例.md",
        "# 干净\n> 调用规则：测试\n正文遵守强制基线式表述。\n"
        "优先级最高、提示词一律英文等句式不再被扫描。\n")
    assert gate.run_gate() == 0
