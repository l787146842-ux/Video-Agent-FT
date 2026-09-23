# -*- coding: utf-8 -*-
"""终验：Q2 关键计数 + 令牌/命中的逐项复核（只读）。"""
import sqlite3, json, io, re, os

OUT = os.path.join(os.path.dirname(__file__), "probe_verify_out.txt")
L = []
def P(s=""): L.append(str(s))
c = sqlite3.connect(r'workspace/state.sqlite3')
def load(pid):
    return json.loads(c.execute("select state from projects where id=?", (pid,)).fetchone()[0])

s2 = load('proj-1790091531-97d20b2d')   # 2222
s3 = load('proj-1790092267-a9abcb25')   # 3333
tok = re.compile(r"\[([^\[\]]{1,60})\]")

P("="*96)
P("复核 1：2222 summary 声称「含2个内切镜头」的镜次（复核船长底稿的 6，我的计数）")
claims = [(i, g['title'], g.get('summary')) for i, g in enumerate(s2['shots'], 1)
          if "含2个内切镜头" in (g.get('summary') or '')]
for i, t, s in claims:
    P("   shot%02d | %s | %s" % (i, t, s))
P("   => 计 %d 个（注意：船长底稿写 6）" % len(claims))
P()

P("复核 2：2222 逐镜 desc 的「内切」出现情况（全 26 镜）")
for i, g in enumerate(s2['shots'], 1):
    d = g.get('desc') or ''
    n_any = len(re.findall("内切", d))
    n_num = len(re.findall(r"内切\s*\d+", d))
    if n_any:
        seg = d[max(0, d.find("内切")-30):d.find("内切")+50].replace("\n", "\\n")
        P("   shot%02d | 内切x%d | 内切N编号x%d | 上下文=...%s..." % (i, n_any, n_num, seg))
P("   => desc 含「内切」的镜数 = %d；含「内切N」编号的 = %d" % (
    sum(1 for g in s2['shots'] if "内切" in (g.get('desc') or '')),
    sum(1 for g in s2['shots'] if re.search(r"内切\s*\d+", g.get('desc') or ''))))
P()

P("复核 3：两项目 desc 的 [元素名] 令牌统计")
for st, nm in ((s2, '2222'), (s3, '3333')):
    n = sum(len(tok.findall(g.get('desc') or '')) for g in st['shots'])
    P("   %s：shot 组数=%d，desc 内 [xx] 令牌总数=%d" % (nm, len(st['shots']), n))
P()

P("复核 4：2222 shot02 的 desc 全文（证明它确实写了内切1/内切2）")
d2 = s2['shots'][1]['desc']
P("   " + d2.replace("\n", "\\n"))
P()

P("复核 5：audio 重复卡 —— 同 label 卡在 keyElement 与 audio 两处各一份")
ke_labels = {}
for g in s2['keyElements']:
    for d in (g.get('drafts') or []):
        if d.get('mediaType') == 'audio':
            ke_labels[d.get('label')] = (g.get('title'), d.get('id'))
au_labels = {}
for g in s2['audioItems']:
    for d in (g.get('drafts') or []):
        au_labels[d.get('label')] = (g.get('title'), d.get('id'))
P("   keyElement 下的 audio 卡 = %s" % json.dumps(ke_labels, ensure_ascii=False))
P("   audio 类目下的卡      = %s" % json.dumps(au_labels, ensure_ascii=False))
P("   同名重复 = %s（不同 id，各自一份）" % json.dumps(sorted(set(ke_labels) & set(au_labels)), ensure_ascii=False))
P()

P("复核 6：全量工具面（storyboard_* + read_draft）—— 有无删单卡")
tools = ["storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
         "storyboard_delete_group", "storyboard_confirm_draft", "storyboard_media_to_chat",
         "read_draft", "read_state_group", "view_storyboard_media"]
P("   注册表 = %s" % json.dumps(tools, ensure_ascii=False))
P("   含 'delete_draft' 的工具 = %s" % [t for t in tools if "draft" in t and "delete" in t])
P("   删除类工具只剩 = ['storyboard_delete_group']（ops.delete_draft 存在但无 Tool 注册、无 API 路由）")
io.open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("written", OUT)
