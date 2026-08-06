"""Extract embedded media from office documents and route through the existing OCR pipeline.

Supports DOCX, PPTX, and PDF. Each helper returns a list of ``ExtractedMedia``
records whose ``media_index`` is a 1-based contiguous index of emitted images
(not of the source archive entries). Bytes are surfaced via
``ExtractedMedia.bytes``; callers are responsible for any on-disk persistence.
"""
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

_logger = logging.getLogger("review.embedded_media")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}


@dataclass
class ExtractedMedia:
    source_rel_path: str
    media_filename: str
    media_index: int  # 1-based index of emitted images (contiguous)
    bytes: bytes
    file_type: str  # extension without dot, lower-case


def _safe_extract(zf: zipfile.ZipFile, member_name: str) -> bytes:
    """Guard against zip-slip: only extract members whose names are safe."""
    # Reject absolute paths and parent-traversal in the member name.
    name = member_name.replace("\\", "/")
    if name.startswith("/") or ".." in Path(name).parts:
        raise ValueError(f"unsafe zip member: {member_name}")
    return zf.read(member_name)


def extract_docx_media(docx_path: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a DOCX file. Returns [] on any error.

    The returned ``ExtractedMedia.media_index`` is a 1-based index of emitted
    images (not of ``word/media/`` entries), so it is always contiguous starting
    at 1. The bytes are surfaced via ``ExtractedMedia.bytes``; callers are
    responsible for any on-disk persistence.
    """
    out: List[ExtractedMedia] = []
    try:
        with zipfile.ZipFile(str(docx_path)) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("word/media/"))
            media_index = 0
            for name in names:
                media_filename = Path(name).name
                ext = Path(media_filename).suffix.lower()
                if ext not in _IMAGE_EXTS:
                    continue
                try:
                    data = _safe_extract(zf, name)
                except Exception:
                    continue
                media_index += 1
                out.append(ExtractedMedia(
                    source_rel_path=docx_path.name,
                    media_filename=media_filename,
                    media_index=media_index,
                    bytes=data,
                    file_type=ext.lstrip("."),
                ))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        _logger.warning("extract_docx_media failed for %s: %s", docx_path, exc)
        return []
    return out


def extract_pptx_media(pptx_path: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a PPTX file. Returns [] on any error."""
    out: List[ExtractedMedia] = []
    try:
        with zipfile.ZipFile(str(pptx_path)) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("ppt/media/"))
            media_index = 0
            for name in names:
                media_filename = Path(name).name
                ext = Path(media_filename).suffix.lower()
                if ext not in _IMAGE_EXTS:
                    continue
                try:
                    data = _safe_extract(zf, name)
                except Exception:
                    continue
                media_index += 1
                out.append(ExtractedMedia(
                    source_rel_path=pptx_path.name,
                    media_filename=media_filename,
                    media_index=media_index,
                    bytes=data,
                    file_type=ext.lstrip("."),
                ))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        _logger.warning("extract_pptx_media failed for %s: %s", pptx_path, exc)
        return []
    return out


# pypdf is an optional dependency for embedded-media extraction. Importing it at
# module level keeps the call path simple; ``extract_pdf_media`` falls back to
# returning ``[]`` (with a warning) when it is not installed.
try:  # pragma: no cover - exercised indirectly via monkeypatch
    from pypdf import PdfReader as _PdfReader
except ImportError:  # pragma: no cover
    _PdfReader = None  # type: ignore[assignment]


def extract_pdf_media(pdf_path: Path) -> List[ExtractedMedia]:
    """Extract embedded images from a PDF. Uses pypdf if available; else returns [].

    ``media_index`` is a 1-based contiguous index of emitted images (only
    incremented when an image is appended), and ``media_filename`` embeds the
    originating page number for traceback.
    """
    if _PdfReader is None:
        _logger.warning("pypdf not installed; skipping PDF embedded media")
        return []
    out: List[ExtractedMedia] = []
    try:
        reader = _PdfReader(str(pdf_path))
        media_index = 0
        for page_num, page in enumerate(reader.pages, start=1):
            try:
                page_images = list(page.images)
            except Exception:
                continue
            for img in page_images:
                # pypdf returns ImageFile objects with .data/.ext, but for
                # extensibility also accept plain (data, ext) tuples.
                if isinstance(img, tuple):
                    data = img[0] if len(img) > 0 else None
                    ext = (img[1] if len(img) > 1 else "") or "png"
                else:
                    data = getattr(img, "data", None)
                    ext = getattr(img, "ext", "") or "png"
                if not data:
                    continue
                media_index += 1
                ext = ext.lower().lstrip(".") or "png"
                if ext not in {e.lstrip(".") for e in _IMAGE_EXTS}:
                    ext = "png"
                out.append(ExtractedMedia(
                    source_rel_path=pdf_path.name,
                    media_filename=f"page{page_num}_img{media_index}.{ext}",
                    media_index=media_index,
                    bytes=data,
                    file_type=ext,
                ))
    except Exception as exc:
        _logger.warning("extract_pdf_media failed for %s: %s", pdf_path, exc)
        return []
    return out