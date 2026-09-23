import json,sys,io
f=r"data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl"
buf=[]
txt=[]
for l in open(f,encoding="utf-8"):
    l=l.strip()
    if not l: continue
    o=json.loads(l)
    if "__chunk__" not in o: continue
    r=o.get("raw","")
    if not r.startswith("{"): continue
    try: d=json.loads(r)
    except: continue
    for ch in d.get("choices") or []:
        dl=ch.get("delta") or {}
        if dl.get("reasoning_content"): buf.append(dl["reasoning_content"])
        if dl.get("content"): txt.append(dl["content"])
rc="".join(buf); ct="".join(txt)
print("reasoning_delta_total_len =", len(rc))
print("content_delta_total_len   =", len(ct))
print("---- reasoning 前 600 字 ----")
print(rc[:600])
print("---- reasoning 后 400 字 ----")
print(rc[-400:])
print("---- content ----")
print(ct[:400])
print("为了效率 in reasoning?", "为了效率" in rc)
