"""临时测试脚本：查找 ModelScope 视频模型正确 ID"""
import httpx

base = "https://api-inference.modelscope.cn/v1"
key = "ms-925fe205-02dc-4658-960a-e0f5012d2a9f"
headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# 1. 尝试获取模型列表
r = httpx.get(f"{base}/models", headers=headers, timeout=10)
print("GET /models:", r.status_code)
if r.status_code == 200:
    data = r.json()
    models = data.get("data", [])
    video_kw = ["video", "wan", "t2v", "i2v", "happyhorse"]
    video_models = [m for m in models if any(kw in str(m.get("id", "")).lower() for kw in video_kw)]
    print(f"Total models: {len(models)}, Video-related: {len(video_models)}")
    for m in video_models[:30]:
        print(f"  {m.get('id')}")
else:
    print(r.text[:300])

# 2. 尝试不同模型 ID 格式
print("\n--- Testing video model IDs ---")
test_ids = [
    "Wan-AI/Wan2.1-T2V-14B",
    "wan2.1-t2v-14b",
    "Wan2.1-T2V-14B-720P",
    "happyhorse-1.1-t2v",
    "wan-t2v",
]
for mid in test_ids:
    payload = {"model": mid, "input": {"prompt": "a cat walking"}, "parameters": {"duration": 5}}
    try:
        r2 = httpx.post(f"{base}/videos/generations", json=payload, headers=headers, timeout=10)
        msg = r2.text[:200]
        print(f"  {mid} -> {r2.status_code}: {msg}")
    except Exception as e:
        print(f"  {mid} -> ERROR: {e}")
