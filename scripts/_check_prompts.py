# -*- coding: utf-8 -*-
"""核查 7777 提示词是否符合 skill：@引用/时长/no subtitles/音频层/语言"""
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

P = r'e:\07 天问\自己做agent\workspace\projects\proj-1786216737-daadd8fe\state.json'
d = json.load(open(P, encoding='utf-8'))

ke_titles = [g.get('title') for g in d.get('keyElements', [])]
print('keyElement 分组数:', len(ke_titles))
badges = {}
for g in d.get('keyElements', []):
    b = g.get('badgeLabel') or g.get('badge') or '?'
    badges[b] = badges.get(b, 0) + 1
print('badgeLabel 分布:', badges)

shots = d.get('shots', [])
print()
print('shot 分组数:', len(shots))
for gi, g in enumerate(shots, 1):
    for x in g.get('drafts', []):
        p = x.get('prompt') or ''
        at = len(re.findall(r'@', p))
        print(f'--- 镜头{gi} {g.get("title")} | dur={x.get("duration")} | @数={at} | '
              f'no subtitles={("no subtitles" in p)} | no music={("no music" in p)} | '
              f'含{{对话}}={"{" in p} | 含<音效>={"<" in p}')
        if gi <= 2:
            print('PROMPT:', p)
        refs = g.get('sceneRefs') or []
        print('sceneRefs:', refs)

print()
print('=== 关键元素提示词示例（前2张）===')
for g in d.get('keyElements', [])[:2]:
    for x in g.get('drafts', []):
        print('---', g.get('title'))
        print((x.get('prompt') or '')[:600])
