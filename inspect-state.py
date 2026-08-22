import sqlite3
paths=[r"C:\Users\ASUS\AppData\Roaming\qoder\User\globalStorage\state.vscdb"]
for p in paths:
 print("##",p)
 c=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
 print(list(c.execute("select name,sql from sqlite_master where type='table'")))
 for row in c.execute("select key,value from ItemTable where key like '%quest%' or key like '%task%' or key like '%account%' or key like '%session%' order by key"):
  print(row[0], (row[1] or '')[:10000])
