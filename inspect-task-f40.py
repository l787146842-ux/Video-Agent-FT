import sqlite3

p = r"C:\Users\ASUS\AppData\Roaming\qoder\SharedClientCache\cache\db\local.db"
s = "task-f40b419507f9429698bf.session.execution"
c = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
tables = [
    "chat_session", "local_execution", "task_tree", "chat_record", "chat_message",
    "chat_snapshot", "chat_working_space_file", "chat_goal", "session_notification",
    "broker_session_mapping", "sync_metadata", "resource_snapshot",
]
for t in tables:
    print("\n##", t)
    cols = [x[1] for x in c.execute("pragma table_info(" + t + ")")]
    print("columns", cols)
    if "session_id" in cols:
        rows = c.execute("select * from " + t + " where session_id=?", (s,)).fetchall()
    elif "local_session_id" in cols:
        rows = c.execute("select * from " + t + " where local_session_id=?", (s,)).fetchall()
    else:
        rows = []
    print("count", len(rows))
    for row in rows[:3]:
        out = []
        for x in row:
            if isinstance(x, (bytes, bytearray)):
                out.append("<bytes %d>" % len(x))
            elif isinstance(x, str) and len(x) > 1500:
                out.append(x[:1500] + "...")
            else:
                out.append(x)
        print(repr(tuple(out)))
