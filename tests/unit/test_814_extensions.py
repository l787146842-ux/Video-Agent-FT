"""814E1/E2 钉死回归：通用章节执行器 + <planner> 依赖图调度。"""
import json

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import dag, executors as ex_mod, registry
from src.video_agent.state.manager import StateManager
from src.video_agent.skill_runtime import exec_common
from src.video_agent.web import generation as gen_mod

PLANNER_TEXT = """**全流程阶段与依赖关系**

1. 读取并分析用户上传的剧本文件 → **resource_prepare_and_analyze**
2. 将全局制作参数写入规格文档 → **text_editor**
3. 设计 Storyboard：登记所有关键元素并拆解分镜 → **storyboard_designer**
4. 生成所有关键元素设定图 → **media_generator**
5. 生成运镜轨迹示意图 → **media_generator**
6. 逐 shot 生成视频 → **media_generator**
7. 生成音频资产 → **media_generator**
8. 组装时间线 → **video_assembler**

**依赖关系：** 3→1,2；4→3；5→3；6→4,5；7→3；8→4,5,6,7
"""


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


class TestDag:
    def test_parse_steps_and_deps(self):
        steps = dag.parse_steps(PLANNER_TEXT)
        assert set(steps) == set(range(1, 9))
        deps = dag.parse_dependencies(PLANNER_TEXT)
        assert deps[3] == [1, 2]
        assert deps[6] == [4, 5]
        assert deps[8] == [4, 5, 6, 7]

    def test_topo_batches_parallelism(self):
        steps = dag.parse_steps(PLANNER_TEXT)
        deps = dag.parse_dependencies(PLANNER_TEXT)
        batches = dag.topo_batches(steps, deps)
        # 第一层：1/2 无前置可并行；3 在第二层；4/5/7 第三层…
        assert batches[0] == [1, 2]
        assert batches[1] == [3]
        assert batches[2] == [4, 5, 7]
        # 所有步骤不丢
        assert sorted(sum(batches, [])) == sorted(steps)

    def test_pipeline_status_ready_with_empty_state(self):
        state = {"keyElements": [], "shots": [], "audioItems": [], "documents": []}
        status = dag.pipeline_status(PLANNER_TEXT, state)
        ready = [s["step"] for s in status if s["ready"]]
        assert ready == [1, 2], "空状态下只有读取分析/规格两步可执行"

    def test_pipeline_status_advances(self):
        state = {
            "keyElements": [], "shots": [], "audioItems": [],
            "documents": [{"name": "Final_Video_Spec.md", "content": "x"}],
            "analysis": {"summary": "剧本一句话"},
        }
        status = dag.pipeline_status(PLANNER_TEXT, state)
        ready = [s["step"] for s in status if s["ready"]]
        assert 3 in ready, "1/2 完成后 3 应变 ready"


CUSTOM_SKILL = (
    "# 自定义章节 Skill\n> 调用规则：测试\n"
    "<planner>\n1. 读取并分析剧本 → **resource_prepare_and_analyze**\n"
    "2. 拆解分镜 → **storyboard_designer**\n依赖关系： 2→1\n</planner>\n"
    "<my_custom_tool>\n自定义章节规范：每个分组标题以 CUSTOM_ 开头。\n</my_custom_tool>\n"
)


class TestGenericSectionExecutor:
    def test_resolve_custom_tag_section(self):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        entry = registry.get_entry("custom")
        text = ex_mod._resolve_section_text(entry, "my_custom_tool")
        assert "CUSTOM_" in text, "白名单外自定义 tag 应能直取章节"
        # stage key 也能解析
        assert "依赖关系" in ex_mod._resolve_section_text(entry, "planning")
        # 不存在的章节返回空
        assert ex_mod._resolve_section_text(entry, "nope") == ""

    async def test_section_run_applies_actions(self, tmp_path, monkeypatch):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        svc = StateManager(str(tmp_path))
        monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
        monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("mockp", "mockm"))

        actions_json = json.dumps([
            {"action": "add_group", "group_type": "keyElement",
             "title": "CUSTOM_主角", "desc": "测试",
             "draft": {"label": "概念图", "mediaType": "image", "prompt": "x" * 90}},
        ], ensure_ascii=False)

        async def fake_chat(provider, model, messages, **kwargs):
            return f"```studio-actions\n{actions_json}\n```", "stop"

        monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_chat)
        tool = ex_mod.SkillSectionRunTool()
        result = await tool.aexecute(ex_mod.SkillSectionRunInput(
            skill_name="自定义章节 Skill", section="my_custom_tool", task="拆关键元素",
        ))
        assert result.success is True
        assert result.data["applied"] >= 1
        titles = [g.get("title") for g in svc.state_dict.get("keyElements", [])]
        assert "CUSTOM_主角" in titles

    async def test_section_run_unknown_section_reports_available(self, tmp_path, monkeypatch):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        svc = StateManager(str(tmp_path))
        monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
        tool = ex_mod.SkillSectionRunTool()
        result = await tool.aexecute(ex_mod.SkillSectionRunInput(
            skill_name="自定义章节 Skill", section="nope", task="x",
        ))
        assert result.success is False
        assert "planning" in result.error
