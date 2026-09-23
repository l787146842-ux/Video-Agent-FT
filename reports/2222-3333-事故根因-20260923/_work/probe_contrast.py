# -*- coding: utf-8 -*-
"""3333 vs 2222 对比：descChipNames 命中 / sceneRefs 形态 / 标题前缀。只读。"""
import sqlite3, json, io, re, os

OUT = os.path.join(os.path.dirname(__file__), "probe_contrast_out.txt")
L = []
def P(s=""): L.append(str(s))
c = sqlite3.connect(r'workspace/state.sqlite3')

def load(pid):
    return json.loads(c.execute("select state from projects where id=?", (pid,)).fetchone()[0])

def bare(t):
    return re.sub(r"^(Element_|Shot_|Audio_)", "", t or "")

def cands_of(kes):
    seen, cands = set(), []
    for ke in kes:
        raw = ke.get('title') or ''
        if not raw: continue
        for x in (raw, bare(raw)):
            if len(x) >= 2 and x not in seen:
                seen.add(x); cands.append(x)
    cands.sort(key=len, reverse=True)
    return cands

for pid, name in [('proj-1790091531-97d20b2d','2222'), ('proj-1790092267-a9abcb25','3333')]:
    st = load(pid)
    kes = st.get('keyElements') or []
    cands = cands_of(kes)
    P("="*100)
    P("## 项目 %s (%s)" % (name, pid))
    P("keyElement 组数 = %d" % len(kes))
    P("组标题 = %s" % json.dumps([g.get('title') for g in kes], ensure_ascii=False))
    P("descChipNames 候选（%d 个）= %s" % (len(cands), json.dumps(cands[:20], ensure_ascii=False)))
    # 组内草稿 imgUrl 情况（决定内联块是否带缩略图）
    for g in kes[:3]:
        for d in (g.get('drafts') or [])[:2]:
            P("   样卡 %s/%s imgUrl=%r mediaType=%r" % (g.get('title'), d.get('label'), d.get('imgUrl'), d.get('mediaType')))
    # 逐 shot 命中
    tot = 0; totrefs = 0
    P("")
    P("| # | shot 标题 | desc长度 | 命中候选名数 | 命中名 | sceneRefs |")
    P("|---|---|---|---|---|---|")
    for i, g in enumerate(st.get('shots') or [], 1):
        d = g.get('desc') or ''
        hits = [x for x in cands if x in d]
        tot += len(hits); totrefs += len(g.get('sceneRefs') or [])
        P("| %d | %s | %d | %d | %s | %s |" % (
            i, (g.get('title') or '')[:34], len(d), len(hits),
            json.dumps(hits[:4], ensure_ascii=False) if hits else "0",
            json.dumps(g.get('sceneRefs'), ensure_ascii=False)))
    P("")
    P("合计：内联块候选命中 = %d；sceneRefs 项数 = %d" % (tot, totrefs))
    # sceneRefs 是否命中 KE 组标题 / id（后端 resolve_*_refs 用）
    refs = set()
    for g in st.get('shots') or []:
        for r in (g.get('sceneRefs') or []): refs.add(r)
    titles = set(g.get('title') for g in kes)
    ids = set(g.get('id') for g in kes)
    P("sceneRefs 去重 = %s" % json.dumps(sorted(refs), ensure_ascii=False))
    P("sceneRefs ∩ KE组标题 = %s" % json.dumps(sorted(refs & titles), ensure_ascii=False))
    P("sceneRefs ∩ KE id   = %s" % json.dumps(sorted(refs & ids), ensure_ascii=False))
    P("sceneRefs 裸名（既不命中标题也不命中 id） = %s" % json.dumps(sorted(refs - titles - ids), ensure_ascii=False))
    # 后端 resolve_scene_refs 实效：能否取到 imgUrl
    n_with_img = 0
    for g in st.get('shots') or []:
        hit = False
        for r in (g.get('sceneRefs') or []):
            for ke in kes:
                if ke.get('id') == r or ke.get('title') == r:
                    for d in (ke.get('drafts') or []):
                        if d.get('imgUrl'): hit = True; break
                    break
        if hit: n_with_img += 1
    P("按后端 resolve_scene_refs 口径，%d 镜中能解析出参考图的 = %d" % (len(st.get('shots') or []), n_with_img))
    P("")

io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("written", OUT)
