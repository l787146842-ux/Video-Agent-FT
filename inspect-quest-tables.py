import sqlite3,json
p=r"C:\Users\ASUS\AppData\Roaming\qoder\SharedClientCache\cache\db\local.db"
c=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
sid="4a219fbf-3b59-45dc-8b44-5b344f7daf62"
for t in ["local_execution","pending_tool_interaction","resource_snapshot","session_notification","task_tree","broker_session_mapping","chat_session","sync_metadata"]:
 print("\n## "+t)
 print("schema",list(c.execute("pragma table_info("+t+")")))
 cols=[x[1] for x in c.execute("pragma table_info("+t+")")]
 if "session_id" in cols:
  rows=c.execute("select * from "+t+" where session_id=?",(sid,)).fetchall()
 elif "local_session_id" in cols:
  rows=c.execute("select * from "+t+" where local_session_id=?",(sid,)).fetchall()
 else: rows=[]
 print("count",len(rows))
 for row in rows[:5]: print(repr(row)[:5000])

