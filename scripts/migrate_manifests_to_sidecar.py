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
    m = freeze_flow_flags()
    print(f"OK migrated={n} frozen={m}")
    return 0


def freeze_flow_flags() -> int:
    """B4：把 spec_wizard/script_required 的客观检测现值冻结进 sidecar，
    随后 registry 改 sidecar 唯一源（文本启发式退役）。幂等。"""
    from src.video_agent.skill_runtime import registry

    frozen = 0
    for f in sorted(Path(sd.SKILL_DOCS_DIR).glob("*.md")):
        slug = f.stem
        entry = registry.register_skill(slug)
        if entry is None:
            continue
        data = sidecar.load_sidecar(slug) or {}
        flow = data.setdefault("flow", {})
        want_wizard = bool(registry.spec_wizard_active(slug))
        want_script = bool(registry.script_required_active(slug))
        if flow.get("spec_wizard") is want_wizard and \
                flow.get("script_required") is want_script:
            continue
        flow["spec_wizard"] = want_wizard
        flow["script_required"] = want_script
        sidecar.write_sidecar(slug, data)
        frozen += 1
    return frozen


if __name__ == "__main__":
    raise SystemExit(main())
