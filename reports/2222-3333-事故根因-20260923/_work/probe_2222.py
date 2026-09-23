# -*- coding: utf-8 -*-
"""2222 取证：只读。从 state.sqlite3 抽取 4 项事实 + 前端 descChipNames 命中模拟。"""
import sqlite3, json, io, re, os

OUT = os.path.join(os.path.dirname(__file__), "probe_2222_out.txt")
lines = []
def P(s=""):
    lines.append(str(s))

c = sqlite3.connect(r'workspace/state.sqlite3')
row = c.execute("select state from projects where id=?", ('proj-1790091531-97d20b2d',)).fetchone()
st = json.loads(row[0])

P("### A. keyElements 分组（组数=%d）" % len(st.get('keyElements') or []))
for g in st.get('keyElements') or []:
    P("- id=%s title=%r drafts=%d" % (g.get('id'), g.get('title'), len(g.get('drafts') or [])))
    for d in g.get('drafts') or []:
        P("    · label=%r mediaType=%r tag=%r id=%s prompt_len=%d desc_len=%d" % (
            d.get('label'), d.get('mediaType'), d.get('tag'), d.get('id'),
            len(d.get('prompt') or ''), len(d.get('desc') or '')))

P()
P("### B. audioItems 分组（组数=%d）" % len(st.get('audioItems') or []))
for g in st.get('audioItems') or []:
    P("- id=%s title=%r drafts=%d" % (g.get('id'), g.get('title'), len(g.get('drafts') or [])))
    for d in g.get('drafts') or []:
        P("    · label=%r mediaType=%r tag=%r id=%s" % (d.get('label'), d.get('mediaType'), d.get('tag'), d.get('id')))

P()
P("### C. shots 分组（组数=%d）" % len(st.get('shots') or []))

tok_re = re.compile(r"\[([^\[\]]{1,60})\]")
def bare(t):
    return re.sub(r"^(Element_|Shot_|Audio_)", "", t or "")

# 模拟前端 descChipNames 候选
cands = []
seen = set()
for ke in st.get('keyElements') or []:
    raw = ke.get('title') or ''
    if not raw:
        continue
    if len(raw) >= 2 and raw not in seen:
        seen.add(raw); cands.append(raw)
    b = bare(raw)
    if len(b) >= 2 and b not in seen:
        seen.add(b); cands.append(b)
cands.sort(key=len, reverse=True)
P("前端内联块候选名（descChipNames，按长度降序）= %s" % json.dumps(cands, ensure_ascii=False))
P()

total_tokens = 0
total_chip_hits = 0
P("| # | 组标题 | 时长 | summary | 内切x,desc计数 | desc内'[xx]'令牌 | sceneRefs | 候选名命中 |")
P("|---|---|---|---|---|---|---|---|")
for i, g in enumerate(st.get('shots') or [], 1):
    desc = g.get('desc') or ''
    summ = g.get('summary') or ''
    toks = tok_re.findall(desc)
    total_tokens += len(toks)
    # 内切计数
    nqie = len(re.findall(r"内切", desc))
    nqie_num = len(re.findall(r"内切\s*\d+", desc))
    hits = [cn for cn in cands if cn in desc]
    total_chip_hits += len(hits)
    P("| %d | %s | %s | %s | 出现'内切'%d次/编号%d个 | %s | %s | %s |" % (
        i, g.get('title'), g.get('duration'), summ, nqie, nqie_num,
        json.dumps(toks, ensure_ascii=False) if toks else "0（零）",
        json.dumps(g.get('sceneRefs'), ensure_ascii=False),
        json.dumps(hits, ensure_ascii=False) if hits else "0（零）"))

P()
P("统计：全部 %d 个 shot，desc 中 [元素名] 令牌总数 = %d；候选名命中总数 = %d" % (
    len(st.get('shots') or []), total_tokens, total_chip_hits))

P()
P("### D. 逐镜 summary 声称内切数 vs desc 实际内切镜头数（对照表）")
P("| # | 组标题 | summary | summary声称内切数 | desc正文内切语句数 | desc是否含'内切1' | 一致? |")
P("|---|---|---|---|---|---|---|")
mism = 0
for i, g in enumerate(st.get('shots') or [], 1):
    desc = g.get('desc') or ''
    summ = g.get('summary') or ''
    m = re.search(r"含\s*(\d+)\s*个内切", summ)
    claim = int(m.group(1)) if m else (0 if "单个" in summ else None)
    actual = len(re.findall(r"内切\s*\d+", desc))
    has1 = "内切1" in desc
    ok = (claim is not None and claim == actual)
    if not ok:
        mism += 1
    P("| %d | %s | %s | %s | %d | %s | %s |" % (
        i, g.get('title'), summ, claim, actual, has1, "一致" if ok else "**不一致**"))
P()
P("不一致镜数 = %d / %d" % (mism, len(st.get('shots') or [])))

P()
P("### E. shot 组标题去掉前缀后的裸名（用于比对 sceneRefs 是否同字符串）")
P(json.dumps([bare(g.get('title')) for g in (st.get('shots') or [])], ensure_ascii=False))

P()
P("### F. 全部 sceneRefs 去重集合")
refs = set()
for g in st.get('shots') or []:
    for r in (g.get('sceneRefs') or []):
        refs.add(r)
P(json.dumps(sorted(refs), ensure_ascii=False))

P()
P("### G. keyElement 卡 label 全集（与 sceneRefs 比对）")
labels = set()
for g in st.get('keyElements') or []:
    for d in g.get('drafts') or []:
        labels.add(d.get('label'))
P(json.dumps(sorted(labels), ensure_ascii=False))
P("sceneRefs 命中卡 label 的 = %s" % json.dumps(sorted(refs & labels), ensure_ascii=False))
P("sceneRefs 不命中卡 label 的 = %s" % json.dumps(sorted(refs - labels), ensure_ascii=False))
P("keyElement 中不含 Element_ 前缀的组标题数 = %d / %d" % (
    sum(1 for g in (st.get('keyElements') or []) if not (g.get('title') or '').startswith("Element_")),
    len(st.get('keyElements') or [])))
P("shot 组中标题以 Shot_ 开头的 = %d / %d" % (
    sum(1 for g in (st.get('shots') or []) if (g.get('title') or '').startswith("Shot_")),
    len(st.get('shots') or [])))
P("audio 组标题 = %s" % json.dumps([g.get('title') for g in (st.get('audioItems') or [])], ensure_ascii=False))

io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("written", OUT, len(lines), "lines")
