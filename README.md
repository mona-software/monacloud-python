# monacloud

SDK Python chính thức, zero-dependency, cho MONA Cloud. Client đồng bộ dùng `urllib` trong standard library, chạy trên Python 3.9+ và mặc định gọi `https://api.monacloud.vn`.

## Cài đặt

```bash
pip install monacloud
```

## Deploy app và đợi job

```python
import os
from monacloud import MonaCloud

token = os.environ["MONACLOUD_TOKEN"]
sandbox = MonaCloud(token=token, sandbox=True)
preview = sandbox.create_vps({"app_name": "demo-app", "package_slug": "standard-1"})
preview_done = sandbox.wait_job(preview["id"], timeout=60)
print("sandbox:", preview_done["result"])

cloud = MonaCloud(token=token)
job = cloud.create_vps({"app_name": "demo-app", "package_slug": "standard-1"})
done = cloud.wait_job(job["id"], timeout=600)
print("production:", done["result"])
```

Client hỗ trợ `prices`, `packages`, tạo VPS/database, đọc và chờ job, list/start/stop/rebuild/delete service và `me`. Mọi lỗi API là `MonaCloudError` với `code`, `message`, `next_step`, `status` và `body`.

Sandbox vẫn dùng header kỹ thuật `X-Vibecloud-Sandbox: 1`; token `vc_live_*` tiếp tục tương thích.

## Test offline

```bash
python -m unittest
```

Xem [hướng dẫn AI agent](https://monacloud.vn/ai-agent).
