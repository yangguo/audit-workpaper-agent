import json

import pytest

from review.contracts import (
    CellEvidence,
    EvidenceGraph,
    InputFile,
    ReviewManifest,
    SheetEvidence,
)
from storage.review_artifact_store import ReviewArtifactStore


def _manifest(review_id: str = "review-123") -> ReviewManifest:
    return ReviewManifest(
        review_id=review_id,
        source="wp.xlsx",
        inputs=[
            InputFile(
                role="workpaper",
                path="assets/uploads/wp.xlsx",
                filename="wp.xlsx",
                sha256="a" * 64,
                size=10,
            )
        ],
    )


def _graph() -> EvidenceGraph:
    return EvidenceGraph(
        source_sha256="a" * 64,
        sheets=[
            SheetEvidence(
                name="PE-6",
                sheet_hash="b" * 64,
                cells=[
                    CellEvidence(
                        evidence_id="ev:1",
                        sheet_name="PE-6",
                        coordinate="A1",
                        value="标准审计程序",
                        formula=None,
                        data_type="s",
                        content_hash="c" * 64,
                    )
                ],
            )
        ],
        captured_cell_count=1,
        omitted_cell_count=0,
        capture_status="complete",
    )


def test_artifact_store_writes_manifest_evidence_and_v1_findings_atomically(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    store = ReviewArtifactStore()

    store.begin(_manifest())
    store.write_evidence("review-123", _graph())
    store.write_v1_findings(
        "review-123",
        [{"issue_type": "示例问题", "severity": "P1"}],
        {"total_findings": 1},
    )
    store.complete("review-123")

    artifact_dir = tmp_path / "assets" / "reviews" / "review-123"
    evidence = json.loads((artifact_dir / "evidence.json").read_text("utf-8"))
    findings = json.loads((artifact_dir / "findings.json").read_text("utf-8"))
    manifest = store.load_manifest("review-123")

    assert manifest["artifact_status"] == "completed"
    assert evidence["sheets"][0]["cells"][0]["evidence_id"] == "ev:1"
    assert findings["findings"][0]["severity"] == "P1"
    assert findings["stats"]["total_findings"] == 1


def test_artifact_store_marks_failure_without_marking_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    store = ReviewArtifactStore()

    store.begin(_manifest())
    store.fail("review-123", "RuntimeError: boom")

    manifest = store.load_manifest("review-123")

    assert manifest["artifact_status"] == "error"
    assert manifest["artifact_error"] == "RuntimeError: boom"


def test_artifact_store_rejects_unsafe_review_id(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    store = ReviewArtifactStore()

    with pytest.raises(ValueError, match="Invalid review_id"):
        store.begin(_manifest("../escape"))

    assert not (tmp_path / "assets" / "escape").exists()
