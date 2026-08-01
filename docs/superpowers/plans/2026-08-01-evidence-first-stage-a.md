# Evidence-First Stage A Implementation Plan

**Status:** Implemented and locally backend-verified on 2026-08-01. Stage B (policy-pack pilot), Stage C (V2 judgement and verification), Stage D (evaluation and feedback gates), and enterprise capabilities remain pending.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a non-blocking shadow artifact for every completed Excel review: an immutable input manifest, bounded Evidence Graph, and V1 findings/statistics snapshot, without changing the existing review result contract.

**Architecture:** The existing runner completes the V1 review and persists findings exactly as today. It then starts a second, isolated shadow task that reopens the source workbook with formulas intact, creates a V2-format artifact under assets/reviews/<review_id>/, and records its own status in the in-memory registry. Artifact failures are logged and recorded but cannot change the V1 review status or findings.

**Tech Stack:** Python 3.12+, Pydantic 2 (already installed), openpyxl, asyncio, pytest and pytest-asyncio.

## Implementation record

- Tasks 1–4 are implemented: typed V2 shadow-artifact contracts, hashed input manifest and bounded workbook Evidence Graph, atomic artifact storage, and non-blocking runner capture using `asyncio.to_thread`.
- Task 5 verification ran `uv run pytest tests/ -q`: **130 passed, 1 warning**. The warning is LangGraph's third-party deprecation notice for `AgentStatePydantic`; it does not report a test failure, but the run is not warning-free.
- The completion boundary is intentionally limited to Stage A: V1 review status and findings remain authoritative and compatible; artifact failures are isolated from the completed V1 review. No policy-pack executor, V2 finding projection, LLM judgement/verifier, golden-set evaluation, feedback API, database/queue, multi-tenancy, RBAC, approval workflow, or enterprise-readiness claim is included.

## Constraints

- Preserve POST /v1/chat/completions, GET /review/<review_id>/status, GET /findings/<review_id>, and the current findings JSON shape.
- Do not introduce a database, queue, policy-pack executor, LLM prompt change, or frontend change in Stage A.
- Capture workpaper cells only in the Evidence Graph; hash optional checkpoint and attachment-preview files in the input manifest.
- Bound capture with REVIEW_EVIDENCE_SNAPSHOT_MAX_CELLS (default 50000). A truncated graph is explicitly marked truncated and is never used by V1 decisions.
- Use atomic JSON writes. No half-written artifact may be marked completed.
- Keep all Stage A work in the dedicated worktree and feature branch.

### Task 1: V2 contracts

**Files:**

- Create: src/review/contracts.py
- Create: tests/review/test_contracts.py

**Step 1: Write the failing contract tests**

Create tests for:

~~~python
from review.contracts import (
    EvidenceGraph,
    InputFile,
    ReviewManifest,
    SheetEvidence,
    CellEvidence,
)


def test_review_manifest_serializes_optional_inputs():
    manifest = ReviewManifest(
        review_id="a" * 32,
        source="wp.xlsx",
        requested_sheets=["PE-6"],
        inputs=[
            InputFile(
                role="workpaper",
                path="assets/uploads/wp.xlsx",
                filename="wp.xlsx",
                sha256="b" * 64,
                size=12,
            )
        ],
    )
    payload = manifest.model_dump(mode="json")
    assert payload["schema_version"] == "2.0"
    assert payload["inputs"][0]["role"] == "workpaper"
    assert payload["requested_sheets"] == ["PE-6"]


def test_evidence_graph_requires_consistent_capture_counts():
    cell = CellEvidence(
        evidence_id="ev:1",
        sheet_name="PE-6",
        coordinate="A1",
        value="标准审计程序",
        formula=None,
        data_type="s",
        content_hash="c" * 64,
    )
    graph = EvidenceGraph(
        source_sha256="d" * 64,
        sheets=[SheetEvidence(name="PE-6", sheet_hash="e" * 64, cells=[cell])],
        captured_cell_count=1,
        omitted_cell_count=0,
        capture_status="complete",
    )
    assert graph.sheets[0].cells[0].evidence_id == "ev:1"
