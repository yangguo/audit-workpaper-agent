# MinerU Embedded Evidence Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make embedded images in DOCX/PDF review attachments reachable by MinerU, surface their investigation status in the workbench, and retain only verifiable evidence citations in findings.

**Architecture:** Keep the user-facing logical evidence path (`.embedded_media/<document>::<image>`) stable for prompts, findings, and UI. Add a private logical-to-physical path map for OCR so it resolves the portable on-disk (`__`) name inside the immutable attachment snapshot. Persist no signed URLs. Project the already persisted `stats.evidence_agent` result into a compact workbench evidence-analysis panel; findings retain only attachment references whose excerpts can be verified against extracted/OCR text.

**Tech Stack:** Python 3.13, FastAPI, pypdf, MinerU HTTP API client, pytest, React/TypeScript, Vitest.

### Task 1: Resolve embedded image paths safely

**Files:**

- Modify: `src/review/attachments.py`
- Modify: `src/review/evidence_agent.py`
- Test: `tests/review/test_evidence_agent.py`

**Step 1: Write the failing test**

Create a DOCX fixture containing one image, index it, invoke `ocr_attachment` using its logical `::` path, and assert that the injected MinerU client receives the actual `.embedded_media/<document>__<image>` file.

**Step 2: Verify it fails**

Run: `uv run pytest tests/review/test_evidence_agent.py::test_ocr_tool_reads_docx_embedded_image_from_its_logical_evidence_path -q`

Expected: `indexed_file_not_found`, because the former path resolver treats the logical path as an on-disk filename.

**Step 3: Implement the minimal map**

Build an index-owned normalized logical-path to safe disk-relative-path map. Use it only after a normal indexed-path match, preserve the existing root containment check, and exclude generated `.embedded_media/` files from a future raw attachment scan.

**Step 4: Verify it passes**

Run the focused test and then `uv run pytest tests/review/test_evidence_agent.py tests/review/test_attachment_directory.py -q`.

### Task 2: Fail closed on attachment citations

**Files:**

- Modify: `src/review/pipeline.py`
- Test: `tests/review/test_pipeline.py`

**Step 1: Write failing tests**

Assert that a basis which only names a DOCX does not synthesize every embedded image as evidence. Assert that a backfilled attachment citation contains the exact validated OCR/Agent excerpt when the finding explicitly refers to the matching evidence.

**Step 2: Verify failures**

Run the targeted tests and observe that the old helper adds blank excerpts or unrelated image paths.

**Step 3: Implement the minimal rule**

Remove heuristic document-name-to-all-images backfilling. Backfill only a path that is already indexed and has an exact, known excerpt from an accepted Agent/OCR result; otherwise leave the finding without a fabricated attachment citation.

**Step 4: Verify it passes**

Run `uv run pytest tests/review/test_pipeline.py tests/review/test_attachments.py -q`.

### Task 3: Show evidence-analysis status in the workbench

**Files:**

- Modify: `frontend/components/workbench/types.ts`
- Modify: `frontend/components/workbench/view-model.ts`
- Create: `frontend/components/workbench/EvidenceAnalysisPanel.tsx`
- Modify: `frontend/components/workbench/WorkbenchShell.tsx`
- Test: `frontend/components/workbench/__tests__/view-model.test.ts`
- Test: `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`

**Step 1: Write failing tests**

Provide `stats.evidence_agent` with OCR counters, accepted excerpts, and unresolved items. Assert that the view model preserves the data and the workbench renders calls, successes, unresolved count, source path, excerpt, and an explicit unresolved reason.

**Step 2: Verify failures**

Run the focused Vitest files; the old view model discards `evidence_agent` and the UI has no evidence-analysis panel.

**Step 3: Implement the smallest presentation layer**

Define typed evidence-analysis data, derive it from saved findings stats, and render a bounded, text-only panel. It must distinguish OCR success, failure, timeout, and not-run; it must not expose source filesystem roots, provider tokens, signed URLs, or raw tool arguments.

**Step 4: Verify it passes**

Run `npm test -- --run components/workbench/__tests__/view-model.test.ts components/workbench/__tests__/WorkbenchShell.test.tsx` under Node 20.

### Task 4: End-to-end document probes and full regression

**Files:**

- Test only: temporary synthetic DOCX/PDF samples outside the repository

**Step 1: Validate extraction**

Create safe, synthetic documents containing a known screenshot-like image and verify `build_attachment_index` creates embedded virtual entries for both DOCX and PDF.

**Step 2: Validate MinerU protocol**

Run the client against the no-token lightweight endpoint with synthetic, non-sensitive samples if it is reachable. Treat quota/rate-limit or unavailable-provider results as an external integration limitation, not a successful OCR result.

**Step 3: Run full checks**

Run `uv run pytest tests/ -q`, then under Node 20 run `npm run lint`, `npx tsc --noEmit`, `npm test -- --run`, and `npm run build` from `frontend/`.

**Step 4: Review the diff**

Confirm that no temporary documents, credentials, generated media, or provider URLs are tracked; report the exact confirmed capability boundary.
