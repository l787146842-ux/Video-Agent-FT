# -*- coding: utf-8 -*-
"""精确终算：两项目「引用可点/可解析」三轴对照。只读。"""
import sqlite3, json, io, re, os

OUT = os.path.join(os.path.dirname(__file__), "probe_final_out.txt")
L = []
def P(s=""): L.append(str(s))
c = sqlite3.connect(r'workspace/state.sqlite3')
def load(pid):
    return json.loads(c.execute("select state from projects where id=?", (pid,)).fetchone()[0])
def bare(t): return re.sub(r"^(Element_|Shot_|Audio_)", "", t or "")
def cands_of(kes):
    seen, out = set(), []
    for ke in kes:
        raw = ke.get('title') or ''
        for x in (raw, bare(raw)):
            if len(x) >= 2 and x not in seen:
                seen.add(x); out.append(x)
    out.sort(key=len, reverse=True); return out

for pid, name in [('proj-1790091531-97d20b2d','2222'), ('proj-1790092267-a9abcb25','3333')]:
    st = load(pid); kes = st.get('keyElements') or []; shots = st.get('shots') or []
    cands = cands_of(kes)
    P("="*96); P("## %s" % name); P()
    P("[轴1] 前端内联块（descChipNames 候选 = keyElements 全集）")
    P("      候选数 = %d：%s" % (len(cands), json.dumps(cands, ensure_ascii=False)))
    hit_shots = sum(1 for g in shots if any(x in (g.get('desc') or '') for x in cands))
    hit_total = sum(sum(1 for x in cands if x in (g.get('desc') or '')) for g in shots)
    P("      => %d/%d 个 shot 至少命中 1 个块；总命中块数 = %d" % (hit_shots, len(shots), hit_total))
    P()
    P("[轴2] sceneRefs 存储形态（决定后端 resolve_scene_refs / resolve_scene_audio_refs）")
    refs = set()
    for g in shots:
        for r in (g.get('sceneRefs') or []): refs.add(r)
    titles = set(g.get('title') for g in kes); ids = set(g.get('id') for g in kes)
    P("      去重 refs = %d 个" % len(refs))
    P("      命中 KE 组标题 = %s" % json.dumps(sorted(refs & titles), ensure_ascii=False))
    P("      命中 KE 组 id   = %s" % json.dumps(sorted(refs & ids), ensure_ascii=False))
    P("      两者皆不命中（裸名/卡名） = %d 个：%s" % (len(refs - titles - ids),
                                                    json.dumps(sorted(refs - titles - ids), ensure_ascii=False)))
    ref_shots = 0
    for g in shots:
        ok = False
        for r in (g.get('sceneRefs') or []):
            for ke in kes:
                if ke.get('id') == r or ke.get('title') == r:
                    if any(d.get('imgUrl') for d in (ke.get('drafts') or [])): ok = True
                    break
        if ok: ref_shots += 1
    P("      => 按 resolve_scene_refs 口径能取到参考图的 shot 数 = %d/%d" % (ref_shots, len(shots)))
    P()
    P("[轴3] KE 卡 mediaType / prompt 长度 / imgUrl")
    from collections import Counter
    mt = Counter(); plen = []; imgs = 0
    for ke in kes:
        for d in (ke.get('drafts') or []):
            mt[d.get('mediaType')] += 1; plen.append(len(d.get('prompt') or ''))
            if d.get('imgUrl'): imgs += 1
    P("      mediaType 分布 = %s；卡数 = %d" % (dict(mt), sum(mt.values())))
    P("      prompt 长度 全部为 0 ？ %s（min=%s max=%s）" % (
        all(x == 0 for x in plen), min(plen) if plen else None, max(plen) if plen else None))
    P("      有 imgUrl 的卡 = %d" % imgs)
    P()
    P("[轴4] 组数对照")
    P("      keyElement 组数 = %d（%s）" % (len(kes), "一元素一组" if len(kes) > 5 else "粗组"))
    P("      shot 组数 = %d；audio 组数 = %d" % (len(shots), len(st.get('audioItems') or [])))
    P()

io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("written", OUT)
