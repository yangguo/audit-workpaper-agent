"""Background review runner + in-process registry.

Decouples the long-running review pipeline from the agent tool call: the tool
starts the review as a background asyncio task and returns immediately with a
review_id; the frontend polls GET /review/{review_id}/status until completed,
then fetches GET /findings/{review_id}.

Single uvicorn worker => one event loop => a module-level registry is safe.
Starting a new review cancels any currently-running one to prevent stacking.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import openpyxl

from review.attachments import load_attachments_preview_xlsx
from review.checkpoints import load_checkpoints_xlsx
from review.contracts import ReviewManifest
from review.evidence import build_evidence_graph, build_input_files
from review.llm import LLM_CALL_STATS, get_review_llm
from review.pipeline import run_review
from storage.findings_store import load_findings, save_findings
from storage.review_artifact_store import ReviewArtifactStore

_logger = logging.getLogger("review.runner")

# review_id -> {status, task, started_at, source, stats?, error?}
_REGISTRY: Dict[str, dict] = {}


def _now() -> str:
    return datetime.now().isoformat()


def get_status(review_id: str) -> Optional[dict]:
    entry = _REGISTRY.get(review_id)
    if entry is None:
        return None
    status = {
        "review_id": review_id,
        "status": entry["status"],
        "started_at": entry.get("started_at"),
        "source": entry.get("source"),
        "stats": entry.get("stats"),
        "error": entry.get("error"),
    }
    if "artifact_status" in entry:
        status["artifact_status"] = entry["artifact_status"]
    if "artifact_error" in entry:
        status["artifact_error"] = entry["artifact_error"]
    return status


def list_running() -> List[str]:
    return [rid for rid, e in _REGISTRY.items() if e["status"] == "running"]


def cancel_all_running() -> int:
    """Cancel all currently-running reviews. Returns the number cancelled."""
    n = 0
    for rid, entry in list(_REGISTRY.items()):
        if entry["status"] != "running":
            continue
        task: Optional[asyncio.Task] = entry.get("task")
        if task is not None and not task.done():
            task.cancel()
        entry["status"] = "cancelled"
        n += 1
        _logger.info("cancelled running review %s", rid)
    return n


async def start_review(
    *,
    file_path: str,
    checkpoints_path: str = "",
    attachments_preview_path: str = "",
    sheets: Optional[str] = None,
    source: str = "",
) -> str:
    """Start a background review. Returns the review_id immediately.

    Cancels any prior running review first (prevents stacking / quota burn).
    """
    cancel_all_running()
    review_id = uuid.uuid4().hex
    task = asyncio.create_task(_run_review(
        review_id=review_id,
        file_path=file_path,
        checkpoints_path=checkpoints_path,
        attachments_preview_path=attachments_preview_path,
        sheets=sheets,
        source=source,
    ))
    _REGISTRY[review_id] = {
        "status": "running",
        "task": task,
        "started_at": _now(),
        "source": source,
    }
    _logger.info("started background review %s source=%s", review_id, source)
    return review_id


async def _run_review(
    *,
    review_id: str,
    file_path: str,
    checkpoints_path: str,
    attachments_preview_path: str,
    sheets: Optional[str],
    source: str,
) -> None:
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        checkpoints = load_checkpoints_xlsx(checkpoints_path) if checkpoints_path else {}
        attachments_preview = (
            load_attachments_preview_xlsx(attachments_preview_path)
            if attachments_preview_path else {}
        )
        LLM_CALL_STATS.clear()
        llm = get_review_llm()
        findings, stats = await run_review(
            wb=wb,
            checkpoints=checkpoints,
            attachments_preview=attachments_preview,
            sheets=sheets,
            llm=llm,
        )
        save_findings(review_id, findings, stats, source=source)
        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["status"] = "completed"
            entry["stats"] = stats
            entry["artifact_status"] = "pending"
            entry["shadow_task"] = asyncio.create_task(
                _capture_shadow_artifact(
                    review_id=review_id,
                    file_path=file_path,
                    checkpoints_path=checkpoints_path,
                    attachments_preview_path=attachments_preview_path,
                    sheets=sheets,
                    source=source,
                    findings=findings,
                    stats=stats,
                )
            )
        _logger.info("background review %s completed: %d findings", review_id, len(findings))
    except asyncio.CancelledError:
        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["status"] = "cancelled"
        _logger.info("background review %s cancelled", review_id)
        raise
    except Exception as e:
        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["status"] = "error"
            entry["error"] = f"{type(e).__name__}: {e}"
        _logger.exception("background review %s failed", review_id)


async def _capture_shadow_artifact(
    *,
    review_id: str,
    file_path: str,
    checkpoints_path: str,
    attachments_preview_path: str,
    sheets: Optional[str],
    source: str,
    findings: list[dict],
    stats: dict,
) -> None:
    """Persist a V2 artifact without affecting the completed V1 review."""
    store = ReviewArtifactStore()
    entry = _REGISTRY.get(review_id)
    if entry is not None:
        entry["artifact_status"] = "running"

    try:
        inputs = build_input_files(
            workpaper_path=file_path,
            checkpoints_path=checkpoints_path,
            attachments_preview_path=attachments_preview_path,
        )
        manifest = ReviewManifest(
            review_id=review_id,
            source=source,
            requested_sheets=[name.strip() for name in sheets.split(",") if name.strip()]
            if sheets
            else [],
            inputs=inputs,
        )
        store.begin(manifest)

        wb = openpyxl.load_workbook(file_path, data_only=False)
        graph = build_evidence_graph(wb, source_sha256=inputs[0].sha256)
        store.write_evidence(review_id, graph)
        store.write_v1_findings(review_id, findings, stats)
        store.complete(review_id)

        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["artifact_status"] = "completed"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _logger.exception("shadow artifact capture %s failed", review_id)
        try:
            store.fail(review_id, error)
        except Exception:
            _logger.exception("shadow artifact failure record %s failed", review_id)
        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["artifact_status"] = "error"
            entry["artifact_error"] = error
