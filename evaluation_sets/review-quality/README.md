# Review quality gold set

This directory stores only the versioned schema and synthetic examples for
review-quality evaluation. Customer workbooks, OCR text, absolute paths and
unredacted excerpts must remain in the approved controlled store.

Each approved case records an input SHA256, an adjudication state, expected
finding match keys, expected status/severity, allowed evidence IDs and (when
applicable) a primary location. Two reviewers must agree on the case before it
can be used as a promotion gate; disagreements are retained as adjudication
records.

Run the evaluator with:

```bash
uv run python scripts/evaluate_review_quality.py \
  --manifest /path/to/manifest.json \
  --results /path/to/results-by-case.json
```

The command returns exit code 2 when adjudication is missing or a quality gate
fails. A result of `promotion_ready=true` is necessary but not sufficient for
promoting Stage C: the release owner must also review the paired V1/V2 report.

