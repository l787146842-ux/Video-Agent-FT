# 画布（画布）API 契约夹具

本目录存放从真实画布服务录制的只读响应（GET），供 `tests/integration/test_canvas_contract.py` 使用。

## 文件

| 文件 | 来源 |
|---|---|
| `app_info.json` | `GET /api/app-info` |
| `canvases_list.json` | `GET /api/canvases` |
| `canvas_detail_smart.json` | `GET /api/canvases/{id}`（取一个未删除的智能画布） |

## 何时刷新

对接新版画布后（`data/canvas_integration.json` 记录版本，启动时漂移会 warning），重新录制本目录文件。
**刷新后的 git diff 即 schema 风险清单**：凡是被删除/改名的字段，若 adapter 有依赖，必须同步修改。

## 如何刷新

画布运行中执行（纯 GET，不写入任何数据）：

```bash
python -c "
import json, urllib.request, pathlib
out = pathlib.Path('tests/fixtures/canvas')
def get(p):
    with urllib.request.urlopen('http://127.0.0.1:3000'+p, timeout=5) as r:
        return json.loads(r.read().decode('utf-8'))
(out/'app_info.json').write_text(json.dumps(get('/api/app-info'), ensure_ascii=False, indent=2), encoding='utf-8')
cs = get('/api/canvases')
(out/'canvases_list.json').write_text(json.dumps(cs, ensure_ascii=False, indent=2), encoding='utf-8')
for c in cs.get('canvases') or []:
    if not c.get('deleted_at') and str(c.get('kind') or '').lower() == 'smart':
        (out/'canvas_detail_smart.json').write_text(json.dumps(get('/api/canvases/'+c['id']), ensure_ascii=False, indent=2), encoding='utf-8')
        break
"
```
