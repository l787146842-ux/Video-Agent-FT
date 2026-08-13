"""一次性修复脚本：还原 api_providers.json 中被破坏的 ComfyUI prompt 转义"""
import json

path = r"e:\07 天问\自己做agent\data\api_providers.json"

try:
    json.load(open(path, encoding="utf-8"))
    print("JSON valid, nothing to do")
    raise SystemExit(0)
except Exception as e:
    print("INVALID:", e)

data = open(path, "rb").read()
marker = 'RH_RhartVideoGImageToVideo\\"'.encode("utf-8")
i = data.find(marker)
print("corrupted occurrence idx:", i)

# 定位损坏区域：从该 prompt 字符串起点到其结束引号。
# 损坏的字符串跨多行，把区域内真实换行还原为 \n 转义即可。
# 起点：该行的 "prompt": " 之后
line_start = data.rfind(b"\n", 0, i) + 1
# 终点：找到 '}}}"' + 换行 的收尾
end_marker = b'}}}"\n'
line_end = data.find(end_marker, i)
assert line_end != -1, "end marker not found"
line_end += len(end_marker) - 1  # 保留末尾换行

region = data[line_start:line_end]
fixed = region.replace(b"\r\n", b"\\n").replace(b"\n", b"\\n")
new_data = data[:line_start] + fixed + data[line_end:]

# 校验修复结果
try:
    json.loads(new_data.decode("utf-8"))
    print("FIXED & valid")
    open(path, "wb").write(new_data)
    print("written")
except Exception as e:
    print("still invalid:", e)
