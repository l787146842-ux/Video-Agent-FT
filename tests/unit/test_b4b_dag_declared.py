"""B4b/F32 回归：DAG 步骤完成度声明化（step_done_conditions 客观状态键评估）。"""
from src.video_agent.skill_runtime.dag import step_done


def test_step_done_uses_declared_conditions():
    """声明化评估优先于关键字猜测：「生成分镜参考图」不再被「分镜」误判完成。"""
    state = {
        "keyElements": [],
        "shots": [{"id": "s1", "drafts": [{"videoUrl": "v.mp4"}]}],
        "audioItems": [],
    }
    assert step_done(3, "生成分镜参考图", state, {"3": "shots"}) is True
    # 声明为 ke_media 时：关键元素无图 → 未完成（关键字「分镜」被声明覆盖）
    assert step_done(3, "生成分镜参考图", state, {"3": "ke_media"}) is False


def test_step_done_falls_back_to_keywords_without_declaration():
    state = {"keyElements": [], "shots": [{"id": "s1", "drafts": []}], "audioItems": []}
    assert step_done(2, "设计分镜", state) is True  # 关键字兜底（存量 Skill 兼容）


def test_manifest_parses_step_done_conditions():
    from src.video_agent.web.skill_docs import parse_skill_manifest

    m = parse_skill_manifest(
        "# x\n```json skill_manifest\n"
        '{"flow": {"spec_wizard": true, "step_done_conditions": {"1": "spec", "4": "shots"}}}\n'
        "```"
    )
    assert m["flow"]["step_done_conditions"] == {"1": "spec", "4": "shots"}


def test_manifest_drops_unknown_step_done_keys():
    from src.video_agent.web.skill_docs import parse_skill_manifest

    m = parse_skill_manifest(
        "# x\n```json skill_manifest\n"
        '{"flow": {"step_done_conditions": {"1": "evil", "2": "shots"}}}\n'
        "```"
    )
    assert m["flow"].get("step_done_conditions") == {"2": "shots"}
