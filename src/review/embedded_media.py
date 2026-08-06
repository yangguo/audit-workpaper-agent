"""Extract embedded media from DOCX and route through the existing OCR pipeline (DOCX support only for now; PPTX/PDF will be added in subsequent tasks)."""
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