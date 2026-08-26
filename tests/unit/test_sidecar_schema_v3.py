# -*- coding: utf-8 -*-
"""任务#34 B1：Skill 声明 schema v3 地基钉（纯增量、零行为变化）。

任务#5 frontmatter 合一后口径：声明唯一源 = 文档头部 YAML frontmatter
（sidecar 模块已退役，读写改 frontmatter，校验改 manifest_schema）。

钉死四件事：
① v3 新键（schema_version/kind/requires_inputs/language/pause_points/scripts）
   合法/非法/缺省用例（fail-closed；未声明=零预设）；
② v2 键校验语义不回归（旧口径原样保留；流程抄本三键已废除）；
③ frontmatter 读写透传 schema_version（活读不快照）；
④ migrate_manifests_v3.py 幂等迁移（临时目录，只加不删、重复运行不变）。
"""
import importlib.util
import json
from pathlib import Path

import pytest

from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime import manifest_schema as ms

_ROOT = Path(__file__).resolve().parents[2]
_mig_spec = importlib.util.spec_from_file_location(
    "migrate_manifests_v3",
    _ROOT / "scripts" / "archive" / "migrate_manifests_v3.py")
mig = importlib.util.module_from_spec(_mig_spec)
_mig_spec.loader.exec_module(mig)


# ---------- ① v3 新键：schema_version / kind ----------


@pytest.mark.parametrize("data", [
    {},                                   # 缺省 = v2 兼容，零预设
    {"schema_version": 3},
    {"schema_version": 2},
    {"kind": "pipeline"},
    {"kind": "style"},
])
def test_v3_defaults_and_valid_scalars(data):
    assert ms.validate_manifest_data(data) == []


def test_reference_kind_retired_warns_open_registration():
    """任务#8 ②：reference kind 下架——再声明输出 WARN 过渡告警
    （开放注册不拒入，降级 pipeline），而非错误级。"""
    issues = ms.validate_manifest_data({"kind": "reference"})
    errors, warnings = ms.split_issue_warnings(issues)
    assert errors == []
    assert any("reference" in w and "登记表" in w for w in warnings)


