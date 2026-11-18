# -*- coding: utf-8 -*-
"""read_file / read_image 的 user-only 技能门禁（用户裁决 2026-11-12）。

口径（ARCHITECTURE_RULES §2.8）：`model_invocable=false` 的技能
- **主代理（委派深度 0）**：不得经 read_file / read_image 自行加载其任何正文
  （含 SKILL.md 与分册），错误文案与 read_skill 对齐；
- **子代理（委派深度 ≥1）**：照常可读（保留主代理把技能包路径交给子代理自读
  的供给设计）。

判据两维缺一不可：目标条目 model_invocable + 当前委派深度。
"""
import asyncio

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime.frontmatter import SKILL_DOC_NAME
from src.video_agent.tools.skill_file_tools import (
    ReadFileInput, ReadFileTool, ReadImageInput, ReadImageTool,
)
from src.video_agent.utils.agent_depth import (
    bind_subagent_depth, unbind_subagent_depth,
)

USER_ONLY = "gate-user-only"
MODEL_OK = "gate-model-ok"
REL_PATH = "references/note.md"
BODY = "分册正文：这里是被保护的内容。\n"


def _doc(name: str, fm: str) -> str:
    return f"---\nname: {name}\ndescription: 门禁用测试桩\n{fm}---\n# {name}\n\n## 一、目标\n正文\n"


@pytest.fixture
def gate_skills(tmp_path, monkeypatch):
    """两个技能包：user-only（disable-model-invocation: true）与模型可用。

    夹具自建、不依赖真实 data/skills 的包名（真实包会随用户增删漂移）。
    """
    root = tmp_path / "skills"
    for slug, fm in ((USER_ONLY, "disable-model-invocation: true\n"),
                     (MODEL_OK, "")):
        pkg = root / slug
        pkg.mkdir(parents=True)
        (pkg / SKILL_DOC_NAME).write_text(_doc(slug, fm), encoding="utf-8")
        (pkg / "references").mkdir()
        (pkg / "references" / "note.md").write_text(BODY, encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", root)
    registry.reset_registry()
    registry.sync_all(force=True)
    yield root
    registry.reset_registry()


@pytest.fixture
def as_subagent():
    """在子代理上下文（深度 1）内执行；退出即解绑。"""
    token = bind_subagent_depth(1)
    try:
        yield
    finally:
        unbind_subagent_depth(token)


def _read_file(skill: str, path: str = REL_PATH):
    return asyncio.run(
        ReadFileTool().aexecute(ReadFileInput(skill=skill, file_path=path)))


def test_main_agent_cannot_read_user_only_skill_md(gate_skills):
    """主代理读 user-only 的 SKILL.md：拒绝，且不返回任何正文。"""
    res = _read_file(USER_ONLY, "SKILL.md")
    assert res.success is False
    assert res.error == f'skill "{USER_ONLY}" is not available for model invocation'
    assert res.error_code == "validation"
    assert not (res.data or {}).get("content")


def test_main_agent_cannot_read_user_only_reference(gate_skills):
    """主代理读 user-only 的分册：同样拒绝（不是只挡主文档）。"""
    res = _read_file(USER_ONLY, REL_PATH)
    assert res.success is False
    assert res.error_code == "validation"
    assert "not available for model invocation" in (res.error or "")


def test_main_agent_can_read_model_invocable(gate_skills):
    """模型可用技能：主代理照常可读（门禁只针对 user-only）。"""
    res = _read_file(MODEL_OK, REL_PATH)
    assert res.success is True
    assert BODY.strip() in str((res.data or {}).get("content") or "")


def test_subagent_can_read_user_only(gate_skills, as_subagent):
    """子代理读 user-only：放行（主代理把技能包路径交给子代理自读的设计）。"""
    res = _read_file(USER_ONLY, REL_PATH)
    assert res.success is True, res.error
    assert BODY.strip() in str((res.data or {}).get("content") or "")


def test_subagent_can_read_user_only_skill_md(gate_skills, as_subagent):
    """子代理读 user-only 的 SKILL.md：放行。"""
    res = _read_file(USER_ONLY, "SKILL.md")
    assert res.success is True, res.error


def test_read_image_same_gate(gate_skills, tmp_path):
    """read_image 与 read_file 同口径（共用解析器，自动继承）。

    用 1x1 PNG 最小字节验证"门禁先于图片解码"：主代理被拒；
    子代理在能力未知（None）时放行。
    """
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    pkg = gate_skills / USER_ONLY
    (pkg / "assets").mkdir(exist_ok=True)
    (pkg / "assets" / "pic.png").write_bytes(png)

    def call():
        return asyncio.run(ReadImageTool().aexecute(
            ReadImageInput(skill=USER_ONLY, file_path="assets/pic.png")))

    denied = call()
    assert denied.success is False
    assert "not available for model invocation" in (denied.error or "")
    assert not (denied.data or {}).get("images")

    token = bind_subagent_depth(1)
    try:
        allowed = call()
    finally:
        unbind_subagent_depth(token)
    assert allowed.success is True, allowed.error


def test_depth_unbound_defaults_to_main_agent(gate_skills):
    """未绑定深度 = 0 = 主代理（fail-closed 取更严一侧）。"""
    from src.video_agent.utils.agent_depth import (
        current_subagent_depth, is_subagent_context,
    )

    assert current_subagent_depth() == 0
    assert is_subagent_context() is False
    assert _read_file(USER_ONLY).success is False
