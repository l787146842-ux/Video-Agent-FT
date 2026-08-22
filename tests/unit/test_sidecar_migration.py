# -*- coding: utf-8 -*-
"""任务#5：frontmatter 声明合一回归（外置 JSON sidecar 已退役删除）。

钉死：
① frontmatter 与正文分离：剥离声明块后章节解析不变；
② registry 声明唯一源 = 文档头部 frontmatter（零声明合法）；
③ 流程步骤抄本通道废除：声明 flow.steps/step_stages/dependencies
   即 fail-hard 报出（正文 planner 是唯一流程源）；
④ YAML 解析失败不静默：_parse_error 哨兵 → 体检报出；
⑤ 全量产品 frontmatter 体检零告警；阶段表 skill 感知裁剪。
"""
import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import validate_manifest_data
from src.video_agent.web.skill_docs import split_skill_sections

_DOC_WITH_FRONTMATTER = """---
flow:
  spec_gate: true
pause:
  stage_pause: true
---
skill_name: "迁移测试桩"
skill_description: "测试。"
<planner>
**全流程阶段与依赖关系：**
1. 读取并分析剧本 → **script_analyze**。
2. 组装时间线 → **video_assembler**。
</planner>
"""


def test_split_frontmatter_keeps_sections():
    """声明块剥离后正文解析不变（YAML 头不是 Skill 正文）。"""
    declaration, body, err = frontmatter.split_frontmatter(_DOC_WITH_FRONTMATTER)
    assert err == ""
    assert declaration == {
        "flow": {"spec_gate": True}, "pause": {"stage_pause": True}}
    assert "spec_gate" not in body and "<planner>" in body
    assert frontmatter.strip_frontmatter(_DOC_WITH_FRONTMATTER) == body
    assert split_skill_sections(body) == split_skill_sections(
        frontmatter.strip_frontmatter(_DOC_WITH_FRONTMATTER))
    # 无 frontmatter 文档原样返回
    declaration2, body2, err2 = frontmatter.split_frontmatter("# A\n正文")
    assert declaration2 is None and body2 == "# A\n正文" and err2 == ""


def test_load_manifest_absent_returns_none(tmp_path):
    assert frontmatter.load_manifest("不存在的桩", directory=tmp_path) is None


def test_registry_manifest_from_frontmatter():
    """registry 声明唯一源 = 文档头部 frontmatter；注入正文已剥离声明块。"""
    from src.video_agent.skill_runtime import registry

    f = sd.SKILL_DOCS_DIR / "frontmatter测试桩.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_DOC_WITH_FRONTMATTER, encoding="utf-8")
    entry = registry._load_entry("frontmatter测试桩")
    assert entry is not None
    assert entry.manifest == {
        "flow": {"spec_gate": True}, "pause": {"stage_pause": True}}
    assert "spec_gate" not in entry.content  # 注入链路不携带 YAML 头
    f.unlink()


def test_registry_zero_declaration():
    """无 frontmatter = 零声明合法（引擎零预设）。"""
    from src.video_agent.skill_runtime import registry

    f = sd.SKILL_DOCS_DIR / "零声明桩.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# 零声明\n正文", encoding="utf-8")
    entry = registry._load_entry("零声明桩")
    assert entry is not None
    assert entry.manifest is None
    f.unlink()


def test_deprecated_flow_keys_fail_hard():
    """流程步骤抄本通道废除：声明 steps/step_stages/dependencies 即报出。"""
    for key in ("steps", "step_stages", "dependencies"):
        issues = validate_manifest_data({"flow": {key: {"1": "x"}}})
        assert any("已废除" in i and key in i for i in issues), key


def test_parse_error_sentinel_fails_validation(tmp_path):
    """YAML 解析失败不静默：load_manifest 返回 _parse_error 哨兵，
    体检转为问题报出（注册期 fail-hard）。"""
    f = tmp_path / "坏声明桩.md"
    f.write_text("---\nflow: [未闭合\n---\n正文", encoding="utf-8")
    data = frontmatter.load_manifest("坏声明桩", directory=tmp_path)
    assert data and "_parse_error" in data
    issues = validate_manifest_data(data)
    assert issues and "frontmatter" in issues[0]


def test_load_manifest_decode_error_returns_parse_error(tmp_path):
    """P1-1（正确性审查）：非 UTF-8 回存的 md 不得击穿 fail-closed——
    UnicodeDecodeError 捕获后走 _parse_error 哨兵（拒注册/拒入），
    而不是返回 None 被当成「零声明合法」静默放行。"""
    f = tmp_path / "坏编码桩.md"
    # UTF-16 字节序列（记事本另存形态）：utf-8 解码必抛 UnicodeDecodeError
    f.write_bytes("---\nflow: {}\n---\n正文".encode("utf-16"))
    data = frontmatter.load_manifest("坏编码桩", directory=tmp_path)
    assert data is not None and "_parse_error" in data
    issues = validate_manifest_data(data)
    assert issues, "编码失败必须走拒注册语义，不能静默放行"


def test_bom_frontmatter_detected(tmp_path):
    """P2-2：UTF-8 BOM 不得使 frontmatter 探测静默失效（Windows
    记事本默认带 BOM）：字符串入口 lstrip + 读取 utf-8-sig 双保险。"""
    content = "\ufeff---\nflow:\n  spec_gate: true\n---\n# A\n正文"
    declaration, body, err = frontmatter.split_frontmatter(content)
    assert err == "" and declaration == {"flow": {"spec_gate": True}}
    assert body.startswith("# A")
    # 落盘带 BOM 字节：load_manifest 照常读到声明
    f = tmp_path / "BOM桩.md"
    f.write_text(content, encoding="utf-8")
    assert frontmatter.load_manifest("BOM桩", directory=tmp_path) == {
        "flow": {"spec_gate": True}}


def test_archived_migrate_script_check_still_passes():
    """P2-1：迁移脚本归档入 scripts/archive/ 后 root 解析不失效
    （parents[2]）：源目录已删 → --check 视为迁移已完成退出 0。"""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "migrate_manifests_to_frontmatter",
        root / "scripts" / "archive" / "migrate_manifests_to_frontmatter.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.main(["--check"]) == 0


def test_unknown_gate_key_rejected():
    """gates 键白名单 fail-hard：未登记的闸键拒注册（任务#5）。"""
    issues = validate_manifest_data({"gates": {"unknown_gate": True}})
    assert any("unknown_gate" in i for i in issues)
    assert validate_manifest_data(
        {"gates": {"require_subtitle": True}}) == []


def test_all_product_frontmatters_validate_clean():
    """全量盘点钉死：产品 Skill 的 frontmatter 体检零告警。"""
    for f in sorted(sd.SKILL_DOCS_DIR.glob("*.md")):
        issues = validate_manifest_data(frontmatter.load_manifest(f.stem))
        assert issues == [], f"{f.stem}: {issues}"


def test_stage_table_skill_aware_trimming():
    """阶段表 skill 感知：无 video_assembler 章节的 Skill 无组装阶段；
    spec_wizard 冻结值决定规格阶段存在性。"""
    from src.video_agent.core import pipeline_orchestrator as po

    keys = [s.key for s in po.stage_table("商品宣传短片")]
    assert "assembly" not in keys
    assert "spec" in keys
    keys2 = [s.key for s in po.stage_table("宣言式概念短片")]
    assert "assembly" in keys2
