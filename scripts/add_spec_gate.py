# -*- coding: utf-8 -*-
"""S1 补丁：给已迁移 Skill 的 manifest 补 flow.spec_gate（规格前置警告声明）。

全部 16 个存量视频 Skill 的流程都含规格文档步骤，声明 spec_gate 与迁移前
行为严格等价（此前该警告对所有 Skill 无差别触发）。幂等：已声明则跳过。
"""
import json
import pathlib
import re

D = pathlib.Path(__file__).parent.parent / "data" / "skills"
_BLOCK_RE = re.compile(r"(```(?:json|js)?\s*skill_manifest\s*\n)(.*?)(```)", re.S | re.I)


def main():
    done = 0
    for f in sorted(D.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        m = _BLOCK_RE.search(content)
        if not m:
            continue
        try:
            manifest = json.loads(m.group(2))
        except Exception:
            print(f"  !! manifest 解析失败: {f.name}")
            continue
        flow = manifest.setdefault("flow", {})
        if flow.get("spec_gate"):
            print(f"  跳过（已声明）: {f.name}")
            continue
        flow["spec_gate"] = True
        body = json.dumps(manifest, ensure_ascii=False, indent=2)
        content = content[:m.start()] + m.group(1) + body + "\n" + m.group(3) + content[m.end():]
        f.write_text(content, encoding="utf-8")
        print(f"  已补 spec_gate: {f.name}")
        done += 1
    print(f"完成：{done} 个")


if __name__ == "__main__":
    main()
