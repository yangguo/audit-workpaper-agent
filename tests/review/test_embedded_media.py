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
    dest.mkdir()
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