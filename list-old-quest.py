import sqlite3,datetime,json
p=r"C:\Users\ASUS\AppData\Roaming\qoder\SharedClientCache\cache\db\local.db"
c=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
uid="01a02518-7ca4-70b6-a824-e91400661f85"
rows=c.execute("select session_id,user_id,user_name,session_title,project_uri,project_name,gmt_create,gmt_modified,session_type,mode,version,status,last_user_query_at,stop_reason,extra from chat_session where user_id=? and (session_type='quest' or mode='long_running') order by gmt_modified desc",(uid,)).fetchall()
for r in rows:
 print("\n",r[:15])
 for ts in [r[6],r[7],r[12]]:
  if ts: print(datetime.datetime.fromtimestamp(ts/1000),end=" ")
 print()
