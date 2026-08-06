import io
import zipfile

from review.embedded_media import extract_docx_media, extract_pptx_media


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
    items = extract_docx_media(docx)
    assert len(items) == 2
    filenames = sorted(i.media_filename for i in items)
    assert filenames == ["image1.png", "photo.jpg"]
    assert all(i.bytes for i in items)


def test_extract_docx_media_handles_no_media(tmp_path):
    docx = tmp_path / "empty.docx"
    docx.write_bytes(_build_docx({}))
    items = extract_docx_media(docx)
    assert items == []


def test_extract_docx_media_skips_invalid_zip(tmp_path):
    bogus = tmp_path / "bogus.docx"
    bogus.write_bytes(b"not a zip")
    items = extract_docx_media(bogus)
    assert items == []


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


def test_extract_pdf_media_returns_each_image(tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    from review import embedded_media

    class _FakePage:
        def __init__(self, images):
            self.images = images

    class _FakeReader:
        def __init__(self, _path):
            self.pages = [_FakePage([
                (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "png"),
                (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "jpeg"),
            ])]

    monkeypatch.setattr(embedded_media, "_PdfReader", _FakeReader, raising=False)
    items = embedded_media.extract_pdf_media(pdf)
    assert len(items) == 2
    assert {i.file_type for i in items} == {"png", "jpeg"}
    assert [i.media_index for i in items] == [1, 2]
    assert [i.media_filename for i in items] == ["page1_img1.png", "page1_img2.jpeg"]
    assert all(i.source_rel_path == "doc.pdf" for i in items)
    assert all(i.bytes for i in items)
