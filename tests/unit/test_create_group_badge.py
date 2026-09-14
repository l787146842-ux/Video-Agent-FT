"""角标归一接回建组路径（3333 批回归修复）钉死测试。

背景：normalize_badge_label（desc→人物/场景/道具 归一）自 9/1 ecce275
「文本轨执行器退役批」删除唯一调用点后成为死代码——此后 FC 建组的
keyElement 组 badgeLabel 恒空，前端全落「关键元素」兜底（用户实测：
元素列表右上角不再按类型分）。本批把归一接回 storyboard_create_group。

钉死：
- keyElement 建组后 badgeLabel 按 desc 锚点归一（人物/场景/道具）；
- 非 keyElement（shot）不写 badgeLabel（前端分镜角标读 shotType）；
- desc 无锚点时保持空串（宁缺勿错，前端回落「关键元素」）。
"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.tools.storyboard_tools import (
    CreateGroupInput,
    StoryboardCreateGroupTool,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _groups(svc, cat):
    return svc.state_dict.get(cat) or []


async def test_key_element_badge_derived_from_desc(svc):
    """角色/场景/道具 desc 锚点 → badgeLabel 确定性归一"""
    tool = StoryboardCreateGroupTool()
    cases = [
        ("程心", "【角色·程心】青年女性，约28岁，鹅蛋脸，浅灰蓝色宇航制服", "人物"),
        ("星环号球形舱", "【场景·星环号球形舱】失重白色舱室，窗外木星云带旋转", "场景"),
        ("白色薄膜", "【关键道具·白色薄膜】8.5cm 白色长方形薄片，白光微辉", "道具"),
    ]
    for title, desc, want in cases:
        r = await tool.aexecute(CreateGroupInput(
            group_type="keyElement", title=title, desc=desc))
        assert r.success, f"{title} 建组失败: {r.error}"
    badges = {g["title"]: g.get("badgeLabel") for g in _groups(svc, CAT_KEY_ELEMENTS)}
    for title, _, want in cases:
        assert badges[title] == want, f"{title} 角标应为「{want}」，实际「{badges[title]}」"


async def test_shot_group_gets_no_badge_label(svc):
    """shot 组不写 badgeLabel（分镜角标固定「分镜」，shotType 已摘除）"""
    tool = StoryboardCreateGroupTool()
    r = await tool.aexecute(CreateGroupInput(
        group_type="shot", title="S1 木星初醒",
        desc="【场景】[星环号球形舱] 【空间锚点卡 / 星环号球形舱】固定参照物：观察窗。建立镜",
        duration="10s",
        scene_refs=["星环号球形舱"]))
    assert r.success
    # 取新建卡（[-1]）：demo 项目自带预置 shot-1（含历史字段），[0] 会抓错卡
    g = _groups(svc, CAT_SHOTS)[-1]
    assert g["title"].startswith("S1") or "木星初醒" in g["title"]
    assert "badgeLabel" not in g
    # roughDesc 写入通道退役（2026-09-15）：新建 shot 卡不再产 roughDesc，
    # 分镜正文唯一载体 = desc
    assert "roughDesc" not in g


async def test_shot_group_rejects_rough_desc_field(svc):
    """rough_desc 已从建组入参摘除（双通道歧义退役，2026-09-15 6666 实证）：
    传 rough_desc 会被 StrictToolInput 拒收（拒收+回喂，不静默丢）"""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        CreateGroupInput(
            group_type="shot", title="S1", desc="x",
            rough_desc="建立镜", scene_refs=["星环号球形舱"])


async def test_shot_group_rejects_shot_type_field(svc):
    """shotType 已从建组入参摘除：传 shot_type 会被 StrictToolInput 拒收"""
    import pydantic
    tool = StoryboardCreateGroupTool()
    with pytest.raises(pydantic.ValidationError):
        CreateGroupInput(group_type="shot", title="S2", shot_type="中景")


async def test_badge_empty_when_no_anchor(svc):
    """desc 无任何锚点 → badgeLabel 空串（宁缺勿错，前端回落「关键元素」）"""
    tool = StoryboardCreateGroupTool()
    r = await tool.aexecute(CreateGroupInput(
        group_type="keyElement", title="未知元素", desc="一段没有类型线索的描述"))
    assert r.success
    g = next(x for x in _groups(svc, CAT_KEY_ELEMENTS) if x.get("title") == "未知元素")
    assert g.get("badgeLabel") == ""
