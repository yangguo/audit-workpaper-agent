# 文档嵌入图片自动 OCR 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 DOCX/PPTX/PDF 中自动提取嵌入图片，写入 attachments 索引的虚拟条目，让受限证据 Agent 能像对待普通图片一样调用 OCR。

**Architecture:** 新模块 `src/review/embedded_media.py` 用 zipfile 解 DOCX/PPTX、用 pypdf 解 PDF；`build_attachment_index` 在原扫描完成后调用，把虚拟图片以 `<原文件>::<嵌入图名>` 命名写入 `.embedded_media/` 子目录并加入索引。无 LLM 调用，纯文件操作 + 现有 OCR 缓存复用。

**Tech Stack:** Python 3.12, zipfile (stdlib), pypdf (已有), openpyxl, pytest, pytest-asyncio.

## Global Constraints

- 复用现有 `ocr_attachment` 工具和 `ocr_by_path` 缓存，**不写新 OCR 调用代码**
- 单文档解压失败不阻塞其他文档
- 单次审阅最多 200 张嵌入图，单图不超过 10MB
- 虚拟路径用 `::` 分隔避免冲突
- `.embedded_media/` 加入 `.gitignore`

---

### Task 1: DOCX embedded media extraction

**Files:**
- Create: `src/review/embedded_media.py`
- Test: `tests/review/test_embedded_media.py`

**Interfaces:**
- Produces: `extract_docx_media(docx_path: Path, dest_dir: Path) -> List[ExtractedMedia]` where `ExtractedMedia` is a dataclass with `source_rel_path`, `media_filename`, `media_index`, `bytes`, `file_type`.

- [ ] **Step 1: Write the failing test**

