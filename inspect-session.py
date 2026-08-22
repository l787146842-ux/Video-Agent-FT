import sqlite3,json
p=r"C:\Users\ASUS\AppData\Roaming\qoder\SharedClientCache\cache\db\local.db"
c=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
sid="4a219fbf-3b59-45dc-8b44-5b344f7daf62"
for t in ["chat_session","chat_record","chat_message","chat_snapshot","chat_working_space_file","chat_working_space_file_reference","session_notification","task_tree","chat_goal","goal","broker_session_mapping","sync_metadata"]:
 rows=c.execute("select * from "+t+" where session_id=?",(sid,)).fetchall() if "session_id" in [x[1] for x in c.execute("pragma table_info("+t+")")] else []
 print("\n##",t,"count",len(rows))
 for row in rows[:3]:
  print(json.dumps(row,ensure_ascii=False,default=str)[:4000])

