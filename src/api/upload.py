import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile, HTTPException


logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILES = 10
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_ATTACHMENT_FILES = 500
MAX_ATTACHMENT_TOTAL_SIZE = 1024 * 1024 * 1024

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


def _safe_relative_path(name: str) -> Path:
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or ":" in raw.split("/")[0]:
        raise HTTPException(status_code=400, detail="Invalid relative upload path")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="Invalid relative upload path")
    return Path(*[_safe_filename(part) for part in parts])


async def _save_upload_file(upload: UploadFile, target_path: Path, *, total_size: int = 0) -> tuple[int, int]:
    size = 0
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target_path.open("xb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE} bytes)")
                out.write(chunk)
    finally:
        await upload.close()
    return size, total_size + size


async def _upload_attachment_directory(
    files: list[UploadFile],
    relative_paths: list[str] | None,
    upload_dir: Path,
) -> dict[str, Any]:
    if len(files) > MAX_ATTACHMENT_FILES:
        raise HTTPException(status_code=400, detail=f"Too many attachment files (max {MAX_ATTACHMENT_FILES})")

    batch_id = uuid.uuid4().hex
    directory = upload_dir / "attachments" / batch_id
    directory.mkdir(parents=True, exist_ok=False)
    directory_resolved = directory.resolve()
    saved_files: list[dict[str, Any]] = []
    total_size = 0
    try:
        for index, upload in enumerate(files):
            raw_relative = (
                relative_paths[index]
                if relative_paths and index < len(relative_paths)
                else upload.filename or "file"
            )
            relative = _safe_relative_path(raw_relative)
            target_path = directory / relative
            if not target_path.resolve().is_relative_to(directory_resolved):
                raise HTTPException(status_code=400, detail="Invalid upload path")
            if target_path.exists():
                raise HTTPException(status_code=400, detail=f"Duplicate attachment path: {relative.as_posix()}")
            size, total_size = await _save_upload_file(upload, target_path, total_size=total_size)
            if total_size > MAX_ATTACHMENT_TOTAL_SIZE:
                raise HTTPException(status_code=413, detail="Attachment directory too large")
            saved_files.append({
                "original_name": Path(raw_relative).name,
                "relative_path": relative.as_posix(),
                "path": (Path("assets") / "uploads" / "attachments" / batch_id / relative).as_posix(),
                "size": size,
            })
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    return {
        "directory": (Path("assets") / "uploads" / "attachments" / batch_id).as_posix(),
        "files": saved_files,
    }


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    upload_mode: str = Form("files"),
    relative_paths: list[str] | None = Form(default=None),
) -> dict[str, Any]:
    logger.info(f"Upload request received: {len(files)} file(s)")
    if upload_mode == "attachments_dir":
        workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())
        upload_dir = Path(workspace_path) / "assets" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        return await _upload_attachment_directory(files, relative_paths, upload_dir)
    if upload_mode != "files":
        raise HTTPException(status_code=400, detail="Unsupported upload mode")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files (max {MAX_FILES})")

    workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())
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
            logger.error(f"Upload failed for {original_name}: {e}", exc_info=True)
            try:
                if target_path.exists():
                    target_path.unlink()
            finally:
                raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}: {e}") from e
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
