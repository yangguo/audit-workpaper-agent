"""Atomic filesystem storage for Evidence-First shadow review artifacts."""
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from review.contracts import EvidenceGraph, ReviewManifest, SCHEMA_VERSION


_SAFE_REVIEW_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ReviewArtifactStore:
    """Persist shadow artifacts separately from the existing findings store."""

    def __init__(self, *, workspace_path: str | Path | None = None) -> None:
        self._workspace_path = Path(workspace_path) if workspace_path else None

    def _root_dir(self) -> Path:
        workspace = self._workspace_path or Path(
            os.getenv("WORKSPACE_PATH", os.getcwd())
        )
        root = workspace / "assets" / "reviews"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _artifact_dir(self, review_id: str) -> Path:
        if not review_id or not _SAFE_REVIEW_ID.fullmatch(review_id):
            raise ValueError(f"Invalid review_id: {review_id!r}")
        root = self._root_dir().resolve()
        artifact_dir = (root / review_id).resolve()
        if not artifact_dir.is_relative_to(root):
            raise ValueError(f"Invalid review_id: {review_id!r}")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    @staticmethod
    def _to_json_payload(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    default=str,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return path

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> Path:
        if not source.is_file():
            raise FileNotFoundError(str(source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        try:
            with source.open("rb") as source_handle, os.fdopen(
                file_descriptor, "wb"
            ) as destination_handle:
                while chunk := source_handle.read(1024 * 1024):
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            os.replace(temp_name, destination)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return destination

    @staticmethod
    def _atomic_copytree(source: Path, destination: Path) -> Path:
        if not source.is_dir() or source.is_symlink():
            raise FileNotFoundError(str(source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
        try:
            for child in source.rglob("*"):
                if child.is_symlink():
                    continue
                relative = child.relative_to(source)
                target = temporary / relative
                if child.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif child.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(child, target)
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    def snapshot_inputs(
        self,
        review_id: str,
        *,
        workpaper_path: str,
        checkpoints_path: str = "",
        attachments_dir: str = "",
        attachments_preview_path: str = "",
    ) -> dict[str, str]:
        """Pin every supplied input once for both V1 and artifact capture."""
        snapshots: dict[str, str] = {}
        for role, raw_path in (
            ("workpaper", workpaper_path),
            ("checkpoints", checkpoints_path),
            ("attachments_dir", attachments_dir),
            ("attachments_preview", attachments_preview_path),
        ):
            if not raw_path:
                continue
            source = Path(raw_path)
            destination = self._artifact_dir(review_id) / "inputs" / role / source.name
            if role == "attachments_dir":
                snapshots[role] = str(self._atomic_copytree(source, destination))
            else:
                snapshots[role] = str(self._atomic_copy(source, destination))
        return snapshots

    def _manifest_path(self, review_id: str) -> Path:
        return self._artifact_dir(review_id) / "manifest.json"

    def _load_required_manifest(self, review_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(review_id)
        if manifest is None:
            raise FileNotFoundError(f"Artifact manifest not found: {review_id}")
        return manifest

    def begin(self, manifest: ReviewManifest) -> Path:
        payload = manifest.model_dump(mode="json")
        payload["artifact_status"] = "running"
        return self._atomic_write(self._manifest_path(manifest.review_id), payload)

    def write_evidence(self, review_id: str, graph: EvidenceGraph) -> Path:
        payload = graph.model_dump(mode="json")
        return self._atomic_write(
            self._artifact_dir(review_id) / "evidence.json",
            payload,
        )

    def write_v1_findings(
        self,
        review_id: str,
        findings: list[dict],
        stats: dict,
    ) -> Path:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "findings": findings,
            "stats": stats,
        }
        return self._atomic_write(
            self._artifact_dir(review_id) / "findings.json",
            payload,
        )

    def complete(self, review_id: str) -> Path:
        payload = self._load_required_manifest(review_id)
        payload["artifact_status"] = "completed"
        payload.pop("artifact_error", None)
        return self._atomic_write(self._manifest_path(review_id), payload)

    def fail(self, review_id: str, error: str) -> Path:
        payload = self._load_required_manifest(review_id)
        payload["artifact_status"] = "error"
        payload["artifact_error"] = str(error).strip()[:1000]
        return self._atomic_write(self._manifest_path(review_id), payload)

    def load_manifest(self, review_id: str) -> dict[str, Any] | None:
        path = self._manifest_path(review_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
