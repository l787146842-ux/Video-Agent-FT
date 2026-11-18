"""分册可见性（2026-11-12 dsh 口径）。

正文不再随 system prompt 注入；分册由注入块的 `read_file` 提示 + 技能包
`references/` 实际文件提供。旧的“截断注入补分册清单”机制随整篇注入一起退役。
"""
import asyncio

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.skill_file_tools import ReadFileInput, ReadFileTool


def _doc(padding_repeat: int, refs: list) -> str:
    filler = "流程正文填充。" * padding_repeat
    ref_lines = "\n".join(f"- `{r}`" for r in refs)
    return (
        "---\nname: 分册可见性\ndescription: 分册读取用例\n---\n"
        "# 分册可见性\n\n"
        "## 一、目标\n\n" + filler + "\n\n"
        "## 二、制作流程\n\n" + filler + "\n\n"
        "## 三、参考资料\n\n需要细节时读取对应分册：\n\n" + ref_lines + "\n"
    )


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _pb():
    return PromptBuilder(
        lambda: sd, lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


REFS = ["references/媒体生成.md", "references/提示词写作.md"]


def test_selected_block_does_not_inject_body_or_references(skills_dir):
    sd.save_skill_doc("分册可见性", _doc(3000, REFS))
    block = _pb().build_selected_skill_block("分册可见性")
    assert "当前主 Skill" in block
    assert "read_file" in block
    for r in REFS:
        assert r not in block, "正文/分册清单不再随 system prompt 注入"


def test_read_file_can_read_reference(skills_dir):
    sd.save_skill_doc("分册可见性", _doc(1, REFS))
    ref = skills_dir / "分册可见性" / "references" / "媒体生成.md"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("媒体生成分册正文 REF_MARK", encoding="utf-8")
    res = asyncio.run(ReadFileTool().aexecute(ReadFileInput(
        skill="分册可见性", file_path="references/媒体生成.md")))
    assert res.success is True
    assert "REF_MARK" in (res.data or {})["content"]


def test_reference_paths_dedup_and_strip_punctuation():
    pb = _pb()
    content = (
        "读 `references/媒体生成.md`、`references/提示词写作.md`，"
        "再读 references/媒体生成.md。"
    )
    assert pb._reference_paths(content) == [
        "references/媒体生成.md", "references/提示词写作.md"]
