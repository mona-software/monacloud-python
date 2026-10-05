# monacloud

Zero-dependency Python SDK for the MONA Cloud compute API: create VPS and databases, wait for jobs and manage services.

The synchronous client uses `urllib` from the standard library, runs on Python 3.9+ and calls `https://api.monacloud.vn` by default.

## Install

```bash
pip install monacloud
```

## Quick start

```python
import os
from monacloud import MonaCloud

token = os.environ["MONACLOUD_TOKEN"]

# Sandbox: simulates the call without creating infrastructure
sandbox = MonaCloud(token=token, sandbox=True)
preview = sandbox.create_vps({"app_name": "demo-app", "package_slug": "standard-1"})
preview_done = sandbox.wait_job(preview["id"], timeout=60)
print("sandbox:", preview_done["result"])

# Real call
cloud = MonaCloud(token=token)
job = cloud.create_vps({"app_name": "demo-app", "package_slug": "standard-1"})
done = cloud.wait_job(job["id"], timeout=600)
print("result:", done["result"])
```

## Usage

```python
MonaCloud(token, base_url="https://api.monacloud.vn", sandbox=False, timeout=30.0)
```

| Method | Description |
|---|---|
| `prices()`, `packages()` | Unit prices and preset packages |
| `me()` | Current account |
| `create_vps(payload, idempotency_key=None)` | Create a VPS; returns a job |
| `create_database(payload, idempotency_key=None)` | Create a database; returns a job |
| `job(job_id)` | Read a job |
| `wait_job(job_id, timeout=300.0, poll_interval=1.0)` | Poll until the job succeeds; raises on failure, cancellation or timeout |
| `services()` | List services |
| `start_service(id)`, `stop_service(id)`, `rebuild_service(id)`, `delete_service(id)` | Service lifecycle |

`create_vps()` and `create_database()` send an `Idempotency-Key` header, generated unless you pass `idempotency_key`.

### Errors

Every API or transport error is a `MonaCloudError` with `code`, `message`, `next_step`, `status`, `body` and `request_id`; `as_dict()` returns a JSON-safe summary.

## Configuration

- `token`: a MONA Pass access token or a `vc_live_*` key.
- `sandbox=True` sends the `X-Vibecloud-Sandbox: 1` header on every request.
- `timeout` is the per-request HTTP timeout in seconds.

Guide for AI agents: [monacloud.vn/ai-agent](https://monacloud.vn/ai-agent).

## Development

```bash
python -m unittest
```

## License

MIT

**MONA Cloud SDK is part of MONA Cloud by The MONA Group.**
