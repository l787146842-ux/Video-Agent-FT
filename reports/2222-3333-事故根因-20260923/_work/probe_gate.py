# -*- coding: utf-8 -*-
"""复算 structure_integrity_gate 对 2222 数据是否可能拦截（只读，纯函数重放）。"""
import sqlite3, json, io, os, re

OUT = os.path.join(os.path.dirname(__file__), "probe_gate_out.txt")
L = []
def P(s=""): L.append(str(s))
c = sqlite3.connect(r'workspace/state.sqlite3')
st = json.loads(c.execute("select state from projects where id=?",
                          ('proj-1790091531-97d20b2d',)).fetchone()[0])
kes = st.get('keyElements') or []
shots = st.get('shots') or []
P("【structure_integrity_gate ② 重放】判定式（fc_gates.py L289-311）:")
P("    t in title  and  kid not in refs  and  t not in refs  → missing")
P("    t = KE 组标题（原文），title = shot 标题，refs = scene_refs 入参")
P()
ke_titles = [str(k.get('title') or '').strip() for k in kes]
ke_ids = [str(k.get('id') or '') for k in kes]
P("KE 组标题池（t 的取值） = %s" % json.dumps(ke_titles, ensure_ascii=False))
P()
n_missing = 0
n_empty = 0
for i, g in enumerate(shots, 1):
    title = g.get('title') or ''
    refs = [str(r) for r in (g.get('sceneRefs') or []) if str(r).strip()]
    missing = [t for t, kid in zip(ke_titles, ke_ids)
               if t and t in title and kid not in refs and t not in refs]
    if not refs:
        n_empty += 1
        status = "拒收（sceneRefs 为空）"
    elif missing:
        n_missing += 1
        status = "拒收（标题提及的 %s 未被引用）" % missing
    else:
        status = "放行"
    P("shot%02d | refs 项数=%d | missing=%s | → %s" % (i, len(refs), json.dumps(missing, ensure_ascii=False), status))
P()
P("=> 26 镜中：sceneRefs 为空者 = %d；被闸②拒收者 = %d；**放行者 = %d**" % (
    n_empty, n_missing, len(shots) - n_empty - n_missing))
P()
P("结论：闸② 的 t 取自 KE 组标题。2222 的组标题是粗组名（Element_主要角色/关键场景/关键道具），")
P("而 shot 标题里出现的是角色名/场景名（程心、星环号球形舱…），**t in title 恒为 False**，")
P("故 missing 恒空 → 只要 scene_refs 非空就一律放行；refs 内容是否真正指向 KE 组不被检查。")
P()
# 对照：如果是一元素一组（3333 形态）会怎样
kes3 = json.loads(c.execute("select state from projects where id=?",
                            ('proj-1790092267-a9abcb25',)).fetchone()[0]).get('keyElements') or []
shots3 = json.loads(c.execute("select state from projects where id=?",
                             ('proj-1790092267-a9abcb25',)).fetchone()[0]).get('shots') or []
P("【对照 3333】16 个 KE 组标题里，有多少会出现在对应 shot 标题中（t in title）：")
for i, g in enumerate(shots3, 1):
    title = g.get('title') or ''
    hit = [k.get('title') for k in kes3 if k.get('title') and k.get('title') in title]
    if hit:
        P("  shot%02d 命中 t = %s → 闸② 需 refs 覆盖之" % (i, json.dumps(hit, ensure_ascii=False)))
P("  （2222 同类命中数 = %d）" % sum(
    1 for g in shots if any((k.get('title') or '') in (g.get('title') or '') for k in kes)))
io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("written", OUT)