@pytest.mark.parametrize("data,keyword", [
    ({"schema_version": "3"}, "整数"),
    ({"schema_version": True}, "整数"),
    ({"schema_version": 4}, "不受支持"),
])
def test_v3_rejects_illegal_schema_version_and_kind(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


@pytest.mark.parametrize("data", [
    {"kind": "cinema"},   # 未知 kind（字符串）
    {"kind": 1},          # 未知 kind（非字符串取值）
])
def test_v3_unknown_kind_is_warn_not_error(data):
    """任务#5 B-1：kind 开放注册——未知取值降级为默认（pipeline）注入
    策略并输出 WARN，不产生错误级问题（不拒注册）。"""
    issues = ms.validate_manifest_data(data)
    errors, warnings = ms.split_issue_warnings(issues)
    assert errors == []
    assert warnings and any("降级" in w and "pipeline" in w for w in warnings)


# ---------- ① v3 新键：requires_inputs ----------


@pytest.mark.parametrize("data", [
    {"requires_inputs": [{"type": "script"}]},  # required 缺省 true
    {"requires_inputs": [
        {"type": "music", "required": False, "hint": "请上传背景音乐文件"}]},
    {"requires_inputs": []},
])
def test_v3_requires_inputs_valid(data):
    assert ms.validate_manifest_data(data) == []


@pytest.mark.parametrize("data,keyword", [
    ({"requires_inputs": {"type": "script"}}, "数组"),
    ({"requires_inputs": ["script"]}, "对象"),
    ({"requires_inputs": [{"type": "subtitle"}]}, "必须是 script/music/video/image/doc"),
    ({"requires_inputs": [{"required": True}]}, "必须是 script/music/video/image/doc"),
    ({"requires_inputs": [{"type": "script", "required": "yes"}]}, "布尔值"),
    ({"requires_inputs": [{"type": "script", "hint": ""}]}, "非空字符串"),
])
def test_v3_requires_inputs_illegal(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


# ---------- ① v3 新键：language ----------


@pytest.mark.parametrize("data", [
    {"language": {}},
    {"language": {"prompt": "zh"}},
    {"language": {"prompt": "zh", "output": "auto"}},
    {"language": {"prompt": "en", "output": "en"}},
])
def test_v3_language_valid(data):
    assert ms.validate_manifest_data(data) == []


@pytest.mark.parametrize("data,keyword", [
    ({"language": "zh"}, "对象"),
    ({"language": {"prompt": "fr"}}, "zh/en/auto"),
    ({"language": {"output": "中文"}}, "zh/en/auto"),
])
def test_v3_language_illegal(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


# ---------- ① v3 新键：pause_points ----------


@pytest.mark.parametrize("data", [
    {"pause_points": []},
    {"pause_points": [
        {"id": "spec_pause", "trigger": "spec_finalized"},
        {"id": "sb_pause", "trigger": "storyboard_structure_ready"},
        {"id": "gen_pause", "trigger": "first_generation_call"}]},
    {"pause_points": [
        {"id": "batch", "trigger": "batch_boundary", "description": "每 5 镜一停"}]},
    {"pause_points": [
        {"id": "free", "trigger": "free_text", "prose": "请确认美术方向"}]},
])
def test_v3_pause_points_valid(data):
    assert ms.validate_manifest_data(data) == []


@pytest.mark.parametrize("data,keyword", [
    ({"pause_points": {"id": "x"}}, "数组"),
    ({"pause_points": ["x"]}, "对象"),
    ({"pause_points": [{"trigger": "spec_finalized"}]}, "非空字符串"),
    ({"pause_points": [{"id": "x", "trigger": "user_confirmed"}]},
     "spec_finalized/storyboard_structure_ready"),
    ({"pause_points": [{"id": "x", "trigger": "batch_boundary"}]}, "description"),
    ({"pause_points": [{"id": "x", "trigger": "batch_boundary", "description": ""}]},
     "description"),
    ({"pause_points": [{"id": "x", "trigger": "free_text"}]}, "prose"),
    ({"pause_points": [{"id": "x", "trigger": "free_text", "prose": ""}]}, "prose"),
])
def test_v3_pause_points_illegal(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


# ---------- ① v3 新键：scripts（键声明静态校验；平台绝不自动执行，P2-4） ----------


@pytest.mark.parametrize("data", [
    {"scripts": {}},
    {"scripts": []},
    {"scripts": {"build": "render.py"}},
    {"scripts": {"build": "scripts/render.py", "lint": "tools/lint.sh"}},
])
def test_v3_scripts_valid_declaration(data):
    """键声明形状合法 = 零 issue（静态校验口径；路径存在性归
    scan_skills 资源探针 WARN 核对，schema 只管形状）。"""
    assert ms.validate_manifest_data(data) == []


@pytest.mark.parametrize("data,keyword", [
    ({"scripts": ["x"]}, "对象"),
    ({"scripts": "x"}, "对象"),
    ({"scripts": {"": "render.py"}}, "脚本名"),
    ({"scripts": {"build": ""}}, "非空字符串"),
    ({"scripts": {"build": 5}}, "非空字符串"),
    ({"scripts": {"build": "/etc/passwd"}}, "包内相对路径"),
    ({"scripts": {"build": "C:/x.py"}}, "包内相对路径"),
    ({"scripts": {"build": "../escape.py"}}, "包内相对路径"),
])
def test_v3_scripts_illegal(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


# ---------- ② v2 兼容不回归 ----------


def test_v2_full_manifest_still_passes_unchanged():
    """v2 锁源样例（与 test_sidecar_schema_v2 同源）校验语义不动；
    流程抄本三键（steps/step_stages/dependencies）已随任务#5 废除；
    僵尸键（stage_executors 等）转 WARN 过渡告警（test_zombie_step_keys 钉死）。"""
    good = {
        "flow": {
            "spec_wizard": True, "spec_gate": True, "script_required": False,
        },
        "pause": {"stage_pause": True},
    }
    assert ms.validate_manifest_data(good) == []


@pytest.mark.parametrize("data,keyword", [
    ({"flow": {"spec_wizard": "yes"}}, "布尔值"),
    ({"pause": {"stage_pause": "yes"}}, "布尔值"),
])
def test_v2_illegal_still_rejected(data, keyword):
    issues = ms.validate_manifest_data(data)
    assert issues and any(keyword in i for i in issues)


def test_v2_and_v3_keys_coexist():
    mixed = {
        "schema_version": 3,
        "kind": "pipeline",
        "flow": {"spec_wizard": True},
        "pause": {"stage_pause": True},
        "requires_inputs": [{"type": "script"}],
        "language": {"prompt": "zh", "output": "auto"},
        "pause_points": [{"id": "sb", "trigger": "storyboard_structure_ready"}],
    }
    assert ms.validate_manifest_data(mixed) == []


# ---------- ③ frontmatter 读写透传 schema_version ----------


def test_frontmatter_roundtrip_passes_through_v3_keys(tmp_path):
    payload = {
        "schema_version": 3,
        "kind": "style",
        "requires_inputs": [{"type": "script", "required": True}],
        "language": {"prompt": "zh", "output": "zh"},
        "pause_points": [{"id": "gen", "trigger": "first_generation_call"}],
        "flow": {"spec_wizard": True},
    }
    frontmatter.write_manifest("v3_probe", payload, directory=tmp_path)
    loaded = frontmatter.load_manifest("v3_probe", directory=tmp_path)
    assert loaded == payload
    assert ms.validate_manifest_data(loaded) == []


# ---------- ④ 迁移脚本幂等性（临时目录） ----------


_V2_SAMPLE = {
    "flow": {
        "script_required": True,
    },
    "pause": {"stage_pause": True},
}


def _write(dir_path: Path, name: str, data: dict) -> Path:
    f = dir_path / name
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return f


def test_migrate_data_is_pure_additive_and_idempotent():
    out = mig.migrate_data(_V2_SAMPLE)
    assert out["schema_version"] == 3
    assert out["requires_inputs"] == [{"type": "script", "required": True}]
    assert out["pause_points"] == [
        {"id": "storyboard_structure_ready", "trigger": "storyboard_structure_ready"},
        {"id": "first_generation_call", "trigger": "first_generation_call"},
    ]
    # v2 原键只加不删
    assert out["flow"]["script_required"] is True
    assert out["pause"]["stage_pause"] is True
    # 幂等：再翻一次无变化（返回 None）
    assert mig.migrate_data(out) is None
    # 迁移产物过 v3 schema
    assert ms.validate_manifest_data(out) == []


def test_migrate_skips_absent_translation_points():
    bare = {"flow": {"spec_wizard": True}}
    out = mig.migrate_data(bare)
    assert out == {"schema_version": 3, "flow": bare["flow"]}
    assert "requires_inputs" not in out and "pause_points" not in out


def test_migrate_script_cli_idempotent_on_disk(tmp_path):
    _write(tmp_path, "sample.json", _V2_SAMPLE)
    # --check：迁移前必报未迁完（退出码 1）
    assert mig.main(["--check", "--dir", str(tmp_path)]) == 1
    # --dry-run：不落盘
    assert mig.main(["--dry-run", "--dir", str(tmp_path)]) == 0
    assert "schema_version" not in json.loads(
        (tmp_path / "sample.json").read_text(encoding="utf-8"))
    # 正式迁移
    assert mig.main(["--dir", str(tmp_path)]) == 0
    first = (tmp_path / "sample.json").read_text(encoding="utf-8")
    # 重复运行：结果逐字节不变（幂等），--check 转绿
    assert mig.main(["--dir", str(tmp_path)]) == 0
    assert (tmp_path / "sample.json").read_text(encoding="utf-8") == first
    assert mig.main(["--check", "--dir", str(tmp_path)]) == 0


def test_migrate_preserves_existing_pause_points(tmp_path):
    data = {
        "schema_version": 3,
        "pause": {"stage_pause": True},
        "pause_points": [{"id": "custom", "trigger": "spec_finalized"}],
    }
    f = _write(tmp_path, "keep.json", data)
    assert mig.main(["--dir", str(tmp_path)]) == 0
    out = json.loads(f.read_text(encoding="utf-8"))
    ids = [p["id"] for p in out["pause_points"]]
    assert ids == ["custom", "storyboard_structure_ready", "first_generation_call"]
    # 已含锚点时重复运行不追加
    assert mig.main(["--check", "--dir", str(tmp_path)]) == 0


def test_migrate_bad_dir_returns_error_code(tmp_path):
    assert mig.main(["--dir", str(tmp_path / "不存在")]) == 2
