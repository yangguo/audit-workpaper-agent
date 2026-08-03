# Stage C V2 Judgement and Verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a bounded Stage-C LLM judgement/verifier shadow path for evidence-step alignment and A-C procedure correspondence while preserving the Stage-A/B V1 contract.

**Architecture:** Keep V1 `run_review` unchanged. Load a separate declarative `itgc-judgement/1.0.0` pack, derive bounded requests from the same workbook Evidence Graph and pinned attachment index, call the configured LLM with a strict response contract, verify every reference against the request whitelist, and persist `judgements.json` plus `v2-findings.json` in the existing shadow artifact. The mode is opt-in (`REVIEW_JUDGEMENT_MODE=off` by default).

**Tech Stack:** Python 3.13+, Pydantic 2, openpyxl, existing async LLM retry helper, pytest/pytest-asyncio, JSON policy packs.

### Task 1: Add Stage-C policy pack metadata and contracts

**Files:**
- Modify: `src/review/policy.py`
- Create: `policy_packs/itgc-judgement/1.0.0/manifest.json`
- Create: `policy_packs/itgc-judgement/1.0.0/rules/evidence-step-alignment.json`
- Create: `policy_packs/itgc-judgement/1.0.0/rules/procedure-correspondence.json`
- Test: `tests/review/test_policy.py`

**Steps:**
1. Add failing tests for judgement-mode rule metadata, pack loading, and rejection of judgement rules without a question.
2. Run `uv run pytest tests/review/test_policy.py -q`; expect collection/assertion failures.
3. Extend strict policy contracts with `execution_mode`, `judgement_question`, `allowed_decisions`, and trusted judgement evaluator IDs. Add the two JSON rules without executable prompts.
4. Run the focused policy tests; expect all to pass.
5. Commit `feat: define stage c judgement policy pack`.

### Task 2: Build JudgementRequest and exact-reference Verifier

**Files:**
- Create: `src/review/judgement.py`
- Create: `src/review/verifier.py`
- Test: `tests/review/test_judgement.py`
- Test: `tests/review/test_verifier.py`

**Steps:**
1. Write failing tests for bounded request construction, stable request IDs, valid/invalid references, decision/unknown semantics, and one retry followed by invalid downgrade.
2. Run `uv run pytest tests/review/test_judgement.py tests/review/test_verifier.py -q`; expect missing-module failures.
3. Implement frozen Pydantic contracts, request builder for ControlFact plus matched attachment evidence, async LLM execution with one verifier-guided retry, and no-source-repair semantics.
4. Run the focused tests; expect all to pass.
5. Commit `feat: add stage c judgement and evidence verifier`.

### Task 3: Add V2 Finding conversion and artifact storage

**Files:**
- Create: `src/review/findings.py`
- Modify: `src/storage/review_artifact_store.py`
- Modify: `src/review/contracts.py`
- Test: `tests/review/test_findings_v2.py`
- Test: `tests/test_review_artifact_store.py`

**Steps:**
1. Write failing tests for stable V2 identity, decision-to-status mapping, invalid-to-unknown projection, and atomic `judgements.json`/`v2-findings.json` writes.
2. Run the focused tests; expect failures.
3. Implement V2 finding serialization, V1-compatible pure projection, optional manifest judgement-pack metadata, and atomic artifact methods.
4. Run the focused tests; expect all to pass.
5. Commit `feat: serialize stage c v2 findings`.

### Task 4: Integrate opt-in Stage-C shadow execution

**Files:**
- Modify: `src/review/runner.py`
- Modify: `tests/review/test_runner.py`
- Modify: `tests/review/test_contracts.py`

**Steps:**
1. Write failing tests for successful opt-in shadow artifacts, V1 immutability, invalid LLM output isolation, and `REVIEW_JUDGEMENT_MODE=off` behavior.
2. Run `uv run pytest tests/review/test_runner.py tests/review/test_contracts.py -q`; expect failures.
3. Add the async Stage-C capture after V1 completion, load the pinned snapshot, execute requests, write V2 artifacts, and mark only the shadow artifact error on failure. Keep existing Stage-B capture and V1 paths intact.
4. Run the focused runner tests; expect all to pass.
5. Commit `feat: run stage c judgement in shadow artifact`.

### Task 5: Document configuration and verify the full branch

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/review/test_judgement.py`

**Steps:**
1. Add `REVIEW_JUDGEMENT_MODE`, judgement pack ID/version/root, max request limit, and artifact semantics to docs.
2. Run policy JSON checks and the focused Stage-C tests.
3. Run `uv run pytest -q`, `uv run python -m py_compile src/review/*.py src/storage/review_artifact_store.py`, `uv lock --check`, and `git diff --check`.
4. Run frontend tests, TypeScript check, and production build with the bundled Node runtime to confirm no V1 UI schema change.
5. Run `git status --short` and inspect the complete diff; commit any focused correction separately.
