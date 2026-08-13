# -*- coding: utf-8 -*-
"""一次性排查脚本：7777 项目聊天/结构/规格文档概览"""
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

P = r'e:\07 天问\自己做agent\workspace\projects\proj-1786216737-daadd8fe\state.json'
d = json.load(open(P, encoding='utf-8'))

ch = d['chatMessages']
print('=== chatMessages:', len(ch), '===')
if ch:
    print('sample keys:', list(ch[0].keys()))
for i, m in enumerate(ch):
    c = str(m.get('content') or m.get('text') or '')
    role = m.get('role') or m.get('sender')
    flag = 'JSON!' if ('"tool"' in c or '"status"' in c) else ''
    print('----', i, role, len(c), flag)
    if flag or len(c) < 300:
        print(c[:2000])

print()
print('=== keyElements ===')
for g in d.get('keyElements', []):
    drafts = g.get('drafts', [])
    print(g.get('group_id'), '|', g.get('title'), '| drafts:', len(drafts),
          '| prompts:', sum(1 for x in drafts if (x.get('prompt') or '').strip()))

print()
print('=== shots ===')
for g in d.get('shots', []):
    drafts = g.get('drafts', [])
    for x in drafts:
        print(g.get('group_id'), '|', (g.get('title') or '')[:20], '|',
              x.get('draft_id'), '| prompt_len:', len(x.get('prompt') or ''),
              '| duration:', x.get('duration'))

print()
print('=== documents ===')
for doc in d.get('documents', []):
    print(json.dumps(doc, ensure_ascii=False)[:4000])

print()
print('=== usedSkills ===')
print(d.get('usedSkills'))

print()
print('=== interaction ===')
it = d.get('interaction') or {}
print(json.dumps({k: (v if not isinstance(v, (dict, list)) else type(v).__name__)
                  for k, v in it.items()}, ensure_ascii=False))
