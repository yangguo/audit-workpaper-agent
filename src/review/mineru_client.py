"""Small, bounded client for MinerU OCR/document parsing APIs.

The review pipeline only calls this client for a file that is already present
in the pinned attachment directory.  This module deliberately returns text
and structured status, never signed upload/download URLs, to keep provider
details out of the evidence Agent conversation and persisted review stats.
"""

from __future__ import annotations

import os
import re
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests


_LIGHTWEIGHT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp",
    ".docx", ".pptx", ".xlsx",
}
_PRECISE_EXTENSIONS = _LIGHTWEIGHT_EXTENSIONS | {
    ".doc", ".ppt", ".xls", ".html",
}
_LIGHTWEIGHT_MAX_BYTES = 10 * 1024 * 1024
_PRECISE_MAX_BYTES = 200 * 1024 * 1024
_DEFAULT_MAX_WAIT_SECONDS = 300.0
_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DEFAULT_MAX_TEXT_CHARS = 60000
_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class MinerUResult:
    """Provider-neutral result returned to the constrained evidence tool."""

    status: str
    text: str = ""
    provider: str = "mineru"
    task_id: str = ""
    state: str = ""
    error: str = ""


class MinerUClient:
    """Call either MinerU's precise or lightweight signed-upload workflow."""

    def __init__(
        self,
        *,
        mode: str = "auto",
        token: str = "",
        base_url: str = "https://mineru.net",
        http: Any = requests,
        max_wait_seconds: float = _DEFAULT_MAX_WAIT_SECONDS,
        poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        max_text_chars: int = _DEFAULT_MAX_TEXT_CHARS,
        max_file_bytes: Optional[int] = None,
        sleep: Callable[[float], None] = time.sleep,
        verify_ssl: bool = True,
    ) -> None:
        normalized_mode = str(mode or "auto").strip().lower()
        if normalized_mode not in {"off", "auto", "lightweight", "precise"}:
            normalized_mode = "auto"
        if normalized_mode == "auto":
            normalized_mode = "precise" if str(token or "").strip() else "lightweight"
        self.mode = normalized_mode
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "https://mineru.net").rstrip("/")
        self.http = http
        self.max_wait_seconds = max(0.0, float(max_wait_seconds))
        self.poll_interval = max(0.0, float(poll_interval))
        self.max_text_chars = max(1, int(max_text_chars))
        self.max_file_bytes = (
            max(1, int(max_file_bytes))
            if max_file_bytes is not None
            else None
        )
        self.sleep = sleep
        self.verify_ssl = bool(verify_ssl)

    @classmethod
    def from_env(cls) -> Optional["MinerUClient"]:
        """Build an explicitly enabled client; default is privacy-safe off."""
        mode = str(os.getenv("MINERU_OCR_MODE", "off")).strip().lower()
        if mode == "off":
            return None
        return cls(
            mode=mode,
            token=os.getenv("MINERU_TOKEN", ""),
            base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net"),
            max_wait_seconds=_env_float("MINERU_OCR_MAX_WAIT_SECONDS", _DEFAULT_MAX_WAIT_SECONDS),
            poll_interval=_env_float("MINERU_OCR_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_SECONDS),
            max_text_chars=_env_int("MINERU_OCR_MAX_TEXT_CHARS", _DEFAULT_MAX_TEXT_CHARS),
            max_file_bytes=_env_optional_int("MINERU_OCR_MAX_FILE_BYTES"),
            verify_ssl=_env_bool("MINERU_VERIFY_SSL", True),
        )

    @property
    def provider(self) -> str:
        return f"mineru-{self.mode}"

    def parse_file(
        self,
        path: str | Path,
        *,
        language: str = "ch",
        is_ocr: bool = True,
        enable_table: bool = True,
        enable_formula: bool = True,
        page_range: str = "",
    ) -> MinerUResult:
        source = Path(path)
        if self.mode == "off":
            return self._error("disabled", "MINERU_OCR_MODE=off")
        if self.mode == "precise" and not self.token:
            return self._error("error", "MINERU_TOKEN 未配置")
        if not source.is_file():
            return self._error("error", "附件文件不存在")

        suffix = source.suffix.lower()
        allowed = _PRECISE_EXTENSIONS if self.mode == "precise" else _LIGHTWEIGHT_EXTENSIONS
        if suffix not in allowed:
            return self._error("unsupported", f"MinerU 当前模式不支持 {suffix or '无扩展名'}")
        try:
            size = source.stat().st_size
        except OSError as exc:
            return self._error("error", f"读取附件大小失败: {type(exc).__name__}")
        limit = self.max_file_bytes or (
            _PRECISE_MAX_BYTES if self.mode == "precise" else _LIGHTWEIGHT_MAX_BYTES
        )
        if size > limit:
            return self._error("too_large", f"附件超过 MinerU 当前模式大小限制（{limit} bytes）")

        try:
            if self.mode == "precise":
                return self._parse_precise(
                    source,
                    language=language,
                    is_ocr=is_ocr,
                    enable_table=enable_table,
                    enable_formula=enable_formula,
                    page_range=page_range,
                )
            return self._parse_lightweight(
                source,
                language=language,
                is_ocr=is_ocr,
                enable_table=enable_table,
                enable_formula=enable_formula,
                page_range=page_range,
            )
        except Exception as exc:
            if isinstance(exc, MinerUError):
                return self._error("error", str(exc))
            # Do not return provider exception text: requests may include a
            # signed upload URL in its error message.
            return self._error("error", f"MinerU 请求失败: {type(exc).__name__}")

    def _parse_lightweight(
        self,
        source: Path,
        *,
        language: str,
        is_ocr: bool,
        enable_table: bool,
        enable_formula: bool,
        page_range: str,
    ) -> MinerUResult:
        payload: Dict[str, object] = {
            "file_name": source.name,
            "language": language,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        }
        if page_range:
            payload["page_range"] = page_range
        response = self._request(
            "post",
            f"{self.base_url}/api/v1/agent/parse/file",
            json=payload,
        )
        data = self._success_data(response)
        task_id = str(data.get("task_id", "") or "")
        upload_url = str(data.get("file_url", "") or "")
        if not task_id or not upload_url:
            raise MinerUError("MinerU 未返回 task_id/file_url")
        self._upload(upload_url, source)

        def poll() -> tuple[str, str, str]:
            result = self._request(
                "get",
                f"{self.base_url}/api/v1/agent/parse/{task_id}",
            )
            body = self._success_data(result)
            state = str(body.get("state", "") or "")
            if state == "done":
                return state, str(body.get("markdown_url", "") or ""), ""
            return state, "", str(body.get("err_msg", "") or "")

        state, markdown_url, error = self._poll(poll)
        if state == "done":
            if not markdown_url:
                raise MinerUError("MinerU 完成但未返回 markdown_url")
            text = self._download_markdown(markdown_url)
            return MinerUResult(
                status="ok", text=text, provider=self.provider, task_id=task_id, state=state,
            )
        if state == "timeout":
            return MinerUResult(status="timeout", provider=self.provider, task_id=task_id, state=error)
        return MinerUResult(
            status="error", provider=self.provider, task_id=task_id, state=state,
            error=_redact_message(error or "MinerU 解析失败"),
        )

    def _parse_precise(
        self,
        source: Path,
        *,
        language: str,
        is_ocr: bool,
        enable_table: bool,
        enable_formula: bool,
        page_range: str,
    ) -> MinerUResult:
        file_spec: Dict[str, object] = {
            "name": source.name,
            "is_ocr": is_ocr,
        }
        if page_range:
            file_spec["page_ranges"] = page_range
        payload: Dict[str, object] = {
            "files": [file_spec],
            "model_version": os.getenv("MINERU_MODEL_VERSION", "vlm"),
            "enable_table": enable_table,
            "enable_formula": enable_formula,
            "language": language,
        }
        headers = self._precise_headers()
        response = self._request(
            "post",
            f"{self.base_url}/api/v4/file-urls/batch",
            headers=headers,
            json=payload,
        )
        data = self._success_data(response)
        batch_id = str(data.get("batch_id", "") or "")
        urls = data.get("file_urls")
        if not batch_id or not isinstance(urls, list) or not urls or not urls[0]:
            raise MinerUError("MinerU 未返回 batch_id/file_urls")
        self._upload(str(urls[0]), source)

        def poll() -> tuple[str, str, str]:
            result = self._request(
                "get",
                f"{self.base_url}/api/v4/extract-results/batch/{batch_id}",
                headers=headers,
            )
            body = self._success_data(result)
            entries = body.get("extract_result", [])
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                entries = []
            entry = next(
                (item for item in entries if isinstance(item, dict) and item.get("file_name") == source.name),
                entries[0] if entries and isinstance(entries[0], dict) else {},
            )
            state = str(entry.get("state", "") or "")
            if state == "done":
                return state, str(entry.get("full_zip_url", "") or ""), ""
            return state, "", str(entry.get("err_msg", "") or "")

        state, result_url, error = self._poll(poll)
        if state == "done":
            if not result_url:
                raise MinerUError("MinerU 完成但未返回 full_zip_url")
            text = self._download_full_markdown(result_url)
            return MinerUResult(
                status="ok", text=text, provider=self.provider, task_id=batch_id, state=state,
            )
        if state == "timeout":
            return MinerUResult(status="timeout", provider=self.provider, task_id=batch_id, state=error)
        return MinerUResult(
            status="error", provider=self.provider, task_id=batch_id, state=state,
            error=_redact_message(error or "MinerU 解析失败"),
        )

    def _poll(self, callback: Callable[[], tuple[str, str, str]]) -> tuple[str, str, str]:
        deadline = time.monotonic() + self.max_wait_seconds
        last_state = ""
        last_error = ""
        while True:
            state, value, error = callback()
            last_state = state
            last_error = error
            if state == "done" or state == "failed":
                return state, value, error
            if state not in {"", "waiting-file", "uploading", "pending", "running", "converting"}:
                return state, value, error or "MinerU 返回未知状态"
            if time.monotonic() >= deadline:
                return "timeout", "", last_state or last_error or "timeout"
            self.sleep(self.poll_interval)

    def _download_markdown(self, url: str) -> str:
        response = self._request("get", url)
        raw = response.content or str(getattr(response, "text", "") or "").encode("utf-8")
        if len(raw) > _MAX_DOWNLOAD_BYTES:
            raise MinerUError("Markdown 响应超过安全大小限制")
        return _limit_text(raw.decode("utf-8", errors="replace"), self.max_text_chars)

    def _download_full_markdown(self, url: str) -> str:
        response = self._request("get", url)
        raw = response.content or str(getattr(response, "text", "") or "").encode("utf-8")
        if len(raw) > _MAX_DOWNLOAD_BYTES:
            raise MinerUError("MinerU ZIP 响应超过安全大小限制")
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                candidates = [
                    info for info in archive.infolist()
                    if not info.is_dir() and info.filename.lower().endswith("full.md")
                ]
                if not candidates:
                    raise MinerUError("MinerU ZIP 中未找到 full.md")
                info = candidates[0]
                if info.file_size > _MAX_DOWNLOAD_BYTES:
                    raise MinerUError("MinerU full.md 超过安全大小限制")
                text = archive.read(info).decode("utf-8", errors="replace")
        except zipfile.BadZipFile as exc:
            raise MinerUError("MinerU 返回的结果不是有效 ZIP") from exc
        return _limit_text(text, self.max_text_chars)

    def _upload(self, url: str, source: Path) -> None:
        # The signed URL is used only inside this client and is never returned
        # to the Agent or persisted in review statistics.
        response = self._request("put", url, data=source.read_bytes())
        if int(getattr(response, "status_code", 200) or 200) >= 400:
            raise MinerUError(f"MinerU 文件上传失败 HTTP {response.status_code}")

    def _precise_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("verify", self.verify_ssl)
        response = getattr(self.http, method)(url, timeout=30, **kwargs)
        try:
            response.raise_for_status()
        except Exception as exc:
            status = getattr(response, "status_code", "")
            suffix = f" HTTP {status}" if status else ""
            raise MinerUError(f"MinerU HTTP 请求失败{suffix}") from exc
        return response

    @staticmethod
    def _success_data(response: Any) -> Dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict):
            raise MinerUError("MinerU 返回格式错误")
        if payload.get("code") not in (0, "0", None):
            message = str(payload.get("msg", "未知错误") or "未知错误")
            raise MinerUError(message)
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise MinerUError("MinerU data 返回格式错误")
        return data

    def _error(self, status: str, error: str) -> MinerUResult:
        return MinerUResult(status=status, provider=self.provider, error=_redact_message(error))


class MinerUError(RuntimeError):
    """Expected provider/protocol failure, kept separate for readable results."""


def _limit_text(value: str, limit: int) -> str:
    return str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()[:limit]


def _redact_message(value: str) -> str:
    return re.sub(r"https?://\S+", "<redacted-url>", str(value or ""))[:1000]


def _env_int(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


def _env_optional_int(key: str) -> Optional[int]:
    raw = str(os.getenv(key, "") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
        return value if value > 0 else None
    except ValueError:
        return None


def _env_float(key: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = str(os.getenv(key, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)
