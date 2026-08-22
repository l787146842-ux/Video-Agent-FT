import sqlite3, json
p = r"C:\Users\ASUS\AppData\Roaming\qoder\SharedClientCache\cache\db\local.db"
c = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
print("chat_session grouped by user/type/status")
for row in c.execute("select user_id,session_type,mode,status,count(*) from chat_session group by user_id,session_type,mode,status order by max(gmt_modified) desc"):
    print(row)
print("\nrecent sessions")
for row in c.execute("select session_id,user_id,session_title,project_uri,session_type,mode,status,gmt_create,gmt_modified from chat_session order by gmt_modified desc limit 30"):
    print(row)
print("\nper-user child counts")
for uid in [r[0] for r in c.execute("select distinct user_id from chat_session")]:
    print("USER",uid)
    for t in ["chat_session","chat_record","chat_message","chat_snapshot","chat_working_space_file","task_tree","chat_goal","goal","session_notification","broker_session_mapping","sync_metadata"]:
        cols=[r[1] for r in c.execute("pragma table_info("+t+")")]
        if "session_id" in cols:
            # map via chat_session ids for child tables
            q="select count(*) from "+t+" where session_id in (select session_id from chat_session where user_id=?)"
            print(t,c.execute(q,(uid,)).fetchone()[0])
