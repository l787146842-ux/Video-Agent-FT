"""read_skill 续读语义：全文/标题章节/start 续读 + 三段式返回。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    # M2 门户：read_skill 放行须可加载（已注册）→ 隔离注册表，
    # 用例内懒同步只扫本临时目录；用例后重置防污染。
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _body(out: str) -> str:
    """取三段式里的 <skill_content> 正文（不含包装与续读提示）。"""
    text = out.split("<skill_content", 1)[1]
    text = text.split(">", 1)[1]
    body = text.split("</skill_content>", 1)[0]
    return body.split("\n……")[0].strip("\n")


def _save_long_skill():
    filler = "章节正文填充。" * 50
    sd.save_skill_doc(
        "续读演示",
        "---\nname: 续读演示\ndescription: 测试桩\n---\n"
        "# 续读演示\n\n"
        f"## 制作流程\n流程总纲 SEC_PLANNER_BODY\n{filler}\n\n"
        f"## 关键元素\n关键元素规范 SEC_KE_BODY\n{filler}\n",
    )


@pytest.mark.asyncio
async def test_read_skill_full_text_default(skills_dir):
    _save_long_skill()
    res = await ReadSkillTool().aexecute(ReadSkillInput(name="续读演示"))
    assert res.success
    assert "SEC_PLANNER_BODY" in res.data["content"]
    assert "SEC_KE_BODY" in res.data["content"]
    assert "<skill_content" in res.data["content"]
    assert "<skill_instructions>" in res.data["content"]


@pytest.mark.asyncio
async def test_read_skill_section_returns_only_that_section(skills_dir):
    _save_long_skill()
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="续读演示", section="关键元素"))
    assert res.success
    assert res.data["section"] == "关键元素"
    assert "SEC_KE_BODY" in res.data["content"]
    assert "SEC_PLANNER_BODY" not in res.data["content"]


@pytest.mark.asyncio
async def test_read_skill_section_fuzzy_title(skills_dir):
    """章节标题大小写/空格容差"""
    sd.save_skill_doc(
        "英文章节",
        "---\nname: 英文章节\ndescription: 测试桩\n---\n"
        "# 英文章节\n\n## Write_The_Prompt\nMARK_EN\n",
    )
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="英文章节", section="write_the_prompt"))
    assert res.success and "MARK_EN" in res.data["content"]


@pytest.mark.asyncio
async def test_read_skill_unknown_section_lists_available(skills_dir):
    _save_long_skill()
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="续读演示", section="不存在章节"))
    assert not res.success
    assert "制作流程" in res.error and "关键元素" in res.error


@pytest.mark.asyncio
async def test_read_skill_start_continuation(skills_dir):
    """start 偏移续读：首段与续段拼回全文不丢字"""
    _save_long_skill()
    tool = ReadSkillTool()
    _, full = sd.resolve_skill_content("续读演示")
    from src.video_agent.config import settings

    old = settings.max_doc_chars
    try:
        object.__setattr__(settings, "max_doc_chars", 100)
        r1 = await tool.aexecute(ReadSkillInput(name="续读演示"))
        assert r1.success and "start=100" in r1.data["content"]
        r2 = await tool.aexecute(ReadSkillInput(name="续读演示", start=100))
        assert r2.success
        got = _body(r1.data["content"]) + _body(r2.data["content"])
        assert got.rstrip() == full[:len(got.rstrip())]
        # 读到末尾后再续读 → 明确报读完
        r3 = await tool.aexecute(ReadSkillInput(name="续读演示", start=len(full)))
        assert not r3.success and "已读完" in r3.error
    finally:
        object.__setattr__(settings, "max_doc_chars", old)
