# 旧格式 .xls/.doc 自动转换实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `build_attachment_index` 增加 `.xls`/`.doc` 自动转换能力，通过系统级 `soffice`（LibreOffice headless）转为 `.xlsx`/`.docx`，转换失败时优雅降级到 `unsupported`。

**Architecture:** 新模块 `src/review/legacy_convert.py` 封装 `subprocess.run` 调用 `soffice --headless --convert-to`，配超时和不可用降级。`src/review/attachments.py:_extract_attachment_text` 在 `.xls`/`.doc` 分支调它，成功后递归走 `.xlsx`/`.docx` 提取器。

**Tech Stack:** Python 3.12, subprocess, shutil, tempfile, pytest (with monkeypatch).

## Global Constraints

- 不引入新的 Python 依赖；依赖系统级 `soffice`（可选）
- 转换失败时返回 `unsupported`，不抛错、不阻塞审阅
- 默认超时 30 秒，可通过 `LIBREOFFICE_CONVERT_TIMEOUT=0` 禁用
- 临时目录不主动清理（依赖系统 / tempfile 周期清理）

---

### Task 1: convert_legacy_to_modern module

**Files:**
- Create: `src/review/legacy_convert.py`
- Test: `tests/review/test_legacy_convert.py`

**Interfaces:**
- Produces: `convert_legacy_to_modern(src_path: Path, dest_dir: Optional[Path] = None) -> Optional[Path]`
- `_resolve_soffice() -> Optional[str]`
- `_convert_timeout() -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/review/test_legacy_convert.py
import os
import shutil
from pathlib import Path

import pytest

from review import legacy_convert
from review.legacy_convert import convert_legacy_to_modern


def test_non_legacy_returns_none(tmp_path):
    assert convert_legacy_to_modern(tmp_path / "modern.xlsx") is None


def test_disabled_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBREOFFICE_CONVERT_TIMEOUT", "0")
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_soffice_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_subprocess_timeout_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/soffice")
    import subprocess as sp
    def _fake_run(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="soffice", timeout=30)
    monkeypatch.setattr(sp, "run", _fake_run)
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_nonzero_returncode_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/soffice")
    class _R:
        returncode = 1
        stderr = "boom"
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **k: _R())
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_legacy_convert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'review.legacy_convert'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/review/legacy_convert.py
"""Convert legacy .xls/.doc to modern .xlsx/.docx via LibreOffice headless."""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("review.legacy_convert")

_LEGACY_FORMATS = {
    ".xls": "xlsx",
    ".doc": "docx",
}


def _resolve_soffice() -> Optional[str]:
    """Locate soffice executable; None if unavailable."""
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_timeout() -> int:
    raw = os.getenv("LIBREOFFICE_CONVERT_TIMEOUT", "30").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def convert_legacy_to_modern(
    src_path: Path,
    dest_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Convert .xls/.doc to .xlsx/.docx. Returns converted path or None.

    None if soffice unavailable, timeout exceeded, conversion failed,
    or format is not legacy.
    """
    src_path = Path(src_path)
    ext = src_path.suffix.lower()
    if ext not in _LEGACY_FORMATS:
        return None
    if _convert_timeout() <= 0:
        return None
    soffice = _resolve_soffice()
    if not soffice:
        _logger.warning("soffice not on PATH; legacy %s conversion skipped", ext)
        return None

    dest_dir = dest_dir or Path(tempfile.mkdtemp(prefix="audit_legacy_convert_"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_ext = _LEGACY_FORMATS[ext]

    try:
        proc = subprocess.run(
            [
                soffice, "--headless", "--convert-to", target_ext,
                "--outdir", str(dest_dir), str(src_path),
            ],
            capture_output=True, text=True,
            timeout=_convert_timeout(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        _logger.warning("soffice convert %s timed out", src_path)
        return None
    except OSError as exc:
        _logger.warning("soffice invocation failed: %s", exc)
        return None

    if proc.returncode != 0:
        _logger.warning("soffice convert failed (rc=%s): %s",
                        proc.returncode, proc.stderr.strip())
        return None

    converted = dest_dir / (src_path.stem + "." + target_ext)
    if not converted.is_file():
        _logger.warning("soffice did not produce expected output: %s", converted)
        return None
    return converted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_legacy_convert.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/review/legacy_convert.py tests/review/test_legacy_convert.py
git commit -m "feat(review): add legacy .xls/.doc conversion via soffice

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Wire conversion into _extract_attachment_text

**Files:**
- Modify: `src/review/attachments.py`
- Modify: `tests/review/test_attachment_directory.py`

**Interfaces:**
- Consumes: `convert_legacy_to_modern(path) -> Optional[Path]`
- Modifies: `_extract_attachment_text(path: Path) -> Tuple[str, str]` behavior for `.xls`/`.doc`

- [ ] **Step 1: Write the failing test**

```python
# tests/review/test_attachment_directory.py
def test_extract_attachment_text_handles_legacy_via_converter(tmp_path, monkeypatch):
    """Legacy .xls/.doc should be routed through the converter when available."""
    from review import attachments

    class _FakeLegacy:
        def convert_legacy_to_modern(self, src_path, dest_dir=None):
            out = tmp_path / (src_path.stem + ".xlsx")
            out.write_bytes(b"fake xlsx")
            return out

    class _FakeXLSXReader:
        def __init__(self, *a, **k):
            pass
        # _read_xlsx_file returns (text, status) — mock via patching

    monkeypatch.setattr(attachments, "convert_legacy_to_modern", _FakeLegacy().convert_legacy_to_modern)

    # Build a tiny .xls file
    fake = tmp_path / "old.xls"
    fake.write_bytes(b"\\xd0\\xcf\\x11\\xe0\\xa1\\xb1\\x1a\\xe1")  # OLE/CFB magic
    text, status = attachments._extract_attachment_text(fake)
    # Either ok or unavailable depending on the patched _read_xlsx_file; main goal:
    # the legacy branch was entered (no "unsupported" without calling converter)
    assert status != "unsupported" or text != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachment_directory.py::test_extract_attachment_text_handles_legacy_via_converter -v`
Expected: FAIL with `AttributeError: module 'review.attachments' has no attribute 'convert_legacy_to_modern'`

- [ ] **Step 3: Implement wiring**

In `src/review/attachments.py`, modify `_extract_attachment_text` to insert the legacy branch BEFORE the `.docx` branch:

```python
def _extract_attachment_text(path: Path) -> Tuple[str, str]:
    suffix = path.suffix.lower()
    try:
        if suffix in _TEXT_EXTENSIONS:
            return _read_text_file(path)
        if suffix in {".xls", ".doc"}:
            from review.legacy_convert import convert_legacy_to_modern
            converted = convert_legacy_to_modern(path)
            if converted is None:
                return "", "unsupported"
            modern_suffix = converted.suffix.lower()
            if modern_suffix == ".xlsx":
                return _read_xlsx_file(converted)
            if modern_suffix == ".docx":
                return _read_docx_file(converted)
            return "", "unsupported"
        if suffix == ".xlsx":
            return _read_xlsx_file(path)
        # ... rest unchanged ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachment_directory.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend review test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: PASS (existing 192 + new tests, no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/review/attachments.py tests/review/test_attachment_directory.py
git commit -m "feat(review): route .xls/.doc attachments through soffice converter

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Document the optional dependency in .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the entry**

Append after the existing MinerU section:

```
# Optional LibreOffice conversion for legacy .xls/.doc attachments.
# soffice must be on PATH (install via OS package manager).
# Set 0 or empty to disable conversion; unsupported entries fall back gracefully.
LIBREOFFICE_CONVERT_TIMEOUT=30
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: document LIBREOFFICE_CONVERT_TIMEOUT in .env.example

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- New module `legacy_convert.py` → Task 1.
- Integration into `_extract_attachment_text` → Task 2.
- .env.example entry → Task 3.

**Placeholder scan:** All steps have concrete code; no TBD.

**Type consistency:** `convert_legacy_to_modern` signature matches across Task 1, Task 2, and spec.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-legacy-format-conversion-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks.

**2. Inline Execution** - Execute tasks in this session.

**Which approach?**