# -*- coding: utf-8 -*-
"""一次性迁移：为 data/skills_manifests/*.json 写入 flow.step_stages 显式声明。

P3-12（sidecar schema v2）：step→stage 映射从 pipeline_orchestrator 关键词
启发式改为 sidecar 显式声明。映射表 = 当前启发式结果 + 逐条人工核对 skill
文档语义（7 规范阶段：analysis/spec/structure/ke_media/shot_media/
audio_assets/assembly）。两处刻意留白（声明会制造阶段 DAG 环 = 调度死锁，
且启发式现状同样未映射，行为零漂移）：
- 剧本生视频需上传剧本 step 4（元素出图夹在两次拆分之间，structure↔ke_media 成环）；
- 古风甜宠短剧 step 2（形象参考图先于故事板，ke_media↔structure 成环）。

幂等：已存在 step_stages 的文件跳过。用法：python scripts/migrate_step_stages.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MANIFEST_DIR = ROOT / "data" / "skills_manifests"

CANONICAL = {
    "analysis", "spec", "structure", "ke_media",
    "shot_media", "audio_assets", "assembly",
}

STEP_STAGES = {
    "3D国漫古装精品短剧": {
        "1": "analysis",   # 剧本分析 script_analyze
        "2": "analysis",   # 剧本细化与钩子增强（更新剧本文本，仍属剧本迭代）
        "3": "spec",       # 写入 Final_Video_Spec.md
        "4": "structure",  # 设计 Storyboard
        "5": "ke_media",   # key_element 设定图 + 音色样本
        "6": "shot_media", "7": "audio_assets", "8": "assembly",
    },
    "AI-短剧一站式生成": {
        "1": "analysis", "2": "spec", "3": "structure",
        "4": "ke_media",
        "5": "ke_media",   # 分镜表格图 = 视觉锚点类（启发式现状同归 ke_media）
        "6": "shot_media", "7": "audio_assets", "8": "assembly",
    },
    "人文纪录短片": {
        "1": "spec",       # 建立 Final_Video_Spec.md（无剧本分析步）
        "2": "structure",  # 故事板 + 资产绑定
        "3": "ke_media",   # 设置元素图像
        "4": "ke_media",   # 每镜头首帧图
        "5": "shot_media", "6": "audio_assets", "7": "assembly",
    },
    "剧情短片音色参考": {
        "1": "analysis", "2": "spec", "3": "structure",
        "4": "ke_media",   # 设置元素 + 音色锚点
        "5": "shot_media", "6": "audio_assets", "7": "assembly",
    },
    "剧本生视频需上传剧本": {
        "1": "analysis", "2": "spec",
        "3": "structure",  # 第一拆：关键元素
        # step 4（关键元素出图）留白：夹在两次拆分之间，声明必成环；
        # 启发式现状同样未映射（边被吸收），行为零漂移
        "5": "structure",  # 第二拆：分镜与音频层
        "6": "ke_media",   # 分镜视频 Prompt Draft（write_media_prompt 归 ke_media）
        "7": "shot_media", "8": "audio_assets", "9": "assembly",
    },
    "叙事驱动的美学视频": {
        "1": "spec", "2": "structure", "3": "ke_media",
        "4": "shot_media", "5": "audio_assets", "6": "assembly",
    },
    "古风甜宠短剧": {
        "0": "analysis",   # 剧本来源确认
        "1": "analysis",   # 剧本审核确认
        # step 2（形象参考图先于故事板）留白：声明必成环；
        # 启发式现状同样未映射（边被吸收），行为零漂移
        "3": "spec",       # 视频比例与制作偏好确认
        "4": "structure",  # 故事板生成
        "5": "ke_media",   # 场景图生成
        "6": "shot_media", "7": "assembly",
    },
    "商品宣传短片": {
        "1": "spec", "2": "structure", "3": "ke_media",
        "4": "shot_media", "5": "audio_assets", "6": "assembly",
    },
    "多人对话访谈": {
        "1": "spec", "2": "structure",
        "3": "ke_media",   # 元素图像
        "4": "audio_assets",  # 旁白与 BGM
        "5": "ke_media",   # 每镜头关键帧图像
        "6": "shot_media", "7": "assembly",
    },
    "宣言式概念短片": {
        "1": "audio_assets",  # 文案（旁白文本）命名化约束
        "2": "shot_media",    # 画面符号化约束（dependencies 为空，DAG 无影响）
    },
    "故事驱动型视频": {
        "1": "spec", "2": "structure", "3": "ke_media",
        "4": "shot_media", "5": "audio_assets", "6": "assembly",
    },
    "未来科幻真人电影": {
        "1": "spec",       # 锁定全局规格
        "2": "spec",       # 确认故事梗概与美术方向（规格锁定的一部分）
        "3": "ke_media",   # 人物设定 + 基础资产四视图
        "4": "ke_media",   # 场景设定图与四视图资产
        "5": "structure",  # 段落级分镜
        "6": "structure",  # 分镜草稿图与分镜脚本敲定
        "7": "assembly",   # 视频段落生成 + 时间线组装（末步归组装）
    },
    "李安美学风格短片": {
        "1": "analysis",   # 构思引导与子风格匹配（分析用户构思）
        "2": "analysis",   # 风格确认暂停点（构思确认，仍属分析侧）
        "3": "spec",       # 锁定全局参数 Final_Video_Spec.md
        "4": "structure", "5": "ke_media", "6": "shot_media",
        "7": "audio_assets", "8": "assembly",
        "9": "assembly",   # 后期超分（剪辑后处理）
    },
    "水墨风格武侠短片": {
        "1": "spec", "2": "structure",
        "3": "ke_media",   # 参考素材绑定与分析（元素资产侧）
        "4": "ke_media",   # 图像元素风格化重塑
        "5": "shot_media", "6": "audio_assets", "7": "assembly",
    },
    "视频拉片复刻": {
        "1": "analysis", "2": "spec", "3": "structure",
        "4": "ke_media", "5": "shot_media", "6": "audio_assets",
        "7": "assembly",
    },
    "音乐MV需上传音乐": {
        "1": "analysis",   # 分析音乐结构
        "2": "spec", "3": "structure",
        "4": "ke_media",   # 设置元素
        "5": "ke_media",   # 每镜头关键帧图像
        "6": "shot_media", "7": "assembly",
    },
}


def main() -> int:
    from src.video_agent.skill_runtime.sidecar import validate_sidecar

    files = sorted(MANIFEST_DIR.glob("*.json"))
    if len(files) != 16:
        print(f"[migrate_step_stages] FAIL: 预期 16 个 manifest，实见 {len(files)}")
        return 1
    changed, skipped = 0, 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        flow = data.get("flow") or {}
        mapping = STEP_STAGES.get(f.stem)
        if mapping is None:
            print(f"[migrate_step_stages] FAIL: {f.stem} 无映射表")
            return 1
        if "step_stages" in flow:
            print(f"[migrate_step_stages] SKIP: {f.stem}（已声明）")
            skipped += 1
            continue
        steps = flow.get("steps") or {}
        unknown = sorted(set(mapping) - {str(k) for k in steps})
        bad = sorted(k for k, v in mapping.items() if v not in CANONICAL)
        if unknown or bad:
            print(f"[migrate_step_stages] FAIL: {f.stem} 非法映射"
                  f"（未知步骤 {unknown}，非法阶段 {bad}）")
            return 1
        # 保序插入：step_stages 置于 dependencies 之后
        new_flow = {}
        inserted = False
        for k, v in flow.items():
            new_flow[k] = v
            if k == "dependencies":
                new_flow["step_stages"] = mapping
                inserted = True
        if not inserted:
            new_flow["step_stages"] = mapping
        data["flow"] = new_flow
        issues = validate_sidecar(data)
        if issues:
            print(f"[migrate_step_stages] FAIL: {f.stem} 迁移后体检未过: {issues}")
            return 1
        f.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"[migrate_step_stages] OK: {f.stem} +step_stages"
              f"（{len(mapping)}/{len(steps)} 步声明）")
        changed += 1
    print(f"[migrate_step_stages] done: {changed} changed, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
