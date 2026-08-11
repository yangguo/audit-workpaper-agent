import hashlib
import logging
import os
import re
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


async def _stream_to_temp_and_hash(upload: UploadFile, target_path: Path) -> tuple[Path, str, int]:
    """Stream the upload to ``target_path`` while computing sha256.

    Returns (target_path, hex_sha256, byte_size). Caller is responsible for
    deleting the file once it has decided what to do with the content.
    """
    hasher = hashlib.sha256()
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
                hasher.update(chunk)
                out.write(chunk)
    finally:
        await upload.close()
    return target_path, hasher.hexdigest(), size


_HASH_suffix_re = re.compile(r"^[0-9a-f]{64}_")


def _list_existing_hash_uploads(upload_dir: Path) -> dict[str, str]:
    """Map sha256 -> relative path for files in assets/uploads/.

    Only considers regular files (not attachments/ subdir). The basename
    pattern ``<sha256>_<original-name>`` lets us recognise previously-deduped
    files without scanning every byte again.
    """
    out: dict[str, str] = {}
    if not upload_dir.is_dir():
        return out
    for child in upload_dir.iterdir():
        if not child.is_file() or child.is_symlink():
            continue
        match = _hash_suffix_re.match(child.name)
        if not match:
            continue
        digest = match.group(0)[:-1]  # strip trailing underscore
        out.setdefault(digest, (Path("assets") / "uploads" / child.name).as_posix())
    return out


async def _upload_with_dedupe(
    *,
    upload: UploadFile,
    upload_dir: Path,
    original_name: str,
) -> tuple[str, str, int, bool]:
    """Save upload once, dedupe by sha256 against ``upload_dir``.

    Returns ``(relative_path, sha256, byte_size, deduplicated)``.
    When ``deduplicated=True`` the new temp file is removed and the returned
    path points at the existing copy; otherwise the file is kept and named
    ``<sha256>_<original-name>``.
    """
    safe_name = _safe_filename(original_name or "file")
    temp_path = upload_dir / f".tmp-{uuid.uuid4().hex}"
    temp_path, digest, size = await _stream_to_temp_and_hash(upload, temp_path)
    try:
        existing = _list_existing_hash_uploads(upload_dir).get(digest)
        if existing:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            return existing, digest, size, True
        final_name = f"{digest}_{safe_name}"
        final_path = upload_dir / final_name
        try:
            temp_path.rename(final_path)
        except FileExistsError:
            # Race: another request stored the same digest concurrently.
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            existing = _list_existing_hash_uploads(upload_dir).get(digest)
            if existing:
                return existing, digest, size, True
            raise
        rel_path = (Path("assets") / "uploads" / final_name).as_posix()
        return rel_path, digest, size, False
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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

            temp_path = directory / f".tmp-{uuid.uuid4().hex}"
            temp_path, digest, size = await _stream_to_temp_and_hash(upload, temp_path)
            total_size += size
            if total_size > MAX_ATTACHMENT_TOTAL_SIZE:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                raise HTTPException(status_code=413, detail="Attachment directory too large")

            try:
                temp_path.rename(target_path)
            except FileExistsError:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

            saved_files.append({
                "original_name": Path(raw_relative).name,
                "relative_path": relative.as_posix(),
                "path": (Path("assets") / "uploads" / "attachments" / batch_id / relative).as_posix(),
                "size": size,
                "sha256": digest,
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
    deduped_count = 0
    for f in files:
        original_name = f.filename or ""
        if not original_name:
            await f.close()
            continue
        try:
            rel_path, digest, size, deduplicated = await _upload_with_dedupe(
                upload=f,
                upload_dir=upload_dir,
                original_name=original_name,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Upload failed for {original_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}: {e}") from e

        if not rel_path.resolve().is_relative_to(upload_dir_resolved):
            raise HTTPException(status_code=400, detail="Invalid upload path")

        if deduplicated:
            deduped_count += 1
            logger.info("deduped upload %s -> %s", original_name, rel_path)

        saved_files.append(
            {
                "original_name": _safe_filename(original_name),
                "path": rel_path,
                "size": size,
                "sha256": digest,
                "deduplicated": deduplicated,
            }
        )

    if deduped_count:
        logger.info("upload dedupe: %d/%d files reused existing copies", deduped_count, len(files))

    return {"files": saved_files}


@router.post("/upload/check")
async def check_paths(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify that previously-returned upload paths still exist on disk.

    Useful before re-triggering a review so the agent/frontend can detect
    when stored paths have been cleaned up (e.g. by `assets/uploads/`
    rotation) and prompt the user to re-upload.

    Body: ``{"paths": ["assets/uploads/<hash>_workbook.xlsx", ...]}``
    Returns ``{"results": [{path, exists, size, sha256}]}``.
    """
    paths = payload.get("paths") or []
    if not isinstance(paths, list):
        raise HTTPException(status_code=400, detail="paths must be a list of strings")

    workspace_path = Path(os.getenv("WORKSPACE_PATH", os.getcwd()))
    results: list[dict[str, Any]] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw:
            results.append({"path": raw, "exists": False, "error": "invalid path"})
            continue
        try:
            target = (workspace_path / raw).resolve()
            if not target.is_file():
                results.append({"path": raw, "exists": False})
                continue
            digest = _hash_suffix_re.match(target.name)
            sha256 = digest.group(0)[:-1] if digest else None
            results.append({
                "path": raw,
                "exists": True,
                "size": target.stat().st_size,
                "sha256": sha256,
            })
        except Exception as exc:
            results.append({"path": raw, "exists": False, "error": str(exc)})

    return {"results": results}
