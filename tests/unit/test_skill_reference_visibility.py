"""分册指针可见性回归（2026-11-11 事故）。

事故：主文档超过注入预算时只注入前 N 字 + 标题目录，而分册指针
（`references/xxx.md`）通常写在正文后段（如「参考资料」节），
一旦落到头部预算之外，模型就完全不知道分册存在——分册明明在
磁盘上，却从来没有任何东西告诉模型它可读。

本文件钉死：截断注入必须补一份从**全文**提取的分册清单。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry


def _doc(padding_repeat: int, refs: list) -> str:
    """构造一份超预算主文档：正文中部一大段填充，分册指针**全部放在末尾**。"""
    filler = "流程正文填充。" * padding_repeat
    ref_lines = "\n".join(f"- `{r}`" for r in refs)
    return (
        "---\nname: 分册可见性\ndescription: 分册指针落在注入窗口外的回归用例\n---\n"
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


def _truncated_block(slug: str, set_global_setting) -> str:
    """写入一份指针只在末尾的长文档（远超 12000 预算），返回截断后的注入块。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    set_global_setting("skill_selected_inject_head_chars", 6000)
    sd.save_skill_doc(slug, _doc(3000, REFS))  # 约 2 万字，指针全在末尾
    block = _pb().build_selected_skill_block(slug)
    assert block, "注入块不应为空"
    return block


def test_truncated_inject_lists_references(skills_dir, set_global_setting):
    """截断注入必须补发分册清单（否则指针落在窗口外即失联）。"""
    block = _truncated_block("分册可见性", set_global_setting)
    for r in REFS:
        assert r in block, f"分册指针 {r} 必须在截断注入块中可见"


def test_references_listed_even_when_cut_off(skills_dir, set_global_setting):
    """指针物理位置在头部预算之外时，仅靠截断正文是看不到的——清单负责补位。"""
    block = _truncated_block("分册可见性", set_global_setting)
    head_part = block.split("本 Skill 的分册")[0]
    assert "references/媒体生成.md" not in head_part, (
        "用例前提：指针应落在头部预算之外（截断正文里看不到）")
    assert "references/媒体生成.md" in block, "但清单必须让它可见"


def test_no_reference_section_when_within_budget(skills_dir, set_global_setting):
    """预算内全文注入不加分册清单段（行为零变化）。"""
    set_global_setting("skill_selected_inject_max_chars", 12000)
    sd.save_skill_doc(
        "短文档",
        "---\nname: 短文档\ndescription: 预算内\n---\n"
        "# 短文档\n\n## 一、制作流程\n\n正文 SHORT_FLOW\n",
    )
    block = _pb().build_selected_skill_block("短文档")
    assert "SHORT_FLOW" in block
    assert "正文因超预算被截断" not in block


def test_reference_paths_dedup_and_strip_punctuation():
    """路径提取：去重保序 + 去尾部标点。"""
    pb = _pb()
    content = (
        "读 `references/媒体生成.md`、`references/提示词写作.md`，"
        "再读 references/媒体生成.md。"
    )
    assert pb._reference_paths(content) == [
        "references/媒体生成.md", "references/提示词写作.md"]
