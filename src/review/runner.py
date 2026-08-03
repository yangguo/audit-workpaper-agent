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

from review.attachments import build_attachment_index, load_attachments_preview_xlsx
from review.checkpoints import load_checkpoints_xlsx
from review.contracts import PolicyPackRef, ReviewManifest
from review.evidence import build_evidence_graph, build_input_files, sha256_file
from review.evaluators import execute_policy_plan
from review.findings import build_v2_findings, project_v2_findings_to_v1
from review.judgement import build_judgement_requests, execute_judgement_requests
from review.llm import LLM_CALL_STATS, get_review_llm
from review.planner import build_review_plan
from review.policy import load_policy_pack
from review.pipeline import run_review
from storage.findings_store import load_findings, save_findings
from storage.review_artifact_store import ReviewArtifactStore

_logger = logging.getLogger("review.runner")

# review_id -> {status, task, started_at, source, stats?, error?}
_REGISTRY: Dict[str, dict] = {}


def _stage_b_policy_config() -> tuple[str, str, str, str | None]:
    mode = os.getenv("REVIEW_POLICY_MODE", "shadow").strip().lower()
    if mode not in {"shadow", "off"}:
        raise ValueError("REVIEW_POLICY_MODE must be shadow or off")
    pack_id = os.getenv("REVIEW_POLICY_PACK_ID", "itgc-core").strip()
    pack_version = os.getenv("REVIEW_POLICY_PACK_VERSION", "1.0.0").strip()
    root = os.getenv("REVIEW_POLICY_PACK_ROOT", "").strip() or None
    return mode, pack_id, pack_version, root