~~~

**Step 2: Run the tests to verify red**

Run:

~~~bash
uv run pytest tests/review/test_contracts.py -q
~~~

Expected: import failure because review.contracts does not exist.

**Step 3: Implement minimal typed contracts**

Create Pydantic models with:

- SCHEMA_VERSION = "2.0".
- InputRole as Literal["workpaper", "checkpoints", "attachments_preview"].
- InputFile(role, path, filename, sha256, size, media_type default application/vnd.openxmlformats-officedocument.spreadsheetml.sheet).
- CellEvidence(evidence_id, sheet_name, coordinate, value, formula, data_type, content_hash).
- SheetEvidence(name, normalized_name, sheet_hash, max_row, max_column, layout_header_row optional, standard_column optional, execution_columns list[int], merged_ranges list[str], cells list[CellEvidence]).
- EvidenceGraph(source_sha256, sheets, captured_cell_count, omitted_cell_count, capture_status Literal["complete", "truncated"]).
- ReviewManifest(review_id, source, requested_sheets, inputs, engine_version default "stage-a-shadow", artifact_status default "running", schema_version, created_at).

Use Field(default_factory=...) for timestamps and collections. Keep contracts JSON serializable through model_dump(mode="json").

**Step 4: Run the focused tests**

Run:

~~~bash
uv run pytest tests/review/test_contracts.py -q
~~~

Expected: all contract tests pass.

**Step 5: Commit**

~~~bash
git add src/review/contracts.py tests/review/test_contracts.py
git commit -m "feat: add evidence artifact contracts"
~~~

### Task 2: Input manifest and bounded Evidence Graph builder

**Files:**

- Create: src/review/evidence.py
- Create: tests/review/test_evidence.py
- Reference: src/review/excel_utils.py

**Step 1: Write the failing evidence tests**

Cover the following observable behavior:

~~~python
def test_build_input_manifest_hashes_workpaper_and_optional_inputs(tmp_path):
    # Create three tiny files and assert role ordering, basename, size and SHA-256.
    ...


def test_build_evidence_graph_is_deterministic_and_preserves_formula():
    # Workbook: PE-6!A1 text, B2 = "=1+1".
    # Two calls with the same source hash produce the same evidence IDs and sheet hash.
    # B2 has formula == "=1+1" and value == "=1+1".
    ...


def test_build_evidence_graph_marks_explicit_truncation():
    # Workbook with three non-empty cells, max_cells=2.
    # Assert captured_cell_count == 2, omitted_cell_count == 1,
    # capture_status == "truncated", and deterministic row-major capture.
    ...


def test_build_evidence_graph_records_detected_layout_and_merged_ranges():
    # Standard/execution headers and A2:B2 merged.
    # Assert layout metadata and the merged range appear in SheetEvidence.
    ...
~~~

**Step 2: Run the tests to verify red**

Run:

~~~bash
uv run pytest tests/review/test_evidence.py -q
~~~

Expected: import failure because review.evidence does not exist.

**Step 3: Implement evidence.py**

Implement:

~~~python
def sha256_file(path: str | Path) -> str: ...

def build_input_files(
    *,
    workpaper_path: str,
    checkpoints_path: str = "",
    attachments_preview_path: str = "",
) -> list[InputFile]: ...

def build_evidence_graph(
    wb: openpyxl.Workbook,
    *,
    source_sha256: str,
    max_cells: int | None = None,
) -> EvidenceGraph: ...
~~~

Implementation rules:

