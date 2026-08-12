# Review quality gold set

This directory contains only the versioned schema and synthetic examples for
review-quality evaluation. Customer workbooks, OCR text, absolute paths and
unredacted excerpts must remain in the approved controlled store.

`review-quality/1` manifests remain readable for baseline finding, citation,
location and gate metrics. They can never return `promotion_ready=true` because
they do not carry controlled execution identity or repeated-run evidence.

`review-quality/2` adds the fields needed for a release candidate:

- case-level `input_sha256`, `input_set_sha256` and `execution_sha256`;
- `minimum_runs` (at least five) and an adjudication state;
- controlled `assertion_id`, `claim_subject` and `scope_key` match identity;
- allowed evidence IDs, attachment-support expectation, duplicate/conflict
  expectation and remediation expectation for every expected finding.

Run the evaluator with:

```bash
uv run python scripts/evaluate_review_quality.py \
  --manifest /path/to/manifest.json \
  --results /path/to/results.json
```

The preferred results shape is:

```json
{
  "v1": {"case-id": []},
  "v2": {"case-id": []},
  "repeated_runs": {"case-id": [[], [], [], [], []]}
}
```

Here `v2` means a V1-compatible finding collection carrying the
`review-quality/2` quality envelope (for example, a controlled quality-on
rerun). It is not the raw `stage-c-v2-findings/1` candidate artifact: Stage C
uses a separate judgement contract and remains an SME-reviewed shadow input.

Each repeated run must contain only findings produced with the case's exact
`input_set_sha256` and `execution_sha256`. Missing, changed or mixed execution
identities are reported as `non_comparable_runs`; an input-set mismatch is a
separate hard failure. The evaluator never assumes that an empty result came
from the same runtime.

The report retains scalar metrics for compatibility and adds `metric_details`
for every metric. Each detail includes its numerator, denominator, threshold,
state (`measured` or `not_applicable`) and failing case IDs. In particular it
measures semantic finding stability, status agreement, verified-citation
identity stability, attachment claim support/unresolved rate, internal conflict
rate, false duplicate merges and P0/P1 remediation completeness.

`promotion_ready=true` requires the quality/2 technical gates: five comparable
runs per case; semantic stability at least 0.90; status agreement at least
0.95; complete V1 and candidate citation reproduction; supported publishable attachment claims;
no unresolved publishable conflicts or false duplicate merge; complete P0/P1
remediation; and non-decreasing V2 P0/P1 precision. It also requires at least
six adjudicated cases and 60 adjudicated findings. The command exits with code
2 whenever a gate fails.

The bundled example intentionally contains only one synthetic case. It proves
the input shape and repeated-run calculation, but exits with code 2 because it
is not a real 6-case / 60-finding promotion sample. It must never be used as
release evidence.

`promotion_ready=true` remains necessary, not sufficient: two independent
batches and audit-SME approval are required before a quality-on canary. See
[`docs/runbooks/review-quality-stability-promotion.md`](../../docs/runbooks/review-quality-stability-promotion.md)
for the release and rollback procedure.
