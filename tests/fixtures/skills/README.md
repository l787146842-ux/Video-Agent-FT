# 测试桩 Skill 夹具（B4/F31）

本目录存放仅测试使用的 Skill 文档（原误置于 `data/skills/`，污染生产技能下拉框）。

- `9999二轮测试桩.md` / `分章边界测试桩.md` / `显式向导测试桩.md` / `测试流程Skill.md` / `截断技能.md` / `豪华技能.md` / `ke-prog.md`

运行时接线：`tests/conftest.py::_test_skill_stubs` autouse fixture 把
`skill_docs.get_skill_doc` 的 slug 解析优先指向本目录（生产技能仍走 `data/skills/`），
因此注册表/执行器按名称解析测试桩时无需触碰生产目录。