```python
# tests/review/test_embedded_media.py
import io
import zipfile
from pathlib import Path

import pytest

from review.embedded_media import extract_docx_media


def _build_docx(media_files: dict[str, bytes]) -> bytes:
    """Build a minimal DOCX-like ZIP with given word/media/* entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # minimal document.xml so zipfile is valid
        zf.writestr("word/document.xml", b"<?xml version='1.0'?><doc/>")
        for name, data in media_files.items():
            zf.writestr(f"word/media/{name}", data)
    return buf.getvalue()


def test_extract_docx_media_returns_each_image(tmp_path):
    docx = tmp_path / "sample.docx"
    docx.write_bytes(_build_docx({
        "image1.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
        "photo.jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 10,
    }))
    dest = tmp_path / "out"
    out.mkdir()
    items = extract_docx_media(docx, dest)
    assert len(items) == 2
    filenames = sorted(i.media_filename for i in items)
    assert filenames == ["image1.png", "photo.jpg"]
    assert all(i.bytes for i in items)


def test_extract_docx_media_handles_no_media(tmp_path):
    docx = tmp_path / "empty.docx"
    docx.write_bytes(_build_docx({}))
    items = extract_docx_media(docx, tmp_path / "out")
    assert items == []


def test_extract_docx_media_skips_invalid_zip(tmp_path):
    bogus = tmp_path / "bogus.docx"
    bogus.write_bytes(b"not a zip")
    items = extract_docx_media(bogus, tmp_path / "out")
    assert items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'review.embedded_media'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/review/embedded_media.py
"""Extract embedded media from DOCX/PPTX/PDF and route through the existing OCR pipeline."""
import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

_logger = logging.getLogger("review.embedded_media")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}


@dataclass
class ExtractedMedia:
    source_rel_path: str
    media_filename: str
    media_index: int
    bytes: bytes
    file_type: str  # extension without dot, lower-case


def _safe_extract(zf: zipfile.ZipFile, member_name: str) -> bytes:
    """Guard against zip-slip: only extract members whose names are safe."""
    # Reject absolute paths and parent-traversal in the member name.
    name = member_name.replace("\\", "/")
    if name.startswith("/") or ".." in Path(name).parts:
        raise ValueError(f"unsafe zip member: {member_name}")
    return zf.read(member_name)


def extract_docx_media(docx_path: Path, dest_dir: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a DOCX file. Returns [] on any error."""
    out: List[ExtractedMedia] = []
    try:
        with zipfile.ZipFile(str(docx_path)) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("word/media/"))
            for idx, name in enumerate(names, start=1):
                media_filename = Path(name).name
                ext = Path(media_filename).suffix.lower()
                if ext not in _IMAGE_EXTS:
                    continue
                try:
                    data = _safe_extract(zf, name)
                except Exception:
                    continue
                out.append(ExtractedMedia(
                    source_rel_path=docx_path.name,
                    media_filename=media_filename,
                    media_index=idx,
                    bytes=data,
                    file_type=ext.lstrip("."),
                ))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        _logger.warning("extract_docx_media failed for %s: %s", docx_path, exc)
        return []
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/embedded_media.py tests/review/test_embedded_media.py
git commit -m "feat(review): extract embedded images from DOCX

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: PPTX embedded media extraction

**Files:**
- Modify: `src/review/embedded_media.py`
- Modify: `tests/review/test_embedded_media.py`

**Interfaces:**
- Produces: `extract_pptx_media(pptx_path: Path) -> List[ExtractedMedia]` (no dest_dir — PPTX reads bytes into memory only; the caller writes them out)

- [ ] **Step 1: Add the failing test**

```python
def test_extract_pptx_media_returns_each_image(tmp_path):
    pptx = tmp_path / "deck.pptx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ppt/presentation.xml", b"<?xml version='1.0'?><p/>")
        zf.writestr("ppt/media/slide1.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        zf.writestr("ppt/media/slide2.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 8)
    pptx.write_bytes(buf.getvalue())
    items = extract_pptx_media(pptx)
    assert len(items) == 2
    assert sorted(i.media_filename for i in items) == ["slide1.png", "slide2.jpg"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py::test_extract_pptx_media_returns_each_image -v`
Expected: FAIL with `AttributeError: module 'review.embedded_media' has no attribute 'extract_pptx_media'`

- [ ] **Step 3: Implement**

Add to `src/review/embedded_media.py`:

```python
def extract_pptx_media(pptx_path: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a PPTX file. Returns [] on any error."""
    out: List[ExtractedMedia] = []
    try:
        with zipfile.ZipFile(str(pptx_path)) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("ppt/media/"))
            for idx, name in enumerate(names, start=1):
                media_filename = Path(name).name
                ext = Path(media_filename).suffix.lower()
                if ext not in _IMAGE_EXTS:
                    continue
                try:
                    data = _safe_extract(zf, name)
                except Exception:
                    continue
                out.append(ExtractedMedia(
                    source_rel_path=pptx_path.name,
                    media_filename=media_filename,
                    media_index=idx,
                    bytes=data,
                    file_type=ext.lstrip("."),
                ))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        _logger.warning("extract_pptx_media failed for %s: %s", pptx_path, exc)
        return []
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/embedded_media.py tests/review/test_embedded_media.py
git commit -m "feat(review): extract embedded images from PPTX

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: PDF embedded media extraction

**Files:**
- Modify: `src/review/embedded_media.py`
- Modify: `tests/review/test_embedded_media.py`

**Interfaces:**
- Produces: `extract_pdf_media(pdf_path: Path) -> List[ExtractedMedia]`

- [ ] **Step 1: Add the failing test**

```python
def test_extract_pdf_media_returns_each_image(tmp_path):
    pdf = tmp_path / "doc.pdf"
    # minimal valid PDF with one image; constructed by pypdf in another fixture
    # For unit test, mock the PdfReader via monkeypatch to return a list of (bytes, ext) tuples.
    from review import embedded_media

    class _FakePage:
        def __init__(self, images):
            self.images = images
    class _FakeReader:
        def __init__(self, _path):
            self.pages = [_FakePage([(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "png"),
                                    (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "jpeg")])]
    monkeypatched_reader = = _FakeReader  # noqa
    monkeypatch.setattr(embedded_media, "_PdfReader", _FakeReader, raising=False)
    items = embedded_media.extract_pdf_media(pdf)
    assert len(items) == 2
    assert {i.file_type for i in items} == {"png", "jpeg"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py::test_extract_pdf_media_returns_each_image -v`
Expected: FAIL with `AttributeError: module 'review.embedded_media' has no attribute 'extract_pdf_media'`

- [ ] **Step 3: Implement**

```python
def extract_pdf_media(pdf_path: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a PDF. Uses pypdf if available; else returns []."""
    try:
        from pypdf import PdfReader
    except ImportError:
        _logger.warning("pypdf not installed; skipping PDF embedded media")
        return []
    out: List[ExtractedMedia] = []
    try:
        reader = PdfReader(str(pdf_path))
        idx = 0
        for page_num, page in enumerate(reader.pages, start=1):
            try:
                page_images = list(page.images)
            except Exception:
                continue
            for img in page_images:
                idx += 1
                data = getattr(img, "data", None)
                if not data:
                    continue
                ext = (getattr(img, "ext", "") or "png").lower().lstrip(".")
                if ext not in {e.lstrip(".") for e in _IMAGE_EXTS}:
                    ext = "png"
                out.append(ExtractedMedia(
                    source_rel_path=pdf_path.name,
                    media_filename=f"page{page_num}_img{idx}.{ext}",
                    media_index=idx,
                    bytes=data,
                    file_type=ext,
                ))
    except Exception as exc:
        _logger.warning("extract_pdf_media failed for %s: %s", pdf_path, exc)
        return []
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_embedded_media.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/embedded_media.py tests/review/test_embedded_media.py
git commit -m "feat(review): extract embedded images from PDF via pypdf

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Integrate embedded media into build_attachment_index

**Files:**
- Modify: `src/review/attachments.py`
- Modify: `tests/review/test_attachment_directory.py`

**Interfaces:**
- Modifies: `build_attachment_index` signature unchanged; behavior extended to write virtual attachments into `.embedded_media/` and add them to the returned `items`.

- [ ] **Step 1: Write the failing test**

```python
def test_build_attachment_index_includes_docx_embedded_images(tmp_path):
    from review.attachments import build_attachment_index
    # Set up attachments dir with a docx containing an image
    att_dir = tmp_path / "atts"
    att_dir.mkdir()
    docx = att_dir / "report.docx"
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<?xml version='1.0'?><doc/>")
        zf.writestr("word/media/picture.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)
    docx.write_bytes(buf.getvalue())

    idx = build_attachment_index(str(att_dir))
    # Virtual attachment should be present
    virtual = [it for it in idx["items"] if "embedded_media" in it.rel_path]
    assert virtual, "expected virtual attachment from embedded image"
    assert any(v.file_type == "png" for v in virtual)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachment_directory.py::test_build_attachment_index_includes_docx_embedded_images -v`
Expected: FAIL with `AssertionError: expected virtual attachment from embedded image`

- [ ] **Step 3: Implement integration**

In `src/review/attachments.py`, add at the end of `build_attachment_index` (after the `status_counts` block and before the `return`):

```python
# After real attachment scanning, extract embedded media from DOCX/PPTX/PDF
# and add them as virtual attachments indexed for Agent OCR.
try:
    from review.embedded_media import (
        extract_docx_media, extract_pptx_media, extract_pdf_media,
    )
    embedded_root = root / ".embedded_media"
    embedded_root.mkdir(parents=True, exist_ok=True)
    for path in list(paths):  # list() to snapshot, paths may be mutated below
        try:
            suffix = path.suffix.lower()
            if suffix == ".docx":
                media_items = extract_docx_media(path, embedded_root)
            elif suffix == ".pptx":
                media_items = extract_pptx_media(path)
                for m in media_items:
                    out_path = embedded_root / f"{path.name}::{m.media_filename}"
                    out_path.write_bytes(m.bytes)
            elif suffix == ".pdf":
                media_items = extract_pdf_media(path)
                for m in media_items:
                    out_path = embedded_root / f"{path.name}::{m.media_filename}"
                    out_path.write_bytes(m.bytes)
            else:
                continue
            for m in media_items:
                rel = f".embedded_media/{path.name}::{m.media_filename}"
                if any(it.rel_path == rel for it in items):
                    continue
                item = AttachmentFile(
                    index="",
                    rel_dir=".embedded_media",
                    filename=f"{path.name}::{m.media_filename}",
                    rel_path=rel,
                    file_type=m.file_type,
                    description="",
                    status="binary",  # triggers ocr_attachment when Agent investigates
                    extraction_status="binary",
                    extracted_text="",
                    size=len(m.bytes),
                    source=str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                )
                items.append(item)
                by_filename[item.filename].append(item)
                by_rel_path[item.rel_path].append(item)
                # do NOT add to by_sheet_norm (no sheet context for embedded media)
                status_counts["binary"] += 1
except Exception as exc:
    _logger.warning("embedded media extraction failed: %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachment_directory.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend review test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: PASS (existing 186 + new tests)

- [ ] **Step 6: Commit**

```bash
git add src/review/attachments.py tests/review/test_attachment_directory.py
git commit -m "feat(review): route DOCX/PPTX/PDF embedded media through OCR index

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: .gitignore the virtual media directory

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add the pattern**

Append to `.gitignore`:

```
# Virtual embedded-media directory created by build_attachment_index
**/.embedded_media/
```

- [ ] **Step 2: Verify no .embedded_media files are tracked**

Run: `git status --ignored`
Expected: shows `.embedded_media` directories as ignored.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore virtual embedded media directory

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Integration smoke test with real audit attachment

**Files:**
- None; verification only.

- [ ] **Step 1: Restart backend with new code**

```bash
bash scripts/http_run.sh -p 5000
```

- [ ] **Step 2: Upload a real attachment directory containing a DOCX with an embedded image**

Use the test fixtures under `assets/uploads/attachments/<batch>/` which contain 99 files including IT audit evidence. Pick any batch that has a `.docx` with embedded images (e.g. `审计证据/SA-12/4-审计期内对系统中的特权账号操作日志进行复核的审阅.xlsx` is an xlsx; look for `.docx` files in the attachment dirs). Or drop a fresh `.docx` with an embedded image into a test attachment directory.

- [ ] **Step 3: Trigger a review and verify OCR is invoked on embedded images**

Run a review on the test attachment directory. Check `logs/app.log` for MinerU HTTP calls and `ocr_attachment` tool traces.

- [ ] **Step 4: Verify finding.evidence_refs can reference embedded images**

Check the findings JSON for `evidence_refs[*].attachment` paths matching `.embedded_media/<filename>::<image>.png`.

- [ ] **Step 5: Commit any final fixes**

If smoke test reveals issues, fix and commit separately.

---

## Self-Review

**Spec coverage:**
- DOCX extraction → Task 1.
- PPTX extraction → Task 2.
- PDF extraction → Task 3.
- Index integration → Task 4.
- .gitignore → Task 5.
- Smoke verification → Task 6.

**Placeholder scan:** All steps have concrete code; no TBD/TODO.

**Type consistency:** `ExtractedMedia` used uniformly; `AttachmentFile` instantiation matches existing fields.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-embedded-media-ocr-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans.

**Which approach?**