1. Read files in 1 MiB chunks and use SHA-256.
2. Process optional inputs only when a non-empty path is supplied; missing paths raise FileNotFoundError for the caller to record.
3. Iterate non-empty cells in workbook sheet order and row-major order.
4. For each cell, serialize None/string/numeric/bool/date/time deterministically. Preserve a formula separately when the raw value starts with "=".
5. Compute content_hash from canonical JSON with sorted keys; compute evidence_id from schema prefix, source hash, sheet name, coordinate and content hash.
6. Compute sheet_hash from sheet metadata and ordered cell content hashes.
7. Import _detect_layout and _normalize_sheet_id instead of duplicating layout rules.
8. Read REVIEW_EVIDENCE_SNAPSHOT_MAX_CELLS only when max_cells is omitted; invalid/non-positive values fall back to 50000.
9. Once the global cell cap is reached, continue counting remaining non-empty cells but do not retain them. Set capture_status to truncated and omitted_cell_count accurately.

**Step 4: Run focused tests**

Run:

~~~bash
uv run pytest tests/review/test_evidence.py tests/review/test_excel_utils.py -q
~~~

Expected: all tests pass.

**Step 5: Commit**

~~~bash
git add src/review/evidence.py tests/review/test_evidence.py
git commit -m "feat: build bounded review evidence graph"
~~~

### Task 3: Atomic review artifact store

**Files:**

- Create: src/storage/review_artifact_store.py
- Create: tests/test_review_artifact_store.py

**Step 1: Write the failing store tests**

Test:

~~~python
def test_artifact_store_writes_manifest_evidence_and_v1_findings_atomically(monkeypatch, tmp_path):
    # Begin an artifact, write graph and V1 findings, complete it.
    # Load it again and assert manifest status, evidence IDs and findings.
    ...


def test_artifact_store_marks_failure_without_marking_completed(monkeypatch, tmp_path):
    # Begin then fail. Assert artifact_status == "error" and error contains only type/message.
    ...


def test_artifact_store_rejects_unsafe_review_id(monkeypatch, tmp_path):
    # "../escape" must raise ValueError and create no parent file.
    ...
~~~

**Step 2: Run the tests to verify red**

Run:

~~~bash
uv run pytest tests/test_review_artifact_store.py -q
~~~

Expected: import failure because storage.review_artifact_store does not exist.

**Step 3: Implement atomic storage**

Create ReviewArtifactStore with:

~~~python
class ReviewArtifactStore:
    def begin(self, manifest: ReviewManifest) -> Path: ...
    def write_evidence(self, review_id: str, graph: EvidenceGraph) -> Path: ...
    def write_v1_findings(self, review_id: str, findings: list[dict], stats: dict) -> Path: ...
    def complete(self, review_id: str) -> Path: ...
    def fail(self, review_id: str, error: str) -> Path: ...
    def load_manifest(self, review_id: str) -> dict | None: ...
~~~

Rules:

1. Root path is WORKSPACE_PATH/assets/reviews/<review_id>.
2. Permit only [A-Za-z0-9_-] review IDs; reject path separators and empty values.
3. Serialize model contracts via model_dump(mode="json"), JSON values with ensure_ascii=False, sort_keys=True and indent=2.
4. Use tempfile.NamedTemporaryFile in the target directory, flush, os.fsync and os.replace.
5. begin writes manifest.json with artifact_status=running; complete preserves metadata and changes it to completed; fail changes it to error and records a concise error string.
6. write_v1_findings writes schema_version, findings and stats to findings.json. It does not replace assets/results/<review_id>_findings.json.

**Step 4: Run focused tests**

Run:

~~~bash
uv run pytest tests/test_review_artifact_store.py -q
~~~

Expected: all artifact-store tests pass.

**Step 5: Commit**

~~~bash
git add src/storage/review_artifact_store.py tests/test_review_artifact_store.py
git commit -m "feat: persist atomic review shadow artifacts"
~~~

### Task 4: Runner integration as a non-blocking shadow task

**Files:**

- Modify: src/review/runner.py
- Modify: tests/review/test_runner.py
- Modify: tests/test_integration.py

**Step 1: Write the failing integration tests**

Add tests for:

