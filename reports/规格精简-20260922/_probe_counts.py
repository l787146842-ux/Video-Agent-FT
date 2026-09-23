# -*- coding: utf-8 -*-
import os, io, sys
TERMS=["效率","一次性","一起问","打包","预收","合并"]
ROOTS=[r"prompts",r"src\video_agent"]
EXTS={".md",".py",".txt",".json",".yaml",".yml",".toml"}
SKIP={"__pycache__",".git","node_modules"}
out=io.StringIO()
per={t:{} for t in TERMS}
for root in ROOTS:
    for dp,dn,fns in os.walk(root):
        dn[:]=[d for d in dn if d not in SKIP]
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() not in EXTS: continue
            fp=os.path.join(dp,fn).replace("\\","/")
            try: ls=open(fp,encoding="utf-8",errors="replace").read().split("\n")
            except: continue
            for i,ln in enumerate(ls,1):
                for t in TERMS:
                    if t in ln: per[t].setdefault(fp,[]).append(i)
for t in TERMS:
    tot=sum(len(v) for v in per[t].values())
    out.write("【%s】命中 %d 行 / %d 文件\n" % (t,tot,len(per[t])))
    for fp,ns in sorted(per[t].items()):
        out.write("    %s : %s\n" % (fp, ns))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
