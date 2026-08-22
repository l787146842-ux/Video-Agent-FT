from pathlib import Path
p=Path(r"C:\Program Files\Qoder\resources\app\resources\bin\x86_64_windows\Qoder.exe")
b=p.read_bytes()
for off in [69673000,69673500,69673954,69674097,50890000,52337000,52352000,52357000,52298000]:
    print("\n###",off)
    chunk=b[max(0,off-1200):off+5000]
    cur=[]
    for x in chunk:
        if 32<=x<127:
            cur.append(chr(x))
        else:
            if len(cur)>=4: print(''.join(cur))
            cur=[]
    if len(cur)>=4: print(''.join(cur))