~~~python
@pytest.mark.asyncio
async def test_completed_review_starts_shadow_artifact_without_changing_v1_result(tmp_path):
    review_id = await start_review(file_path=_make_workbook(tmp_path), source="wp.xlsx")
    await _REGISTRY[review_id]["task"]
    await _REGISTRY[review_id]["shadow_task"]

    assert get_status(review_id)["status"] == "completed"
    assert get_status(review_id)["artifact_status"] == "completed"
    assert load_findings(review_id)["review_id"] == review_id
    assert ReviewArtifactStore().load_manifest(review_id)["artifact_status"] == "completed"


@pytest.mark.asyncio
async def test_shadow_failure_does_not_fail_existing_review(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "build_evidence_graph", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    review_id = await start_review(file_path=_make_workbook(tmp_path), source="wp.xlsx")
    await _REGISTRY[review_id]["task"]
    await _REGISTRY[review_id]["shadow_task"]

    assert get_status(review_id)["status"] == "completed"
    assert get_status(review_id)["artifact_status"] == "error"
    assert load_findings(review_id) is not None
~~~

Update the autouse isolation fixture to cancel and await all outstanding task and shadow_task instances after each test. This removes the existing pending-task warning without changing production behavior.

**Step 2: Run the runner tests to verify red**

Run:

~~~bash
uv run pytest tests/review/test_runner.py tests/test_integration.py -q
~~~

Expected: failures because shadow_task and artifact_status do not exist.

**Step 3: Implement runner integration**

After save_findings succeeds, preserve the existing completed status and stats, then schedule:

~~~python
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
~~~

_capture_shadow_artifact must:

1. Set artifact_status to running.
2. Build input files and a ReviewManifest.
3. Write begin(manifest).
4. Reopen the workpaper with data_only=False so formulas are preserved.
5. Build and write EvidenceGraph.
6. Write V1 findings/statistics and complete the artifact.
7. Set artifact_status to completed.
8. On any exception, log it, call fail when possible, and set artifact_status/error. Never re-raise into the completed V1 task.

get_status must add artifact_status and artifact_error only when present; all existing response fields and values remain unchanged.

**Step 4: Run focused tests**

Run:

~~~bash
uv run pytest tests/review/test_runner.py tests/test_integration.py tests/test_review_artifact_store.py -q
~~~

Expected: all focused tests pass without pending-task warnings.

**Step 5: Commit**

~~~bash
git add src/review/runner.py tests/review/test_runner.py tests/test_integration.py
git commit -m "feat: capture review artifacts in shadow mode"
~~~

### Task 5: Full verification and documentation reconciliation

**Files:**

- Modify: docs/superpowers/specs/2026-08-01-evidence-first-review-engine-v2-design.md
- Modify: docs/superpowers/plans/2026-08-01-evidence-first-stage-a.md

**Step 1: Update design status**

Mark Stage A as implemented only after all verification commands below pass. Keep later stages explicitly pending.

**Step 2: Run backend verification**

Run:

~~~bash
uv run pytest tests/ -q
~~~

Expected: all tests pass; inspect warnings separately rather than calling the run clean if warnings remain.

**Step 3: Run static and diff checks**

Run:

~~~bash
git diff --check
git status --short
~~~

Expected: no whitespace errors; only intended Stage A files changed.

**Step 4: Commit**

~~~bash
git add docs/superpowers/specs/2026-08-01-evidence-first-review-engine-v2-design.md docs/superpowers/plans/2026-08-01-evidence-first-stage-a.md
git commit -m "docs: record evidence-first stage a delivery"
~~~

## Execution notes

- Implement in task order. Do not begin a later task while the preceding task lacks a passing focused test.
- Use @superpowers:test-driven-development for every production behavior change.
- Keep the current review pipeline, findings store and frontend projection untouched except for the runner's additive artifact status fields.
- Before final delivery, use @superpowers:verification-before-completion and report fresh test output, known warnings and exact commits.
