# Evidence-First Stage A Final Review Fix Report

**Date:** 2026-08-01
**Branch:** `codex/evidence-first-review-v2`
**Scope:** Final fix wave for the two verified Stage A P1 findings only.

## Outcome

The fix wave pins the workpaper, checkpoints workbook, and attachment-preview workbook before V1 consumes them. V1 and the shadow artifact now read the same immutable snapshot paths, so a completed artifact cannot silently combine V1 findings from one source version with manifest or evidence data from another. Snapshot copying runs through `asyncio.to_thread`, preserving the runner's immediate API and avoiding new file-copy work on the event loop.

Evidence serialization now handles openpyxl `ArrayFormula` and `DataTableFormula` objects explicitly. Their stable fields are encoded as canonical, sorted JSON; DataTable boolean flags are normalized across openpyxl's in-memory booleans and reloaded `"1"` representation. Existing string formula behavior remains unchanged.

## Strict TDD Evidence

### RED

The two regressions were added before production changes and run with:

```bash
uv run pytest tests/review/test_runner.py::test_completed_artifact_uses_v1_input_versions_when_sources_change tests/review/test_evidence.py::test_modern_formulas_are_stable_across_independent_reloads -q
```

Result: exit code 1, `2 failed in 0.57s`.

- Source/version regression: V1 observed the original workpaper and optional inputs, then the test replaced all three source files during review. The completed manifest contained replacement hashes; the first workpaper hash differed (`d84aeed0...` versus original `822c6ce7...`). This reproduced the silent cross-version artifact.
- Formula regression: two independent reloads of the same saved workbook produced different `ArrayFormula` content hashes (`936ca612...` versus `7d9ca7f8...`) because the fallback string contained object identity. Formula text was not available as structured evidence.

### GREEN

After the minimal implementation, the source/version regression passed. The first formula run exposed one implementation detail: openpyxl reloads true DataTable flags as `"1"`; the canonicalizer initially treated those as false. The flag normalization was corrected without changing the test.

The same regression command then produced:

```text
2 passed in 0.36s
```

Affected suites:

```bash
uv run pytest tests/review/test_runner.py tests/review/test_evidence.py tests/test_review_artifact_store.py tests/test_integration.py -q
```

Result: `22 passed, 1 warning in 1.74s`.

Initial full suite:

```bash
uv run pytest tests/ -q
```

Result: `126 passed, 1 warning in 2.59s`.

The warning is the pre-existing third-party LangGraph deprecation for `AgentStatePydantic`; it is not a test failure and was not broadened into this fix wave.

## Design Choices

### Immutable input boundary

`ReviewArtifactStore.snapshot_inputs()` atomically copies each supplied input into:

```text
assets/reviews/<review_id>/inputs/<role>/<original-filename>
```

The copy uses a target-directory temporary file, flush, `fsync`, and `os.replace`. `_run_review()` captures the workspace path and invokes snapshotting with `asyncio.to_thread` before loading any workbook. It then uses the returned pinned paths for:

- the V1 workpaper load;
- checkpoint parsing;
- attachment-preview parsing; and
- the completed review's shadow artifact task.

This pins the identity at the consumption boundary rather than comparing hashes after V1 has already reviewed a potentially different file. If a snapshot is invalid, V1 cannot complete from it; if it is valid, both V1 and the artifact use exactly those bytes.

### Modern formulas

`review.evidence._json_value()` now recognizes:

- `ArrayFormula`: `t`, `ref`, and `text`;
- `DataTableFormula`: `t`, `ref`, `ca`, `dt2D`, `dtr`, `r1`, `r2`, `del1`, and `del2`.

The complete stable field set is serialized with sorted keys and compact separators. The canonical string is retained in both `value` and `formula`, so content hashes and evidence IDs are deterministic and formula information remains inspectable. The existing `=...` string path is unchanged and remains covered by the prior normal-formula test.

## Files Changed

- `src/storage/review_artifact_store.py` — atomic input snapshot support.
- `src/review/runner.py` — pin all supplied inputs before V1 and reuse snapshots for shadow capture.
- `src/review/evidence.py` — deterministic modern-formula serialization.
- `tests/review/test_runner.py` — mutation regression covering workpaper and both optional input roles.
- `tests/review/test_evidence.py` — independent-reload regression covering ArrayFormula and DataTableFormula.
- `docs/superpowers/plans/2026-08-01-evidence-first-stage-a.md` — Stage A verification count updated from 124 to 126.
- `.superpowers/sdd/2026-08-01-evidence-first-stage-a/final-review-fix-report.md` — this report.

No Stage B, C, or D status was changed. No frontend, policy-pack, database, queue, prompt, or V1 findings-contract work was added.

## Self-Review

- Confirmed V1 API parameters, status semantics, findings storage, and result shape remain unchanged.
- Confirmed all supplied input roles are snapshotted once and both V1 and shadow capture receive the pinned paths.
- Confirmed snapshot I/O is off the event loop and the existing shadow capture remains off-thread.
- Confirmed artifact files continue to use atomic writes and snapshot files use the same durability pattern.
- Confirmed independent workbook reloads produce matching content hashes and evidence IDs for both modern formula classes.
- Confirmed normal formulas still serialize as their original `=...` text.
- Confirmed Stage B-D remain pending in documentation.
- Confirmed `git diff --check` had no whitespace errors before final reporting.
- Confirmed the existing untracked `assets/` directory and its manifest were retained and excluded from staging.

## Known Concern

The full suite still reports one existing LangGraph third-party deprecation warning. It is unrelated to these P1 fixes and remains intentionally out of scope.

The final fresh verification and commit SHA are reported in the task handoff because a commit cannot accurately embed its own final SHA.
