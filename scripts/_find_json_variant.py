# -*- coding: utf-8 -*-
"""在 traces/tasks 中搜索截图里的 JSON 变体来源"""
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

needles = ['slowly unfold', '"tool": "confirm"', '"status": "done"']

for path in [r'e:\07 天问\自己做agent\data\agent_traces.jsonl',
             r'e:\07 天问\自己做agent\data\agent_tasks.json']:
    print('=====', path)
    try:
        txt = open(path, encoding='utf-8').read()
    except FileNotFoundError:
        print('missing')
        continue
    for n in needles:
        i = txt.find(n)
        print(f'  needle {n!r}: found={i >= 0}')
        if i >= 0:
            print('  ctx:', txt[max(0, i - 300):i + 600].replace('\n', ' ')[:900])
            print('  ----')
