"""Synchronous, standard-library-only MONA Cloud client."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, Mapping, Optional


DEFAULT_BASE_URL = "https://api.monacloud.vn"
TOP_UP_NEXT_STEP = "nạp ví tại https://monacloud.vn/console"
STATUS_CODES = {
    400: "bad_request",
    401: "auth_required",
    402: "insufficient_funds",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


class MonaCloudError(RuntimeError):
    """Structured API/transport error safe to return to an AI agent."""

    def __init__(
        self,
        code: str,
        message: str,
        next_step: str,
        *,
        status: Optional[int] = None,
        body: Any = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_step = next_step
        self.status = status
        self.body = body
        self.request_id = request_id

    def as_dict(self) -> Dict[str, str]:
        result = {
            "code": self.code,
            "message": self.message,
            "next_step": self.next_step,
        }
        if self.request_id:
            result["request_id"] = self.request_id
        return result


def _segment(value: Any, label: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError("{} không được để trống".format(label))
    return urllib.parse.quote(text, safe="")


def _as_dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_string(payload: Mapping[str, Any], key: str) -> Optional[str]:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    for container_name in ("detail", "error"):
        nested = _as_dict(payload.get(container_name))
        value = nested.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _validation_message(detail: Any) -> Optional[str]:
    if not isinstance(detail, list):
        return None
    messages = []
    for entry in detail:
        message = _as_dict(entry).get("msg")
        if isinstance(message, str) and message:
            messages.append(message)
    return "; ".join(messages) if messages else None


def _default_next_step(status: int) -> str:
    if status in (401, 403):
        return "kiểm tra token và quyền truy cập rồi thử lại"
    if status == 404:
        return "kiểm tra ID tài nguyên rồi thử lại"
    if status in (400, 409, 422):
        return "kiểm tra tham số request rồi thử lại"
    if status == 429:
        return "chờ một lúc rồi thử lại"
    if status >= 500:
        return "kiểm tra trạng thái MONA Cloud rồi thử lại"
    return "kiểm tra request rồi thử lại"


def _api_error(
    status: int,
    payload: Any,
    request_id: Optional[str] = None,
) -> MonaCloudError:
    parsed = _as_dict(payload)
    detail = parsed.get("detail")
    code = (
        "insufficient_funds"
        if status == 402
        else _nested_string(parsed, "code")
        or STATUS_CODES.get(status)
        or "http_{}".format(status)
    )
    message = (
        _nested_string(parsed, "message")
        or (detail if isinstance(detail, str) and detail else None)
        or _validation_message(detail)
        or "MONA Cloud API lỗi HTTP {}".format(status)
    )
    next_step = (
        TOP_UP_NEXT_STEP
        if status == 402
        else _nested_string(parsed, "next_step") or _default_next_step(status)
    )
    return MonaCloudError(
        code,
        message,
        next_step,
        status=status,
        body=payload,
        request_id=request_id or _nested_string(parsed, "request_id"),
    )


class MonaCloud:
    """Client for the MONA Cloud public automation API."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        sandbox: bool = False,
        timeout: float = 30.0,
        *,
        opener: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token là bắt buộc")
        if timeout <= 0:
            raise ValueError("timeout phải lớn hơn 0")
        self.token = token.strip()
        self.base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.sandbox = bool(sandbox)
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen

    def prices(self) -> Any:
        return self._request("GET", "/api/prices")

    def packages(self) -> Any:
        return self._request("GET", "/api/packages")

    def create_vps(
        self,
        payload: Mapping[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Any:
        return self._request(
            "POST",
            "/api/lxc",
            body=payload,
            headers={"Idempotency-Key": idempotency_key or str(uuid.uuid4())},
        )

    def create_database(
        self,
        payload: Mapping[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Any:
        return self._request(
            "POST",
            "/api/databases",
            body=payload,
            headers={"Idempotency-Key": idempotency_key or str(uuid.uuid4())},
        )

    def job(self, job_id: str) -> Any:
        return self._request("GET", "/api/jobs/" + _segment(job_id, "job id"))

    def wait_job(
        self,
        job_id: str,
        timeout: float = 300.0,
        poll_interval: float = 1.0,
    ) -> Any:
        if timeout < 0:
            raise ValueError("timeout phải là số không âm")
        if poll_interval < 0:
            raise ValueError("poll_interval phải là số không âm")
        started_at = time.monotonic()
        while True:
            current = self.job(job_id)
            status = current.get("status") if isinstance(current, Mapping) else None
            if status in ("succeeded", "done"):
                return current
            if status in ("failed", "cancelled"):
                raise MonaCloudError(
                    "job_cancelled" if status == "cancelled" else "job_failed",
                    current.get("error") or "Job {} {}".format(job_id, status),
                    "tạo một job mới"
                    if status == "cancelled"
                    else "kiểm tra job.error rồi tạo lại tài nguyên",
                    body=current,
                )
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                raise MonaCloudError(
                    "wait_timeout",
                    "Job {} chưa hoàn tất sau {} giây".format(job_id, timeout),
                    "gọi job(id) để tiếp tục kiểm tra trạng thái",
                    body=current,
                )
            time.sleep(min(poll_interval, max(0.0, timeout - elapsed)))

    def services(self) -> Any:
        return self._request("GET", "/api/services")

    def start_service(self, service_id: str) -> Any:
        return self._request(
            "POST", "/api/services/{}/start".format(_segment(service_id, "service id"))
        )

    def stop_service(self, service_id: str) -> Any:
        return self._request(
            "POST", "/api/services/{}/stop".format(_segment(service_id, "service id"))
        )

    def rebuild_service(self, service_id: str) -> Any:
        return self._request(
            "POST", "/api/services/{}/rebuild".format(_segment(service_id, "service id"))
        )

    def delete_service(self, service_id: str) -> Any:
        return self._request(
            "DELETE", "/api/services/{}".format(_segment(service_id, "service id"))
        )

    def me(self) -> Any:
        return self._request("GET", "/api/me")

    # CamelCase aliases keep the method names identical across all three SDKs.
    createVps = create_vps
    createDatabase = create_database
    waitJob = wait_job
    startService = start_service
    stopService = stop_service
    rebuildService = rebuild_service
    deleteService = delete_service

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self.token,
        }
        if self.sandbox:
            request_headers["X-Vibecloud-Sandbox"] = "1"
        if headers:
            request_headers.update(headers)
        encoded_body = None
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded_body,
            headers=request_headers,
            method=method,
        )
        try:
            response = self._opener(request, timeout=self.timeout)
            try:
                status_value = getattr(response, "status", None)
                if status_value is None:
                    status_value = response.getcode()
                status = int(status_value)
                raw = response.read()
                response_headers = getattr(response, "headers", {})
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as error:
            status = int(error.code)
            try:
                raw = error.read()
                response_headers = error.headers or {}
            finally:
                error.close()
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise MonaCloudError(
                "network_error",
                "Không kết nối được MONA Cloud: {}".format(reason),
                "kiểm tra kết nối mạng và base_url rồi thử lại",
            ) from error

        text = raw.decode("utf-8", errors="replace") if raw else ""
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as error:
                if status < 200 or status >= 300:
                    payload = {"message": text[:1000]}
                else:
                    raise MonaCloudError(
                        "invalid_json",
                        "MONA Cloud trả response không phải JSON (HTTP {})".format(status),
                        "kiểm tra base_url hoặc trạng thái API rồi thử lại",
                        status=status,
                        body=text,
                    ) from error
        else:
            payload = {}

        if status < 200 or status >= 300:
            get_header = getattr(response_headers, "get", lambda _name: None)
            raise _api_error(status, payload, get_header("x-request-id"))
        return payload
