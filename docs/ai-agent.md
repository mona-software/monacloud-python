# MONA Cloud SDK cho AI agent — Python

Khởi tạo `MonaCloud` với token Bearer. Luôn chạy `sandbox=True` trước khi tạo tài nguyên thật; SDK sẽ gửi header kỹ thuật `X-Vibecloud-Sandbox: 1`.

```python
import os
from monacloud import MonaCloud

cloud = MonaCloud(token=os.environ["MONACLOUD_TOKEN"], sandbox=True)
job = cloud.create_vps({"app_name": "agent-demo", "package_slug": "standard-1"})
result = cloud.wait_job(job["id"])
print(result)
```

API mặc định: `https://api.monacloud.vn`. Xem quy trình đầy đủ tại `https://monacloud.vn/ai-agent`.
