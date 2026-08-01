from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from api.upload import upload_files


@pytest.mark.asyncio
async def test_upload_attachment_directory_preserves_relative_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    files = [
        UploadFile(
            filename="evidence.txt",
            file=BytesIO(b"admin,administrator"),
        )
    ]

    payload = await upload_files(
        files=files,
        upload_mode="attachments_dir",
        relative_paths=["SA-4c/evidence.txt"],
    )

    assert payload["directory"].startswith("assets/uploads/attachments/")
    saved = tmp_path / payload["files"][0]["path"]
    assert saved.read_bytes() == b"admin,administrator"
    assert saved.relative_to(tmp_path / "assets/uploads/attachments").parts[-2:] == (
        "SA-4c",
        "evidence.txt",
    )
