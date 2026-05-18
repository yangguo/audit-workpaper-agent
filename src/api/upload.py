import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile, HTTPException


router = APIRouter()

MAX_FILES = 10
MAX_FILE_SIZE = 100 * 1024 * 1024

def _safe_filename(name: str) -> str:
    base = Path(name).name
    base = base.replace("\\", "_").replace("/", "_")
    for ch in [":", "*", "?", "\"", "<", ">", "|"]:
        base = base.replace(ch, "_")
    base = base.strip()
    if not base:
        return "file"
    if len(base) > 200:
        suffix = Path(base).suffix
        stem = Path(base).stem[: 200 - len(suffix)]
        return f"{stem}{suffix}"
    return base


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files (max {MAX_FILES})")

    workspace_path = os.getenv("COZE_WORKSPACE_PATH", os.getcwd())
    upload_dir = Path(workspace_path) / "assets" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_dir_resolved = upload_dir.resolve()

    saved_files: list[dict[str, Any]] = []
    for f in files:
        original_name = _safe_filename(f.filename or "")
        target_name = f"{uuid.uuid4().hex}_{original_name}"
        target_path = upload_dir / target_name
        if not target_path.resolve().is_relative_to(upload_dir_resolved):
            raise HTTPException(status_code=400, detail="Invalid upload path")

        size = 0
        try:
            with target_path.open("xb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_SIZE:
                        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE} bytes)")
                    out.write(chunk)
        except HTTPException:
            try:
                if target_path.exists():
                    target_path.unlink()
            finally:
                raise
        except Exception as e:
            try:
                if target_path.exists():
                    target_path.unlink()
            finally:
                raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}") from e
        finally:
            await f.close()

        rel_path = (Path("assets") / "uploads" / target_name).as_posix()
        saved_files.append(
            {
                "original_name": original_name,
                "path": rel_path,
                "size": size,
            }
        )

    return {"files": saved_files}
