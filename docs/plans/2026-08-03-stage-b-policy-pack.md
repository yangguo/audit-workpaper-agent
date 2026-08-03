# Stage B Policy Pack Pilot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a versioned `itgc-core` JSON policy pack and deterministic shadow execution for three high-value ITGC rules while preserving the Stage-A/V1 user contract.

**Architecture:** Load and validate policy JSON from a repository-owned `policy_packs/` directory. Build a bounded review plan from the Stage-A workbook Evidence Graph, execute only trusted evaluator IDs, validate exact evidence references, deduplicate stable candidates, and persist the plan/findings beside the existing shadow artifact. V1 remains authoritative and runs unchanged.

**Tech Stack:** Python 3.12+, Pydantic 2, openpyxl, existing Evidence Graph/artifact store, pytest/pytest-asyncio, JSON policy files.

### Task 1: Define policy-pack contracts and fixture

**Files:**
- Create: `src/review/policy.py`
- Create: `policy_packs/itgc-core/1.0.0/manifest.json`
- Create: `policy_packs/itgc-core/1.0.0/rules/procedure-interview-only.json`
- Create: `policy_packs/itgc-core/1.0.0/rules/procedure-required-evidence.json`
- Create: `policy_packs/itgc-core/1.0.0/rules/scope-os-db-admin.json`
- Test: `tests/review/test_policy.py`

**Step 1: Write failing tests** for valid loading, deterministic ordering, missing rule rejection, unknown evaluator rejection, and traversal-safe pack selection.

**Step 2: Run** `uv run pytest tests/review/test_policy.py -q`; expect failures because the loader/contracts do not exist.

**Step 3: Implement** strict Pydantic contracts (`PolicyPackManifest`, `PolicyRule`, `PolicyPack`), safe pack ID/version resolution, JSON loading, duplicate rule detection, and evaluator ID allowlisting. Keep policy files declarative; no code or prompt fields.

**Step 4: Run** the focused test; expect all tests to pass.

**Step 5: Commit** `feat: add itgc core policy pack contracts`.

### Task 2: Build facts, planner, and trusted deterministic evaluators

**Files:**
- Create: `src/review/planner.py`
- Create: `src/review/evaluators.py`
- Test: `tests/review/test_planner.py`
- Test: `tests/review/test_evaluators.py`

**Step 1: Write failing tests** for ControlFact/SheetFact evidence IDs, explicit scope failures, the three rule outcomes, stable identity keys, and same-run deduplication.

**Step 2: Run** `uv run pytest tests/review/test_planner.py tests/review/test_evaluators.py -q`; expect failures.

**Step 3: Implement** plan serialization, stable hashes, layout-aware fact extraction, three evaluator registry entries, exact evidence refs, and candidate serialization. Evaluators may use trusted repository helpers/constants but never execute policy-file content.

**Step 4: Run** the focused tests; expect all tests to pass.

**Step 5: Commit** `feat: execute policy pack rules against evidence facts`.

### Task 3: Persist policy shadow artifacts without changing V1

**Files:**
- Modify: `src/review/contracts.py`
- Modify: `src/storage/review_artifact_store.py`
- Modify: `src/review/runner.py`
- Test: `tests/test_review_artifact_store.py`
- Test: `tests/review/test_runner.py`

**Step 1: Write failing tests** for manifest policy-pack metadata, atomic plan/findings files, successful shadow capture, invalid policy-pack isolation, and unchanged V1 findings.

**Step 2: Run** the focused tests; expect failures.

**Step 3: Implement** optional policy-pack metadata, `write_review_plan`, `write_policy_findings`, and Stage-B execution inside the existing `asyncio.to_thread` shadow capture. Use `REVIEW_POLICY_PACK_ID`, `REVIEW_POLICY_PACK_VERSION`, `REVIEW_POLICY_PACK_ROOT`, and `REVIEW_POLICY_MODE=shadow|off` with a privacy-safe deterministic default. Do not add policy findings to V1 results.

**Step 4: Run** focused runner/store tests; expect all tests to pass.

**Step 5: Commit** `feat: persist stage b policy shadow artifacts`.

### Task 4: Configuration and operational documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/review/test_policy.py`

**Step 1: Add** policy-pack environment examples and document artifact paths, default behavior, three pilot rules, and the fact that V1 remains authoritative.

**Step 2: Run** JSON/config checks and the policy tests.

**Step 3: Commit** `docs: document stage b policy pack pilot`.

### Task 5: Full verification and handoff

**Step 1:** Run `uv run pytest -q`, `python -m py_compile src/review/*.py src/storage/review_artifact_store.py`, `uv lock --check`, and `git diff --check`.

**Step 2:** Run the frontend tests, TypeScript check, and production build with the bundled Node runtime to confirm V1 UI compatibility.

**Step 3:** Inspect generated artifact fixtures and staged diff; report any pre-existing warnings separately.

**Step 4:** Commit any final test-only or documentation correction as a separate focused commit.
