import io
import json
import zipfile

import pytest

from review.mineru_client import MinerUClient


class _Response:
    def __init__(self, payload=None, *, status_code=200, content=b"", text=""):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Http:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        return response

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._next("PUT", url, **kwargs)

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)


def _zip_payload(filename="full.md", text="# OCR\n\n系统用户清单"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, text)
    return buffer.getvalue()


def test_lightweight_signed_upload_poll_and_download(tmp_path):
    source = tmp_path / "scan.png"
    source.write_bytes(b"image-bytes")
    http = _Http([
        _Response({"code": 0, "data": {"task_id": "task-1", "file_url": "https://upload.invalid/signed"}}),
        _Response({}, status_code=200),
        _Response({"code": 0, "data": {"task_id": "task-1", "state": "running"}}),
        _Response({"code": 0, "data": {"task_id": "task-1", "state": "done", "markdown_url": "https://cdn.invalid/result.md"}}),
        _Response({}, text="# OCR\n\n系统用户清单"),
    ])
    client = MinerUClient(
        mode="lightweight",
        http=http,
        poll_interval=0,
        max_wait_seconds=2,
        sleep=lambda _: None,
    )

    result = client.parse_file(source, language="ch", is_ocr=True, page_range="1-2")

    assert result.status == "ok"
    assert result.text == "# OCR\n\n系统用户清单"
    assert result.provider == "mineru-lightweight"
    assert [call[0:2] for call in http.calls] == [
        ("POST", "https://mineru.net/api/v1/agent/parse/file"),
        ("PUT", "https://upload.invalid/signed"),
        ("GET", "https://mineru.net/api/v1/agent/parse/task-1"),
        ("GET", "https://mineru.net/api/v1/agent/parse/task-1"),
        ("GET", "https://cdn.invalid/result.md"),
    ]
    assert http.calls[0][2]["json"] == {
        "file_name": "scan.png",
        "language": "ch",
        "enable_table": True,
        "is_ocr": True,
        "enable_formula": True,
        "page_range": "1-2",
    }
    assert http.calls[1][2]["data"] == b"image-bytes"


def test_precise_signed_upload_polls_batch_and_extracts_full_markdown(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"pdf-bytes")
    http = _Http([
        _Response({"code": 0, "data": {"batch_id": "batch-1", "file_urls": ["https://upload.invalid/precise"]}}),
        _Response({}, status_code=200),
        _Response({"code": 0, "data": {"batch_id": "batch-1", "extract_result": [{"file_name": "scan.pdf", "state": "running"}]}}),
        _Response({"code": 0, "data": {"batch_id": "batch-1", "extract_result": [{"file_name": "scan.pdf", "state": "done", "full_zip_url": "https://cdn.invalid/result.zip"}]}}),
        _Response({}, content=_zip_payload()),
    ])
    client = MinerUClient(
        mode="precise",
        token="test-token",
        http=http,
        poll_interval=0,
        max_wait_seconds=2,
        sleep=lambda _: None,
    )

    result = client.parse_file(source, language="ch", is_ocr=True, page_range="1-2")

    assert result.status == "ok"
    assert result.text == "# OCR\n\n系统用户清单"
    assert result.provider == "mineru-precise"
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer test-token"
    assert http.calls[0][2]["json"] == {
        "files": [{
            "name": "scan.pdf",
            "is_ocr": True,
            "page_ranges": "1-2",
        }],
        "model_version": "vlm",
        "enable_table": True,
        "enable_formula": True,
        "language": "ch",
    }
    assert http.calls[2][1] == "https://mineru.net/api/v4/extract-results/batch/batch-1"


def test_client_returns_structured_failure_for_remote_error_and_timeout(tmp_path):
    source = tmp_path / "scan.png"
    source.write_bytes(b"image-bytes")
    failed_http = _Http([
        _Response({"code": 429, "msg": "rate limited"}),
    ])
    failed = MinerUClient(mode="lightweight", http=failed_http).parse_file(source)
    assert failed.status == "error"
    assert "rate limited" in failed.error

    timeout_http = _Http([
        _Response({"code": 0, "data": {"task_id": "task-timeout", "file_url": "https://upload.invalid/signed"}}),
        _Response({}, status_code=200),
        _Response({"code": 0, "data": {"task_id": "task-timeout", "state": "running"}}),
    ])
    timeout = MinerUClient(
        mode="lightweight",
        http=timeout_http,
        poll_interval=0,
        max_wait_seconds=0,
        sleep=lambda _: None,
    ).parse_file(source)
    assert timeout.status == "timeout"
    assert timeout.state == "running"


def test_precise_mode_requires_token(tmp_path):
    source = tmp_path / "scan.png"
    source.write_bytes(b"image-bytes")
    result = MinerUClient(mode="precise", token="", http=_Http([])).parse_file(source)
    assert result.status == "error"
    assert result.error == "MINERU_TOKEN 未配置"


def test_http_error_does_not_leak_signed_url(tmp_path):
    source = tmp_path / "scan.png"
    source.write_bytes(b"image-bytes")

    class _BadResponse(_Response):
        def raise_for_status(self):
            raise RuntimeError("403 Client Error for url: https://signed.invalid/upload?secret=1")

    result = MinerUClient(
        mode="lightweight",
        http=_Http([_BadResponse({})]),
    ).parse_file(source)

    assert result.status == "error"
    assert "signed.invalid" not in result.error
    assert "secret=1" not in result.error