def _stage_c_judgement_config() -> tuple[str, str, str, str | None, int]:
    mode = os.getenv("REVIEW_JUDGEMENT_MODE", "off").strip().lower()
    if mode not in {"shadow", "off"}:
        raise ValueError("REVIEW_JUDGEMENT_MODE must be shadow or off")
    pack_id = os.getenv("REVIEW_JUDGEMENT_PACK_ID", "itgc-judgement").strip()
    pack_version = os.getenv("REVIEW_JUDGEMENT_PACK_VERSION", "1.0.0").strip()
    root = (
        os.getenv("REVIEW_JUDGEMENT_PACK_ROOT", "").strip()
        or os.getenv("REVIEW_POLICY_PACK_ROOT", "").strip()
        or None
    )
    try:
        max_requests = int(os.getenv("REVIEW_JUDGEMENT_MAX_REQUESTS", "200"))
    except (TypeError, ValueError) as exc:
        raise ValueError("REVIEW_JUDGEMENT_MAX_REQUESTS must be an integer") from exc
    if max_requests <= 0:
        raise ValueError("REVIEW_JUDGEMENT_MAX_REQUESTS must be greater than zero")
    return mode, pack_id, pack_version, root, max_requests


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
    attachments_dir: str = "",
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
        attachments_dir=attachments_dir,
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
    attachments_dir: str,
    attachments_preview_path: str,
    sheets: Optional[str],
    source: str,
) -> None:
    try:
        workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())
        store = ReviewArtifactStore(workspace_path=workspace_path)
        snapshot_error = None
        try:
            snapshot_paths = await asyncio.to_thread(
                store.snapshot_inputs,
                review_id,
                workpaper_path=file_path,
                checkpoints_path=checkpoints_path,
                attachments_dir=attachments_dir,
                attachments_preview_path=attachments_preview_path,
            )
            pinned_file_path = snapshot_paths["workpaper"]
            pinned_checkpoints_path = snapshot_paths.get("checkpoints", "")
            pinned_attachments_dir = snapshot_paths.get("attachments_dir", "")
            pinned_attachments_path = snapshot_paths.get("attachments_preview", "")
        except Exception as e:
            snapshot_error = f"{type(e).__name__}: {e}"
            _logger.exception("review input snapshot %s failed", review_id)
            entry = _REGISTRY.get(review_id)
            if entry is not None:
                entry["artifact_status"] = "error"
                entry["artifact_error"] = snapshot_error
            pinned_file_path = file_path
            pinned_checkpoints_path = checkpoints_path
            pinned_attachments_dir = attachments_dir
            pinned_attachments_path = attachments_preview_path

        wb = openpyxl.load_workbook(pinned_file_path, data_only=True)
        checkpoints = (
            load_checkpoints_xlsx(pinned_checkpoints_path)
            if pinned_checkpoints_path
            else {}
        )
        if pinned_attachments_dir:
            attachments = await asyncio.to_thread(
                build_attachment_index, pinned_attachments_dir
            )
        elif pinned_attachments_path:
            attachments = await asyncio.to_thread(
                load_attachments_preview_xlsx, pinned_attachments_path
            )
        else:
            attachments = {}
        LLM_CALL_STATS.clear()
        llm = get_review_llm()
        findings, stats = await run_review(
            wb=wb,
            checkpoints=checkpoints,
            attachments=attachments,
            attachments_preview=attachments,
            sheets=sheets,
            llm=llm,
        )
        save_findings(review_id, findings, stats, source=source)
        entry = _REGISTRY.get(review_id)
        if entry is not None:
            entry["status"] = "completed"
            entry["stats"] = stats
            if snapshot_error is None:
                entry["artifact_status"] = "pending"
                entry["shadow_task"] = asyncio.create_task(
                    _capture_shadow_artifact(
                        review_id=review_id,
                        file_path=pinned_file_path,
                        checkpoints_path=pinned_checkpoints_path,
                        attachments_dir=pinned_attachments_dir,
                        attachments_preview_path=pinned_attachments_path,
                        sheets=sheets,
                        source=source,
                        findings=findings,
                        stats=stats,
                        llm=llm,
                        attachments=attachments,
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
    attachments_dir: str = "",
    attachments_preview_path: str,
    sheets: Optional[str],
    source: str,
    findings: list[dict],
    stats: dict,
    llm=None,
    attachments: Optional[dict[str, object]] = None,
) -> None:
    """Persist a V2 artifact without affecting the completed V1 review."""
    entry = _REGISTRY.get(review_id)
    if entry is not None:
        entry["artifact_status"] = "running"
    workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())

    try:
        error = await asyncio.to_thread(
            _write_shadow_artifact,
            review_id=review_id,
            file_path=file_path,
            checkpoints_path=checkpoints_path,
            attachments_dir=attachments_dir,
            attachments_preview_path=attachments_preview_path,
            sheets=sheets,
            source=source,
            findings=findings,
            stats=stats,
            workspace_path=workspace_path,
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _logger.exception("shadow artifact capture %s could not start", review_id)

    if error is None:
        try:
            error = await _capture_stage_c_shadow(
                review_id=review_id,
                file_path=file_path,
                sheets=sheets,
                llm=llm,
                attachments=attachments,
                workspace_path=workspace_path,
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            _logger.exception("stage c shadow capture %s failed", review_id)

    entry = _REGISTRY.get(review_id)
    if entry is None:
        return
    if error is None:
        entry["artifact_status"] = "completed"
    else:
        entry["artifact_status"] = "error"
        entry["artifact_error"] = error


def _load_stage_c_snapshot(file_path: str):
    wb = openpyxl.load_workbook(file_path, data_only=False)
    graph = build_evidence_graph(wb, source_sha256=sha256_file(file_path))
    return wb, graph


async def _capture_stage_c_shadow(
    *,
    review_id: str,
    file_path: str,
    sheets: Optional[str],
    llm,
    attachments: Optional[dict[str, object]],
    workspace_path: str,
) -> Optional[str]:
    """Run opt-in Stage-C judgement after V1 and Stage-B capture complete."""
    mode, pack_id, pack_version, pack_root, max_requests = _stage_c_judgement_config()
    if mode == "off":
        return None
    if llm is None:
        return "RuntimeError: Stage C LLM is unavailable"

    store = ReviewArtifactStore(workspace_path=workspace_path)
    try:
        policy_pack = load_policy_pack(
            pack_id=pack_id,
            version=pack_version,
            root=pack_root,
        )
        wb, graph = await asyncio.to_thread(_load_stage_c_snapshot, file_path)
        requests = build_judgement_requests(
            workbook=wb,
            evidence_graph=graph,
            policy_pack=policy_pack,
            sheets=sheets,
            attachments=attachments,
            max_requests=max_requests,
        )
        executions = await execute_judgement_requests(requests, llm=llm)
        engine_version = os.getenv(
            "REVIEW_ENGINE_VERSION", "stage-b-policy-shadow"
        ).strip()
        v2_findings = build_v2_findings(
            requests=requests,
            executions=executions,
            policy_pack=policy_pack,
            engine_version=engine_version,
        )
        policy_metadata = {"id": policy_pack.id, "version": policy_pack.version}
        judgement_payload = {
            "schema_version": "stage-c-judgements/1",
            "engine_version": engine_version,
            "source_sha256": graph.source_sha256,
            "policy_pack": policy_metadata,
            "requests": [request.model_dump(mode="json") for request in requests],
            "results": [result.model_dump(mode="json") for result in executions],
            "stats": {
                "requests": len(requests),
                "results": len(executions),
                "by_verification_status": _count_values(
                    [result.verification_status for result in executions]
                ),
            },
        }
        v2_payload = {
            "schema_version": "stage-c-v2-findings/1",
            "engine_version": engine_version,
            "source_sha256": graph.source_sha256,
            "policy_pack": policy_metadata,
            "findings": v2_findings,
            "v1_projection": project_v2_findings_to_v1(v2_findings),
            "stats": {
                "total_findings": len(v2_findings),
                "by_status": _count_values(
                    [str(item.get("status", "")) for item in v2_findings]
                ),
            },
        }
        await asyncio.to_thread(
            store.write_judgements, review_id, judgement_payload
        )
        await asyncio.to_thread(store.write_v2_findings, review_id, v2_payload)
        return None
    except Exception as e:
        _logger.exception("stage c shadow capture %s failed", review_id)
        return f"{type(e).__name__}: {e}"


def _count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _write_shadow_artifact(
    *,
    review_id: str,
    file_path: str,
    checkpoints_path: str,
    attachments_dir: str = "",
    attachments_preview_path: str,
    sheets: Optional[str],
    source: str,
    findings: list[dict],
    stats: dict,
    workspace_path: str,
) -> Optional[str]:
    """Run synchronous artifact capture off the event-loop thread."""
    store = ReviewArtifactStore(workspace_path=workspace_path)
    try:
        policy_mode, policy_id, policy_version, policy_root = _stage_b_policy_config()
        judgement_mode, judgement_id, judgement_version, _, _ = (
            _stage_c_judgement_config()
        )
        engine_version = os.getenv(
            "REVIEW_ENGINE_VERSION",
            "stage-b-policy-shadow" if policy_mode == "shadow" else "stage-a-shadow",
        ).strip()
        inputs = build_input_files(
            workpaper_path=file_path,
            checkpoints_path=checkpoints_path,
            attachments_dir=attachments_dir,
            attachments_preview_path=attachments_preview_path,
        )
        manifest = ReviewManifest(
            review_id=review_id,
            source=source,
            requested_sheets=[name.strip() for name in sheets.split(",") if name.strip()]
            if sheets
            else [],
            inputs=inputs,
            policy_pack=(
                PolicyPackRef(id=policy_id, version=policy_version)
                if policy_mode == "shadow"
                else None
            ),
            judgement_policy_pack=(
                PolicyPackRef(id=judgement_id, version=judgement_version)
                if judgement_mode == "shadow"
                else None
            ),
            engine_version=engine_version,
        )
        store.begin(manifest)

        wb = openpyxl.load_workbook(file_path, data_only=False)
        graph = build_evidence_graph(wb, source_sha256=inputs[0].sha256)
        store.write_evidence(review_id, graph)
        store.write_v1_findings(review_id, findings, stats)
        if policy_mode == "shadow":
            policy_pack = load_policy_pack(
                pack_id=policy_id,
                version=policy_version,
                root=policy_root,
            )
            plan = build_review_plan(
                wb,
                graph,
                policy_pack,
                sheets=sheets,
                engine_version=engine_version,
            )
            store.write_review_plan(review_id, plan.to_dict())
            policy_findings = execute_policy_plan(plan, policy_pack)
            store.write_policy_findings(review_id, policy_findings)
        store.complete(review_id)
        return None
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _logger.exception("shadow artifact capture %s failed", review_id)
        try:
            store.fail(review_id, error)
        except Exception:
            _logger.exception("shadow artifact failure record %s failed", review_id)
        return error
