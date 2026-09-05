import io
import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from monacloud import MonaCloud, MonaCloudError


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers or {}

    def getcode(self):
        return self.status

    def read(self):
        return self._body

    def close(self):
        pass


class ApiContract:
    def __init__(self):
        self.job_polls = 0
        self.seen = []

    def route(self, method, path, headers, body):
        normalized = {name.lower(): value for name, value in headers.items()}
        self.seen.append((method, path, normalized, body))
        if normalized.get("authorization") != "Bearer vc_live_test":
            return 401, {"detail": "Invalid token"}
        if normalized.get("x-vibecloud-sandbox") != "1":
            return 400, {"detail": "Missing sandbox header"}
        if path == "/api/prices":
            return 200, {"prices": {"cpu_hour_vnd": 100}}
        if path == "/api/packages":
            return 200, {"packages": [{"slug": "standard-1"}]}
        if path == "/api/services" and method == "GET":
            return 200, [{"id": "svc-1", "kind": "lxc", "status": "active", "name": "demo-app"}]
        if path == "/api/services/svc-1/start":
            return 200, {"status": "running"}
        if path == "/api/services/svc-1/stop":
            return 200, {"status": "stopped"}
        if path == "/api/services/svc-1/rebuild":
            return 202, {"id": "job-rebuild", "type": "rebuild_lxc", "status": "queued"}
        if path == "/api/services/svc-1" and method == "DELETE":
            return 200, {"status": "destroyed"}
        if path == "/api/me":
            return 200, {"user": {"id": "user-1"}}
        if path == "/api/lxc" and method == "POST":
            assert body["app_name"] == "demo-app"
            assert normalized.get("idempotency-key")
            return 202, {
                "id": "job-1",
                "type": "create_lxc",
                "status": "queued",
                "sandbox": True,
            }
        if path == "/api/jobs/job-1":
            self.job_polls += 1
            if self.job_polls == 1:
                return 200, {"id": "job-1", "type": "create_lxc", "status": "running"}
            return 200, {
                "id": "job-1",
                "type": "create_lxc",
                "status": "done",
                "result": {"service_id": "svc-1"},
                "sandbox": True,
            }
        if path == "/api/databases":
            assert normalized.get("idempotency-key")
            return 402, {"detail": "Insufficient credit"}
        return 404, {"detail": "Not found"}


def make_handler(contract):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def do_DELETE(self):
            self._dispatch()

        def _dispatch(self):
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            status, payload = contract.route(self.command, self.path, self.headers, body)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("x-request-id", "req-test")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format, *args):
            pass

    return Handler


def fake_opener(contract):
    def open_request(request, timeout):
        headers = dict(request.header_items())
        body = json.loads(request.data) if request.data else None
        status, payload = contract.route(
            request.get_method(), request.full_url.split(".test", 1)[-1], headers, body
        )
        response = FakeResponse(status, payload, {"x-request-id": "req-test"})
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "mock error",
                response.headers,
                io.BytesIO(response._body),
            )
        return response

    return open_request


class MonaCloudTests(unittest.TestCase):
    def test_default_base_url(self):
        cloud = MonaCloud(token="vc_live_test", opener=lambda *_args, **_kwargs: None)
        self.assertEqual(cloud.base_url, "https://api.monacloud.vn")

    def test_http_contract_polling_and_402(self):
        contract = ApiContract()
        server = None
        thread = None
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(contract))
        except PermissionError:
            base_url = "http://mock.vibecloud.test"
            opener = fake_opener(contract)
        else:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = "http://127.0.0.1:{}".format(server.server_port)
            opener = None

        try:
            cloud = MonaCloud(
                token="vc_live_test",
                base_url=base_url,
                sandbox=True,
                opener=opener,
            )
            self.assertEqual(cloud.prices()["prices"]["cpu_hour_vnd"], 100)
            created = cloud.create_vps(
                {"app_name": "demo-app", "package_slug": "standard-1"}
            )
            self.assertEqual(created["id"], "job-1")
            done = cloud.wait_job("job-1", timeout=1, poll_interval=0.001)
            self.assertEqual(done["status"], "done")
            self.assertEqual(done["result"]["service_id"], "svc-1")
            self.assertEqual(cloud.packages()["packages"][0]["slug"], "standard-1")
            self.assertEqual(cloud.services()[0]["id"], "svc-1")
            self.assertEqual(cloud.start_service("svc-1")["status"], "running")
            self.assertEqual(cloud.stop_service("svc-1")["status"], "stopped")
            self.assertEqual(cloud.rebuild_service("svc-1")["id"], "job-rebuild")
            self.assertEqual(cloud.delete_service("svc-1")["status"], "destroyed")
            self.assertEqual(cloud.me()["user"]["id"], "user-1")

            with self.assertRaises(MonaCloudError) as caught:
                cloud.create_database(
                    {"app_name": "no-credit", "package_slug": "standard-1"}
                )
            error = caught.exception
            self.assertEqual(error.code, "insufficient_funds")
            self.assertEqual(error.message, "Insufficient credit")
            self.assertEqual(error.next_step, "nạp ví tại https://monacloud.vn/console")
            self.assertEqual(error.status, 402)
            self.assertEqual(error.request_id, "req-test")
            self.assertGreaterEqual(len(contract.seen), 12)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_camel_case_aliases_exist(self):
        for name in (
            "createVps",
            "createDatabase",
            "waitJob",
            "startService",
            "stopService",
            "rebuildService",
            "deleteService",
        ):
            self.assertTrue(callable(getattr(MonaCloud, name)))


if __name__ == "__main__":
    unittest.main()
