#!/usr/bin/env python3
"""Evaluate a review-quality manifest against a JSON findings payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running a script by file path does not apply the pytest/uv `pythonpath`
# setting. Add the repository's src directory explicitly for that supported
# invocation, while leaving installed/module execution unchanged.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from review.evaluation import evaluate_quality_cases


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="gold-set manifest JSON")
    parser.add_argument(
        "--results",
        type=Path,
        help="JSON object mapping case_id to finding arrays",
    )
    parser.add_argument("--output", type=Path, help="optional metrics output JSON")
    args = parser.parse_args(argv)
    if not args.manifest or not args.results:
        parser.print_help()
        return 0

    manifest = _load_json(args.manifest)
    results = _load_json(args.results)
    if not isinstance(manifest, dict) or not isinstance(results, dict):
        print("manifest and results must be JSON objects", file=sys.stderr)
        return 2
    v2_results = results.get("v2") if isinstance(results.get("v2"), dict) else None
    v1_results = results.get("v1") if isinstance(results.get("v1"), dict) else results
    report = evaluate_quality_cases(manifest, v1_results, v2_by_case=v2_results)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0 if report.get("promotion_ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
