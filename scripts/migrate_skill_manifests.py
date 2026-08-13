# -*- coding: utf-8 -*-
"""S1 清偿迁移：为存量 Skill 写入 skill_manifest 声明块，删除旧 pause_rules/gate_rules 块。

幂等：已含 skill_manifest 的文件跳过。直接写文件（批量迁移不走 save_skill_doc，
避免触发注册表与历史备份副作用）。
"""
import json
import pathlib
import re

D = pathlib.Path(__file__).parent.parent / "data" / "skills"

_ALL = {"require_duration": True, "require_subtitle": True,
        "require_camera_language": True, "require_audio_layer": True}
_CAM_AUDIO_SUB = {"require_subtitle": True, "require_camera_language": True,
                  "require_audio_layer": True}
_CAM_AUDIO = {"require_camera_language": True, "require_audio_layer": True}
_CAM_ONLY = {"require_camera_language": True}

CONFIG = {
    "3D国漫古装精品短剧": {**_ALL, "_flow": {"spec_gate": True}},
    "AI-短剧一站式生成": {**_ALL, "_flow": {"spec_gate": True}},
    "人文纪录短片": {**_CAM_ONLY, "_flow": {"spec_gate": True}},
    "剧情短片音色参考": {**_ALL, "_flow": {"spec_gate": True}, "_pause": {"stage_pause": True}},
    "剧本生视频需上传剧本": {
        **_ALL,
        "_flow": {"spec_wizard": True, "spec_stage_trim": True, "channels_block": True,
                  "spec_gate": True},
        "_pause": {"stage_pause": True},
    },
    "叙事驱动的美学视频": {**_CAM_AUDIO_SUB, "_flow": {"spec_gate": True}},
    "古风甜宠短剧": {**_ALL, "_flow": {"spec_gate": True}},
    "商品宣传短片": {**_ALL, "_flow": {"spec_gate": True}},
    "多人对话访谈": {**_CAM_AUDIO_SUB, "_flow": {"spec_gate": True}},
    # 宣言式：旁白英文锁定（cjk=0 关闭语言闸）、片长由文案推导不预锁（duration 关）
    "宣言式概念短片": {"cjk_min_ratio": 0, "require_subtitle": True,
                       "require_camera_language": True, "require_audio_layer": True,
                       "_flow": {"spec_gate": True}},
    "故事驱动型视频": {**_ALL, "_flow": {"spec_gate": True}},
    "未来科幻真人电影": {**_ALL, "_flow": {"spec_gate": True}},
    "李安美学风格短片": {**_CAM_AUDIO, "_flow": {"spec_gate": True}},
    "水墨风格武侠短片": {**_CAM_AUDIO_SUB, "_flow": {"spec_gate": True}},
    "视频拉片复刻": {**_ALL, "_flow": {"spec_gate": True}},
    "音乐MV需上传音乐": {**_CAM_AUDIO_SUB, "_flow": {"spec_gate": True}},
}

_OLD_BLOCK_RE = re.compile(
    r"\n*```(?:json|js)?\s*(?:pause_rules|gate_rules)\s*\n.*?```\n*", re.S | re.I
)


def build_block(cfg: dict) -> str:
    manifest = {}
    gates = {k: v for k, v in cfg.items() if not k.startswith("_")}
    if gates:
        manifest["gates"] = gates
    if cfg.get("_flow"):
        manifest["flow"] = cfg["_flow"]
    if cfg.get("_pause"):
        manifest["pause"] = cfg["_pause"]
    body = json.dumps(manifest, ensure_ascii=False, indent=2)
    return f"```json skill_manifest\n{body}\n```"


def migrate(path: pathlib.Path, cfg: dict) -> bool:
    content = path.read_text(encoding="utf-8")
    if "skill_manifest" in content:
        print(f"  跳过（已有 manifest）: {path.name}")
        return False
    content = _OLD_BLOCK_RE.sub("\n", content)
    block = build_block(cfg)
    lines = content.splitlines(keepends=True)
    # 插入位置：首行标题之后（保留 # 标题在文档顶部，供目录/名称解析）
    idx = 1 if lines and lines[0].startswith("# ") else 0
    lines[idx:idx] = ["\n" + block + "\n"]
    path.write_text("".join(lines), encoding="utf-8")
    print(f"  已迁移: {path.name}")
    return True


def main():
    done = 0
    for stem, cfg in CONFIG.items():
        p = D / f"{stem}.md"
        if not p.exists():
            print(f"  !! 文件不存在: {p.name}")
            continue
        if migrate(p, cfg):
            done += 1
    print(f"完成：迁移 {done} 个 Skill")


if __name__ == "__main__":
    main()
