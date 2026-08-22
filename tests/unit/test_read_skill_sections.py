"""read_skill 续读语义（任务#36 B5）：全文按需读 + section/start 章节续读。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    return d


def _save_long_skill():
    filler = "章节正文填充。" * 50
    sd.save_skill_doc(
        "续读演示",
        "# 续读演示\n> 调用规则：测试\n"
        f"<planner>\n流程总纲 SEC_PLANNER_BODY\n{filler}</planner>\n"
        f"<storyboard_key_elements>\n关键元素规范 SEC_KE_BODY\n{filler}</storyboard_key_elements>\n",
    )


@pytest.mark.asyncio
async def test_read_skill_full_text_default(skills_dir):
    _save_long_skill()
    res = await ReadSkillTool().aexecute(ReadSkillInput(name="续读演示"))
    assert res.success
    assert "SEC_PLANNER_BODY" in res.data["content"]
    assert "SEC_KE_BODY" in res.data["content"]


@pytest.mark.asyncio
async def test_read_skill_section_returns_only_that_section(skills_dir):
    _save_long_skill()
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="续读演示", section="storyboard_key_elements"))
    assert res.success
    assert res.data["section"] == "storyboard_key_elements"
    assert "SEC_KE_BODY" in res.data["content"]
    assert "SEC_PLANNER_BODY" not in res.data["content"]


@pytest.mark.asyncio
async def test_read_skill_section_fuzzy_title(skills_dir):
    """章节标题大小写/空格容差"""
    sd.save_skill_doc(
        "英文章节",
        "# 英文章节\n> 调用规则：测试\n<Write_The_Prompt>\nMARK_EN\n</Write_The_Prompt>\n",
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
    assert "planner" in res.error and "storyboard_key_elements" in res.error


@pytest.mark.asyncio
async def test_read_skill_start_continuation(skills_dir):
    """start 偏移续读：首段与续段拼回全文不丢字"""
    _save_long_skill()
    tool = ReadSkillTool()
    _, full = sd.resolve_skill_content("续读演示")
    # 用一个很小的窗口模拟超长分段（直接改 settings 上限）
    from src.video_agent.config import settings

    old = settings.max_doc_chars
    try:
        object.__setattr__(settings, "max_doc_chars", 100)
        r1 = await tool.aexecute(ReadSkillInput(name="续读演示"))
        assert r1.success and "start=100" in r1.data["content"]
        r2 = await tool.aexecute(ReadSkillInput(name="续读演示", start=100))
        assert r2.success
        got = r1.data["content"].split("\n……")[0] + r2.data["content"].split("\n……")[0]
        # 两段拼接覆盖全文前 200 字（续读提示不算正文）
        assert got.rstrip() == full[:len(got.rstrip())]
        # 读到末尾后再续读 → 明确报读完
        r3 = await tool.aexecute(ReadSkillInput(name="续读演示", start=len(full)))
        assert not r3.success and "已读完" in r3.error
    finally:
        object.__setattr__(settings, "max_doc_chars", old)
