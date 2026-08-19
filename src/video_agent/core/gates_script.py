"""剧本原料闸家族（自 prompt_gates.py 切出； 宪法 13.5 确定性三问收归系统）。

「剧本是否已交」可从客观数据算出（uploadedDocs/analysis）、可机器一眼判定、
无创作空间 → 收归系统：缺失时提醒/短路/拦越阶，不再出题给模型。
被测试 patch 的符号经 prompt_gates 模块属性引用（尾块登记 re-export，
patch prompt_gates 即可生效）。
"""
import re
from typing import Any, Dict, List, Tuple

from src.video_agent.core.prompt_gates import _gate_json, _gate_msg

_SCRIPT_FEATURE_RE = re.compile(
    r"(上传剧本|剧本文件|读取并分析[^\n]{0,12}剧本|script_analyze|分析用户上传的[^\n]{0,10}文件)"
)


def text_mentions_script(text: str) -> bool:
    """Skill 正文客观特征：流程含「上传/分析剧本」环节（script_required 客观检测判据，
    与 spec_wizard_active 同模式；manifest flow.script_required 显式声明优先）。"""
    return bool(_SCRIPT_FEATURE_RE.search(str(text or "")))


def script_present(state: Dict[str, Any]) -> bool:
    """原料已交的客观判定：有上传文档，或剧本分析摘要已存在。"""
    if (state or {}).get("uploadedDocs"):
        return True
    ana = (state or {}).get("analysis") or {}
    return bool(str(ana.get("summary") or "").strip())


# 豁免意图（用户明确不要剧本/拒绝提醒）：与提醒卡选项「确认从零原创」同语义源
_SCRIPT_WAIVE_RE = re.compile(
    r"(从零|原创|无需剧本|不要剧本|不用剧本|没有剧本也|自行创作|你编|即兴|别提醒|不要提醒|直接继续|直接推进)"
)


def script_waive_intent(text: str) -> bool:
    """用户消息是否表达「无剧本豁免」意图（Context≠Consent：只认显式话术）。

    ：提醒卡选项携带 value（waive_script），点击即机械消费——意图识别
    不再依赖正则猜话术（正则仅作手工输入的兜底）。"""
    t = str(text or "").strip()
    if t == "waive_script":
        return True
    return bool(_SCRIPT_WAIVE_RE.search(t))


# 推进意图（短路触发条件之一）：用户在推进任务而非提问
_SCRIPT_PROGRESS_RE = re.compile(
    r"(上传|剧本|开始|继续|做|生成|拆解|分析|准备|好了|有|确认|执行)"
)
_SCRIPT_QUESTION_RE = re.compile(r"[？?]|什么|为什么|怎么|如何|你是谁|介绍|能不能|可以吗")


def script_short_circuit_eligible(text: str) -> bool:
    """ 零思考直出准入：含推进意图 且 非提问 且 非长文本粘贴（>500 字视为原料在消息里）。

    提问类消息落回正常 LLM（回复末尾由层 9 附提醒），避免用催传卡答非所问（用户意志优先）。
    """
    t = str(text or "")
    if len(t) > 500:
        return False
    if _SCRIPT_QUESTION_RE.search(t):
        return False
    return bool(_SCRIPT_PROGRESS_RE.search(t))


def script_remind_card() -> Tuple[str, List[Dict[str, Any]]]:
    """剧本缺失提醒卡（层 9 兜底；文案外置 messages.md §SCRIPT_REMIND_CARD）。"""
    data = _gate_json("SCRIPT_REMIND_CARD", {
        "message": "这个 Skill 的创作以剧本为原料，当前还没收到剧本文件。请先上传剧本或粘贴剧本文字。",
        "options": [
            {"label": "确认从零原创（无需剧本）", "description": "记账豁免，不再提醒", "value": "waive_script"},
            {"label": "我去上传/粘贴剧本", "description": "原料一到自动开工", "value": "upload_script"},
        ],
    })
    return str(data.get("message") or ""), list(data.get("options") or [])


SCRIPT_MODEL_NOTE = _gate_msg(
    "SCRIPT_MODEL_NOTE",
    "剧本未提供。本轮先引导用户上传或粘贴剧本，不做规格收集、拆解结构等下游操作。",
)

SCRIPT_UPLOAD_ACK = _gate_msg(
    "SCRIPT_UPLOAD_ACK",
    "好的，我等你发送剧本。原料一到立刻开始分析与设计。",
)

# 提醒卡「我去上传/粘贴剧本」选项的回执语义：秒回等待句，不再重复弹卡。
# 首锚限定：只认「点选项/明确回应去上传」的话术；「有，我现在上传剧本」这类
# 推进话术仍走提醒卡分支（剧本实际未到，须提醒）。
_SCRIPT_UPLOAD_ACK_RE = re.compile(r"^(我去上传|好的，?我去|马上去|这就去)")


def script_upload_ack_intent(text: str) -> bool:
    """用户回应了「我去上传」类话术 → 回等待回执而非再弹提醒卡。

    ：提醒卡选项 value=upload_script 点击即机械消费；正则仅作手工输入兜底。"""
    if str(text or "").strip() == "upload_script":
        return True
    return bool(_SCRIPT_UPLOAD_ACK_RE.search(str(text or "")))
