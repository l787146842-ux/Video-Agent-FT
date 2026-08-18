# -*- coding: utf-8 -*-
"""B0：批量迁移 skill 文档 manifest 到 sidecar（幂等）。

用法：python scripts/migrate_manifests_to_sidecar.py
迁移后 skill 文档还原纯散文；registry 双读 sidecar 优先（零行为变化）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.video_agent.skill_runtime import sidecar
from src.video_agent.web import skill_docs as sd


def main() -> int:
    n = 0
    for f in sorted(Path(sd.SKILL_DOCS_DIR).glob("*.md")):
        if sidecar.migrate_doc_to_sidecar(f):
            n += 1
    print(f"OK migrated={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
