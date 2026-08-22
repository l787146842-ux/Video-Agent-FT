from pathlib import Path
import re
p=Path(r"C:\Program Files\Qoder\resources\app\resources\bin\x86_64_windows\Qoder.exe")
b=p.read_bytes()
for m in re.finditer(rb"[ -~]{8,}", b):
    s=m.group().decode('ascii','replace')
    if any(x.lower() in s.lower() for x in ["chat/getSessionById","chat/listAllSessions","session_id = ?","user_id = ?","chat_session WHERE","fork source hydrate","move_to_local","attach"]):
        print(m.start(), s[:2000])
