# Attachment Directory Evidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the optional attachment-preview workbook with an uploaded attachment directory whose real evidence files are located and analyzed during workpaper review.

**Architecture:** The browser uploads a directory as one isolated bundle while preserving relative paths. The agent passes the returned directory path as `attachments_dir`; the review runner snapshots it, builds a recursive attachment index, matches workpaper references, and includes extracted text from matched files in the existing checkpoint and evidence-step LLM checks. The old preview workbook data model is replaced at the public tool and artifact-contract boundaries, while lower-level matching remains deterministic and testable.

**Tech Stack:** FastAPI multipart upload, Next.js/React directory input, Python `pathlib`/`openpyxl`/`python-pptx`/ZIP XML extraction, pytest, Vitest.

### Task 1: Define the attachment-directory contract

**Files:**
- Create: `tests/review/test_attachment_directory.py`
- Modify: `tests/test_understood_requirement.py`

Write failing tests for recursive directory indexing, relative-path matching, extracted text, and the new `attachments_dir` understood-requirement field.

### Task 2: Implement deterministic directory indexing

**Files:**
- Modify: `src/review/models.py`
- Modify: `src/review/attachments.py`
- Modify: `src/review/checkpoints.py`
- Modify: `src/review/evidence_steps.py`
- Modify: `src/review/pipeline.py`

Add a recursive index with filename/path/index/Sheet lookup maps and bounded text extraction. Feed matched evidence content into existing LLM prompts and emit directory-specific missing/unreadable evidence findings.

### Task 3: Thread the directory through review execution and artifacts

**Files:**
- Modify: `src/tools/review_workpaper.py`
- Modify: `src/review/runner.py`
- Modify: `src/storage/review_artifact_store.py`
- Modify: `src/review/contracts.py`
- Modify: `src/review/evidence.py`

Rename the review input to `attachments_dir`, snapshot the directory, index the pinned copy, and record a deterministic directory digest in the Stage-A manifest.

### Task 4: Upload and select a directory in the UI

**Files:**
- Modify: `src/api/upload.py`
- Modify: `frontend/app/api/upload/route.ts`
- Modify: `frontend/hooks/use-file-upload.tsx`
- Modify: `frontend/components/workbench/ReviewIntakePanel.tsx`
- Modify: `frontend/components/thread/index.tsx`
- Modify: `frontend/components/workbench/types.ts`
- Modify: `frontend/components/workbench/UnderstoodRequirementPanel.tsx`
- Modify: `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
- Modify: `frontend/components/workbench/__tests__/view-model.test.ts`

Support `upload_mode=attachments_dir`, preserve browser-relative paths, and add a separate attachment-directory control while retaining regular workpaper/checkpoint uploads.

### Task 5: Update agent guidance and verify

**Files:**
- Modify: `config/agent_llm_config.json`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: affected Python tests under `tests/`

Update tool instructions and terminology, then run focused pytest/Vitest tests, the full Python suite, and the frontend build/test checks.
