"""Deterministic evaluation helpers for review-quality gold sets.

The evaluator intentionally consumes already-produced finding payloads. It
does not invoke an LLM or open a workbook, which keeps promotion decisions
reproducible and makes it safe to run in CI against redacted manifests.
"""

from __future__ import annotations

from collections import Counter
import re
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence


_CATEGORIES = (
    "agreement",
    "legacy_only",
    "shadow_only",
    "status_conflict",
    "evidence_conflict",
    "not_comparable",
)

_WHITESPACE = re.compile(r"\s+")
_MINIMUM_REPEATED_RUNS = 5
_SEMANTIC_STABILITY_THRESHOLD = 0.90
_STATUS_AGREEMENT_THRESHOLD = 0.95
_CITATION_IDENTITY_STABILITY_THRESHOLD = 1.0
_ATTACHMENT_CLAIM_SUPPORT_THRESHOLD = 1.0
_INTERNAL_CONFLICT_THRESHOLD = 0.0
_P0_P1_REMEDIATION_THRESHOLD = 1.0
_MINIMUM_ADJUDICATED_CASES = 6
_MINIMUM_ADJUDICATED_FINDINGS = 60


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_controlled(value: Any) -> str:
    """Normalise compact controlled keys without interpreting display prose."""

    return _WHITESPACE.sub("", _text(value)).casefold()


def _quality_mapping(finding: Mapping[str, Any]) -> Mapping[str, Any]:
    quality = finding.get("quality")
    return quality if isinstance(quality, Mapping) else {}


def _has_quality_v2_envelope(finding: Mapping[str, Any]) -> bool:
    return _text(_quality_mapping(finding).get("schema_version")) == "review-quality/2"


def _scope_key(finding: Mapping[str, Any]) -> str:
    """Return the explicit review scope used for cross-run identity.

    ``scope_key`` is preferred because a future policy pack can define a
    narrower scope than a sheet. Existing V1-compatible findings only expose
    ``sheet`` (or a quality primary location), which remains a deterministic
    fallback. No free-text field is used as a substitute.
    """

    quality = _quality_mapping(finding)
    location = quality.get("primary_location")
    location = location if isinstance(location, Mapping) else {}
    return _normalise_controlled(
        finding.get("scope_key")
        or finding.get("sheet")
        or location.get("sheet")
    )


def semantic_finding_key(finding: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the controlled identity used for repeated-run comparisons.

    The key deliberately excludes run-local finding IDs, display issue types,
    evidence IDs and claim values. Those can legitimately vary as the model
    wording or supporting material evolves, while the assertion/subject/scope
    identity is the thing whose repeatability the promotion gate measures.
    """

    return (
        _normalise_controlled(finding.get("assertion_id")),
        _normalise_controlled(finding.get("claim_subject")),
        _scope_key(finding),
    )


def _complete_semantic_key(key: tuple[str, str, str]) -> bool:
    return all(key)


def _execution_sha256_from_quality(finding: Mapping[str, Any]) -> str:
    provenance = _quality_mapping(finding).get("provenance")
    return (
        _text(provenance.get("execution_sha256"))
        if isinstance(provenance, Mapping)
        else ""
    )


def _input_set_sha256_from_quality(finding: Mapping[str, Any]) -> str:
    provenance = _quality_mapping(finding).get("provenance")
    return (
        _text(provenance.get("input_set_sha256"))
        if isinstance(provenance, Mapping)
        else ""
    )


def _finding_id(finding: Mapping[str, Any]) -> str:
    quality = _quality_mapping(finding)
    return _text(quality.get("finding_id")) or _text(finding.get("finding_id"))


def _effective_status(finding: Mapping[str, Any]) -> str:
    disposition = _quality_mapping(finding).get("disposition")
    if isinstance(disposition, Mapping):
        effective = _text(disposition.get("effective_status"))
        if effective:
            return effective
    return _text(finding.get("status"))


def _verified_evidence_ids(finding: Mapping[str, Any]) -> set[str]:
    citation = _quality_mapping(finding).get("citation_validation")
    if not isinstance(citation, Mapping):
        return set()
    if _text(citation.get("status")) not in {"verified", "partial"}:
        return set()
    return {
        _text(item)
        for item in _as_list(citation.get("evidence_ids"))
        if _text(item)
    }


def _metric_detail(
    value: float | int | None,
    *,
    numerator: float | int,
    denominator: int,
    threshold: float | int | None,
    status: str = "measured",
    failure_case_ids: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "threshold": threshold,
        "status": status,
        "failure_case_ids": sorted({_text(case_id) for case_id in failure_case_ids if _text(case_id)}),
    }


def _failure_case_ids(failures: Iterable[Mapping[str, Any]], code: str) -> list[str]:
    return sorted(
        {
            _text(item.get("case_id"))
            for item in failures
            if _text(item.get("code")) == code and _text(item.get("case_id"))
        }
    )


def _finding_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    match_key = expected.get("match_key") or {}
    if not isinstance(match_key, Mapping):
        return False
    controlled = (
        str(match_key.get("assertion_id", "") or "").strip()
        and str(match_key.get("claim_subject", "") or "").strip()
    )
    # In schema v2, controlled assertion/subject identity outranks mutable
    # display wording. A gold set can still include sheet/value constraints.
    keys = (
        [key for key in match_key if key != "issue_type"]
        if controlled
        else list(match_key)
    )
    for key in keys:
        expected_value = match_key[key]
        if key == "scope_key":
            if _scope_key(actual) != _normalise_controlled(expected_value):
                return False
            continue
        if key in {"assertion_id", "claim_subject"}:
            if _normalise_controlled(actual.get(key)) != _normalise_controlled(
                expected_value
            ):
                return False
            continue
        if str(actual.get(key, "") or "") != str(expected_value or ""):
            return False
    return bool(keys)


def _has_controlled_match_key(expected: Mapping[str, Any]) -> bool:
    match_key = expected.get("match_key") or {}
    return isinstance(match_key, Mapping) and bool(
        str(match_key.get("assertion_id", "") or "").strip()
        and str(match_key.get("claim_subject", "") or "").strip()
        and str(match_key.get("scope_key", "") or "").strip()
    )


def _v2_expected_contract_errors(expected: Mapping[str, Any]) -> list[str]:
    """Return required quality/2 contract fields that are absent or malformed."""

    errors: list[str] = []
    allowed_evidence_ids = expected.get("allowed_evidence_ids")
    if "allowed_evidence_ids" not in expected or not isinstance(
        allowed_evidence_ids, (list, tuple)
    ):
        errors.append("allowed_evidence_ids")

    duplicate_of = expected.get("expected_duplicate_of")
    if "expected_duplicate_of" not in expected:
        errors.append("expected_duplicate_of")
    elif not (
        duplicate_of is None
        or (isinstance(duplicate_of, str) and bool(_text(duplicate_of)))
        or (
            isinstance(duplicate_of, Mapping)
            and all(
                _text(duplicate_of.get(key))
                for key in ("assertion_id", "claim_subject", "scope_key")
            )
        )
    ):
        errors.append("expected_duplicate_of")

    if not isinstance(expected.get("expected_conflict"), bool):
        errors.append("expected_conflict")

    remediation = expected.get("expected_remediation")
    if not isinstance(remediation, Mapping) or not isinstance(
        remediation.get("required"), bool
    ):
        errors.append("expected_remediation")
    return errors


def _display_match_key(expected: Mapping[str, Any]) -> dict[str, Any]:
    match_key = expected.get("match_key")
    return dict(match_key) if isinstance(match_key, Mapping) else {}


def _evidence_ids_from_quality(finding: Mapping[str, Any]) -> set[str]:
    quality = finding.get("quality")
    if not isinstance(quality, Mapping):
        return set()
    citation = quality.get("citation_validation")
    if not isinstance(citation, Mapping):
        return set()
    return {
        str(item).strip()
        for item in _as_list(citation.get("evidence_ids"))
        if str(item).strip()
    }


def _evidence_ids_from_v2(finding: Mapping[str, Any]) -> set[str]:
    refs = finding.get("evidence_refs_v2")
    result: set[str] = set()
    for ref in _as_list(refs):
        if not isinstance(ref, Mapping):
            continue
        evidence_id = str(ref.get("evidence_id", "") or "").strip()
        if evidence_id:
            result.add(evidence_id)
    return result


def _input_sha256_from_quality(finding: Mapping[str, Any]) -> str:
    quality = finding.get("quality")
    provenance = quality.get("provenance") if isinstance(quality, Mapping) else None
    return (
        str(provenance.get("input_sha256", "") or "").strip()
        if isinstance(provenance, Mapping)
        else ""
    )


def _primary_location_matches(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> bool:
    expected_location = expected.get("primary_location")
    if expected_location is None:
        return True
    quality = actual.get("quality")
    actual_location = quality.get("primary_location") if isinstance(quality, Mapping) else None
    if not isinstance(actual_location, Mapping):
        return False
    for key in ("source_kind", "sheet", "cell_or_range"):
        expected_value = expected_location.get(key)
        if expected_value is None:
            continue
        if str(actual_location.get(key, "") or "") != str(expected_value or ""):
            return False
    return True


def _has_gate_status(finding: Mapping[str, Any]) -> bool:
    quality = finding.get("quality")
    gates = quality.get("gates") if isinstance(quality, Mapping) else None
    if not isinstance(gates, Mapping) or not gates:
        return False
    return all(
        isinstance(gate, Mapping) and str(gate.get("status", "") or "").strip()
        for gate in gates.values()
    )


def _not_run_encoded_as_passed(gate: Mapping[str, Any]) -> bool:
    if str(gate.get("status", "") or "").strip() != "passed":
        return False
    reason = str(gate.get("reason", "") or "").strip().casefold()
    return "not_run" in reason or "not run" in reason or "未执行" in reason


def _minimum_runs(raw_case: Mapping[str, Any]) -> int:
    value = raw_case.get("minimum_runs", _MINIMUM_REPEATED_RUNS)
    try:
        return max(_MINIMUM_REPEATED_RUNS, int(value))
    except (TypeError, ValueError):
        return _MINIMUM_REPEATED_RUNS


def _v2_case_contract_errors(raw_case: Mapping[str, Any]) -> list[str]:
    """Validate required quality/2 case fields without trusting a prior schema pass."""

    errors = [
        field
        for field in (
            "case_id",
            "input_sha256",
            "input_set_sha256",
            "execution_sha256",
        )
        if not _text(raw_case.get(field))
    ]
    minimum_runs = raw_case.get("minimum_runs")
    if (
        isinstance(minimum_runs, bool)
        or not isinstance(minimum_runs, int)
        or minimum_runs < _MINIMUM_REPEATED_RUNS
    ):
        errors.append("minimum_runs")
    if _text(raw_case.get("adjudication_status")) not in {
        "pending",
        "adjudicated",
    }:
        errors.append("adjudication_status")
    if not isinstance(raw_case.get("expected_findings"), list):
        errors.append("expected_findings")
    return errors


def _run_by_semantic_key(
    run: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str, str], list[Mapping[str, Any]]], list[Mapping[str, Any]]]:
    """Group a run only when every identity component is controlled."""

    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    invalid: list[Mapping[str, Any]] = []
    for finding in run:
        key = semantic_finding_key(finding)
        if not _complete_semantic_key(key):
            invalid.append(finding)
            continue
        grouped.setdefault(key, []).append(finding)
    return grouped, invalid


def _jaccard(left: set[tuple[str, str, str]], right: set[tuple[str, str, str]]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def _status_signature(findings: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({_effective_status(finding) for finding in findings}))


def _evidence_signature(findings: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({item for finding in findings for item in _verified_evidence_ids(finding)}))


def evaluate_repeated_runs(
    manifest: Mapping[str, Any],
    runs_by_case: Mapping[str, Sequence[Sequence[Mapping[str, Any]]]],
) -> dict[str, Any]:
    """Measure whether a quality/2 gold set is stable across comparable runs.

    An empty run has no per-finding provenance to prove its execution identity,
    so it is deliberately non-comparable rather than treated as a stable empty
    result. This keeps a changed model, prompt bundle, or policy pack from
    passing the gate by producing fewer findings.
    """

    failures: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if str(manifest.get("schema_version", "") or "") != "review-quality/2":
        failures.append({"code": "legacy_manifest_not_promotion_eligible", "case_id": ""})
    if not isinstance(cases, list):
        return {
            "promotion_ready": False,
            "metrics": {},
            "metric_details": {},
            "case_results": [],
            "failures": [{"code": "invalid_manifest", "case_id": ""}],
        }
    if not isinstance(runs_by_case, Mapping):
        runs_by_case = {}

    jaccard_total = 0.0
    jaccard_pairs = 0
    status_agreeing = 0
    status_total = 0
    citation_agreeing = 0
    citation_total = 0

    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            failures.append({"code": "invalid_case", "case_id": ""})
            continue
        case_id = _text(raw_case.get("case_id"))
        for field in _v2_case_contract_errors(raw_case):
            failures.append(
                {"code": "invalid_v2_case", "case_id": case_id, "field": field}
            )
        minimum_runs = _minimum_runs(raw_case)
        supplied_runs = _as_list(runs_by_case.get(case_id, []))
        runs = [
            [finding for finding in _as_list(raw_run) if isinstance(finding, Mapping)]
            for raw_run in supplied_runs
        ]
        case_failures_before = len(failures)
        if len(runs) < minimum_runs:
            failures.append(
                {
                    "code": "insufficient_repeated_runs",
                    "case_id": case_id,
                    "actual_runs": len(runs),
                    "minimum_runs": minimum_runs,
                }
            )

        expected_execution_sha256 = _text(raw_case.get("execution_sha256"))
        if not expected_execution_sha256:
            failures.append(
                {
                    "code": "non_comparable_runs",
                    "case_id": case_id,
                    "reason": "missing_expected_execution_sha256",
                }
            )
        expected_input_set_sha256 = _text(raw_case.get("input_set_sha256"))
        if not expected_input_set_sha256:
            failures.append(
                {"code": "missing_input_set_sha256", "case_id": case_id}
            )

        groups_by_run: list[dict[tuple[str, str, str], list[Mapping[str, Any]]]] = []
        execution_sets: list[set[str]] = []
        input_set_sets: list[set[str]] = []
        for run_index, run in enumerate(runs):
            grouped, invalid = _run_by_semantic_key(run)
            groups_by_run.append(grouped)
            execution_set = {_execution_sha256_from_quality(finding) for finding in run}
            execution_sets.append(execution_set)
            input_set_set = {_input_set_sha256_from_quality(finding) for finding in run}
            input_set_sets.append(input_set_set)
            if execution_set != {expected_execution_sha256}:
                failures.append(
                    {
                        "code": "non_comparable_runs",
                        "case_id": case_id,
                        "run_index": run_index,
                        "expected_execution_sha256": expected_execution_sha256,
                        "actual_execution_sha256": sorted(execution_set),
                    }
                )
            if input_set_set != {expected_input_set_sha256}:
                failures.append(
                    {
                        "code": "input_set_sha256_mismatch",
                        "case_id": case_id,
                        "run_index": run_index,
                        "expected_input_set_sha256": expected_input_set_sha256,
                        "actual_input_set_sha256": sorted(input_set_set),
                    }
                )
            for finding in run:
                if not _has_quality_v2_envelope(finding):
                    failures.append(
                        {
                            "code": "quality_schema_not_promotion_eligible",
                            "case_id": case_id,
                            "run_index": run_index,
                            "finding_id": _finding_id(finding),
                            "schema_version": _text(
                                _quality_mapping(finding).get("schema_version")
                            ),
                        }
                    )
            for finding in invalid:
                failures.append(
                    {
                        "code": "non_comparable_finding_identity",
                        "case_id": case_id,
                        "run_index": run_index,
                        "finding_id": _finding_id(finding),
                    }
                )

        comparable = (
            len(runs) >= minimum_runs
            and bool(expected_execution_sha256)
            and bool(expected_input_set_sha256)
            and all(execution_set == {expected_execution_sha256} for execution_set in execution_sets)
            and all(input_set_set == {expected_input_set_sha256} for input_set_set in input_set_sets)
            and all(
                _has_quality_v2_envelope(finding)
                for run in runs
                for finding in run
            )
            and not any(
                failure.get("case_id") == case_id
                and failure.get("code") == "non_comparable_finding_identity"
                for failure in failures
            )
        )
        case_metrics: dict[str, float | None] = {
            "semantic_finding_stability": None,
            "status_agreement_rate": None,
            "citation_identity_stability": None,
        }
        if comparable:
            key_sets = [set(grouped) for grouped in groups_by_run]
            pair_scores = [
                _jaccard(left, right)
                for left, right in combinations(key_sets, 2)
            ]
            pair_score = sum(pair_scores)
            pair_count = len(pair_scores)
            semantic_stability = pair_score / pair_count if pair_count else 0.0
            case_metrics["semantic_finding_stability"] = semantic_stability
            jaccard_total += pair_score
            jaccard_pairs += pair_count
            if semantic_stability < _SEMANTIC_STABILITY_THRESHOLD:
                failures.append(
                    {
                        "code": "semantic_stability_below_threshold",
                        "case_id": case_id,
                        "value": semantic_stability,
                        "threshold": _SEMANTIC_STABILITY_THRESHOLD,
                    }
                )

            common_keys = set.intersection(*key_sets) if key_sets else set()
            for key in common_keys:
                status_signatures = [
                    _status_signature(grouped[key]) for grouped in groups_by_run
                ]
                evidence_signatures = [
                    _evidence_signature(grouped[key]) for grouped in groups_by_run
                ]
                status_total += 1
                citation_total += 1
                if len(set(status_signatures)) == 1:
                    status_agreeing += 1
                if len(set(evidence_signatures)) == 1:
                    citation_agreeing += 1
            if common_keys:
                case_metrics["status_agreement_rate"] = sum(
                    1
                    for key in common_keys
                    if len(
                        {
                            _status_signature(grouped[key])
                            for grouped in groups_by_run
                        }
                    )
                    == 1
                ) / len(common_keys)
                case_metrics["citation_identity_stability"] = sum(
                    1
                    for key in common_keys
                    if len(
                        {
                            _evidence_signature(grouped[key])
                            for grouped in groups_by_run
                        }
                    )
                    == 1
                ) / len(common_keys)
            else:
                failures.append(
                    {
                        "code": "status_agreement_not_comparable",
                        "case_id": case_id,
                    }
                )
                failures.append(
                    {
                        "code": "citation_identity_not_comparable",
                        "case_id": case_id,
                    }
                )

            if (
                case_metrics["status_agreement_rate"] is not None
                and case_metrics["status_agreement_rate"] < _STATUS_AGREEMENT_THRESHOLD
            ):
                failures.append(
                    {
                        "code": "status_agreement_below_threshold",
                        "case_id": case_id,
                        "value": case_metrics["status_agreement_rate"],
                        "threshold": _STATUS_AGREEMENT_THRESHOLD,
                    }
                )
            if (
                case_metrics["citation_identity_stability"] is not None
                and case_metrics["citation_identity_stability"]
                < _CITATION_IDENTITY_STABILITY_THRESHOLD
            ):
                failures.append(
                    {
                        "code": "citation_identity_stability_below_threshold",
                        "case_id": case_id,
                        "value": case_metrics["citation_identity_stability"],
                        "threshold": _CITATION_IDENTITY_STABILITY_THRESHOLD,
                    }
                )

        case_results.append(
            {
                "case_id": case_id,
                "run_count": len(runs),
                "minimum_runs": minimum_runs,
                "comparable": comparable,
                "input_set_sha256": expected_input_set_sha256,
                "execution_sha256": expected_execution_sha256,
                "metrics": case_metrics,
                "failure_count": len(failures) - case_failures_before,
            }
        )

    semantic_value = jaccard_total / jaccard_pairs if jaccard_pairs else None
    status_value = status_agreeing / status_total if status_total else None
    citation_value = citation_agreeing / citation_total if citation_total else None
    metrics = {
        "semantic_finding_stability": semantic_value,
        "status_agreement_rate": status_value,
        "citation_identity_stability": citation_value,
    }
    metric_details = {
        "semantic_finding_stability": _metric_detail(
            semantic_value,
            numerator=jaccard_total,
            denominator=jaccard_pairs,
            threshold=_SEMANTIC_STABILITY_THRESHOLD,
            status="measured" if jaccard_pairs else "not_applicable",
            failure_case_ids=_failure_case_ids(
                failures, "semantic_stability_below_threshold"
            ),
        ),
        "status_agreement_rate": _metric_detail(
            status_value,
            numerator=status_agreeing,
            denominator=status_total,
            threshold=_STATUS_AGREEMENT_THRESHOLD,
            status="measured" if status_total else "not_applicable",
            failure_case_ids=(
                _failure_case_ids(failures, "status_agreement_below_threshold")
                + _failure_case_ids(failures, "status_agreement_not_comparable")
            ),
        ),
        "citation_identity_stability": _metric_detail(
            citation_value,
            numerator=citation_agreeing,
            denominator=citation_total,
            threshold=_CITATION_IDENTITY_STABILITY_THRESHOLD,
            status="measured" if citation_total else "not_applicable",
            failure_case_ids=(
                _failure_case_ids(failures, "citation_identity_stability_below_threshold")
                + _failure_case_ids(failures, "citation_identity_not_comparable")
            ),
        ),
    }
    return {
        "promotion_ready": not failures,
        "metrics": metrics,
        "metric_details": metric_details,
        "case_results": case_results,
        "failures": failures,
    }


def _p0_p1_precision_measure(
    manifest: Mapping[str, Any],
    results_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[float, int, int, set[str]]:
    """Calculate high-risk precision plus the auditable count components."""

    expected_high = 0
    actual_high = 0
    correct = 0
    failure_cases: set[str] = set()
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(cases, list):
        return 0.0, 0, 0, failure_cases
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            continue
        case_id = _text(raw_case.get("case_id"))
        expected = [
            item
            for item in _as_list(raw_case.get("expected_findings"))
            if isinstance(item, Mapping)
        ]
        actual = [
            item
            for item in _as_list(results_by_case.get(case_id, []))
            if isinstance(item, Mapping)
        ]
        high_indexes = {
            index
            for index, item in enumerate(actual)
            if _text(item.get("severity")) in {"P0", "P1"}
        }
        actual_high += len(high_indexes)
        used: set[int] = set()
        for expected_finding in expected:
            if _text(expected_finding.get("severity")) not in {"P0", "P1"}:
                continue
            expected_high += 1
            index = next(
                (
                    idx
                    for idx, actual_finding in enumerate(actual)
                    if idx not in used
                    and _finding_matches(expected_finding, actual_finding)
                ),
                None,
            )
            if index is None:
                failure_cases.add(case_id)
                continue
            used.add(index)
            actual_finding = actual[index]
            if (
                _text(actual_finding.get("severity"))
                == _text(expected_finding.get("severity"))
                and _text(actual_finding.get("status"))
                == _text(expected_finding.get("status"))
            ):
                correct += 1
            else:
                failure_cases.add(case_id)
        if high_indexes - used:
            failure_cases.add(case_id)
    if actual_high == 0:
        return (1.0 if expected_high == 0 else 0.0), correct, actual_high, failure_cases
    return correct / actual_high, correct, actual_high, failure_cases


def _expected_evidence_ids(expected: Mapping[str, Any]) -> set[str]:
    """Read the V2 allow-list while retaining V1 manifest compatibility."""

    raw_ids = expected.get("allowed_evidence_ids")
    if raw_ids is None:
        raw_ids = expected.get("evidence_ids")
    return {_text(item) for item in _as_list(raw_ids) if _text(item)}


def _semantic_key_from_match_key(match_key: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _normalise_controlled(match_key.get("assertion_id")),
        _normalise_controlled(match_key.get("claim_subject")),
        _normalise_controlled(match_key.get("scope_key") or match_key.get("sheet")),
    )


def _matched_quality_pairs(
    raw_case: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    expected = [
        item
        for item in _as_list(raw_case.get("expected_findings"))
        if isinstance(item, Mapping)
    ]
    actual = [item for item in findings if isinstance(item, Mapping)]
    used: set[int] = set()
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for expected_finding in expected:
        index = next(
            (
                candidate_index
                for candidate_index, actual_finding in enumerate(actual)
                if candidate_index not in used
                and _finding_matches(expected_finding, actual_finding)
            ),
            None,
        )
        if index is not None:
            used.add(index)
            pairs.append((expected_finding, actual[index]))
    return pairs


def _citation_reproduction_measure(
    manifest: Mapping[str, Any],
    findings_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[int, int, set[str]]:
    """Return reproduced/expected citations for one structured result set."""

    reproduced = 0
    expected_total = 0
    failure_cases: set[str] = set()
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else []
    for raw_case in cases if isinstance(cases, list) else []:
        if not isinstance(raw_case, Mapping):
            continue
        case_id = _text(raw_case.get("case_id"))
        actual = [
            finding
            for finding in _as_list(findings_by_case.get(case_id, []))
            if isinstance(finding, Mapping)
        ]
        used: set[int] = set()
        for expected in _as_list(raw_case.get("expected_findings")):
            if not isinstance(expected, Mapping):
                continue
            expected_ids = _expected_evidence_ids(expected)
            if not expected_ids:
                continue
            expected_total += 1
            index = next(
                (
                    candidate_index
                    for candidate_index, finding in enumerate(actual)
                    if candidate_index not in used
                    and _finding_matches(expected, finding)
                ),
                None,
            )
            if index is None:
                failure_cases.add(case_id)
                continue
            used.add(index)
            finding = actual[index]
            citation = _quality_mapping(finding).get("citation_validation")
            actual_ids = _evidence_ids_from_quality(finding)
            if (
                isinstance(citation, Mapping)
                and _text(citation.get("status")) == "verified"
                and expected_ids.issubset(actual_ids)
            ):
                reproduced += 1
            else:
                failure_cases.add(case_id)
    return reproduced, expected_total, failure_cases


def _is_conflicted(finding: Mapping[str, Any]) -> bool:
    consistency = _quality_mapping(finding).get("consistency")
    if not isinstance(consistency, Mapping):
        return False
    return (
        _text(consistency.get("status")) == "conflicted"
        or bool(_as_list(consistency.get("conflict_ids")))
    )


def _remediation_complete(finding: Mapping[str, Any]) -> bool:
    remediation = _quality_mapping(finding).get("remediation")
    if not isinstance(remediation, Mapping):
        return False
    return bool(
        _text(remediation.get("status")) == "actionable"
        and _text(remediation.get("action"))
        and _as_list(remediation.get("required_evidence"))
        and _as_list(remediation.get("acceptance_criteria"))
    )


def _quality_gate_metrics(
    manifest: Mapping[str, Any],
    findings_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[dict[str, float | int | None], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Evaluate V2-only support, conflict, duplicate and remediation gates."""

    failures: list[dict[str, Any]] = []
    attachment_supported = 0
    attachment_publishable = 0
    attachment_total = 0
    attachment_unknown = 0
    attachment_failure_cases: set[str] = set()
    conflict_count = 0
    publishable_count = 0
    conflict_failure_cases: set[str] = set()
    duplicate_count = 0
    false_duplicate_count = 0
    false_duplicate_cases: set[str] = set()
    remediation_complete_count = 0
    remediation_total = 0
    remediation_failure_cases: set[str] = set()

    cases = manifest.get("cases") if isinstance(manifest, Mapping) else []
    for raw_case in cases if isinstance(cases, list) else []:
        if not isinstance(raw_case, Mapping):
            continue
        case_id = _text(raw_case.get("case_id"))
        actual = [
            finding
            for finding in _as_list(findings_by_case.get(case_id, []))
            if isinstance(finding, Mapping)
        ]
        pairs = _matched_quality_pairs(raw_case, actual)
        expected_duplicate_rules: dict[tuple[str, str, str], Any] = {}
        for expected in _as_list(raw_case.get("expected_findings")):
            if not isinstance(expected, Mapping):
                continue
            match_key = expected.get("match_key")
            if isinstance(match_key, Mapping) and "expected_duplicate_of" in expected:
                expected_duplicate_rules[_semantic_key_from_match_key(match_key)] = (
                    expected.get("expected_duplicate_of")
                )

        for expected, finding in pairs:
            requires_attachment_support = bool(
                expected.get("requires_attachment_support", False)
            )
            effective_status = _effective_status(finding)
            claim_support = _quality_mapping(finding).get("claim_support")
            support_status = (
                _text(claim_support.get("status"))
                if isinstance(claim_support, Mapping)
                else ""
            )
            if requires_attachment_support:
                attachment_total += 1
                if effective_status == "unknown" and support_status != "supported":
                    attachment_unknown += 1
                if effective_status == "fail":
                    attachment_publishable += 1
                    if support_status == "supported":
                        attachment_supported += 1
                    else:
                        attachment_failure_cases.add(case_id)

            expected_conflict = expected.get("expected_conflict")
            if isinstance(expected_conflict, bool) and _is_conflicted(finding) != expected_conflict:
                failures.append(
                    {
                        "code": "conflict_expectation_mismatch",
                        "case_id": case_id,
                        "finding_id": _finding_id(finding),
                        "expected": expected_conflict,
                        "actual": _is_conflicted(finding),
                    }
                )

            expected_remediation = expected.get("expected_remediation")
            if isinstance(expected_remediation, Mapping):
                remediation = _quality_mapping(finding).get("remediation")
                remediation = remediation if isinstance(remediation, Mapping) else {}
                if bool(expected_remediation.get("required")) and not _remediation_complete(finding):
                    failures.append(
                        {
                            "code": "remediation_expectation_mismatch",
                            "case_id": case_id,
                            "finding_id": _finding_id(finding),
                            "reason": "required_remediation_incomplete",
                        }
                    )
                expected_status = _text(expected_remediation.get("status"))
                if expected_status and _text(remediation.get("status")) != expected_status:
                    failures.append(
                        {
                            "code": "remediation_expectation_mismatch",
                            "case_id": case_id,
                            "finding_id": _finding_id(finding),
                            "expected": expected_status,
                            "actual": _text(remediation.get("status")),
                        }
                    )

        ids = {_finding_id(finding): finding for finding in actual if _finding_id(finding)}
        for finding in actual:
            if _effective_status(finding) == "fail":
                publishable_count += 1
                if _is_conflicted(finding):
                    conflict_count += 1
                    conflict_failure_cases.add(case_id)
            if (
                _effective_status(finding) == "fail"
                and _text(finding.get("severity")) in {"P0", "P1"}
            ):
                remediation_total += 1
                if _remediation_complete(finding):
                    remediation_complete_count += 1
                else:
                    remediation_failure_cases.add(case_id)

            grouping = _quality_mapping(finding).get("grouping")
            duplicate_of = (
                _text(grouping.get("duplicate_of"))
                if isinstance(grouping, Mapping)
                else ""
            )
            if not duplicate_of:
                continue
            duplicate_count += 1
            parent = ids.get(duplicate_of)
            child_key = semantic_finding_key(finding)
            parent_key = semantic_finding_key(parent) if parent is not None else ("", "", "")
            expected_rule = expected_duplicate_rules.get(child_key, object())
            false_merge = (
                parent is None
                or not _complete_semantic_key(child_key)
                or child_key != parent_key
                or expected_rule is None
            )
            if isinstance(expected_rule, Mapping):
                expected_parent_key = _semantic_key_from_match_key(expected_rule)
                false_merge = false_merge or parent_key != expected_parent_key
            elif isinstance(expected_rule, str) and expected_rule:
                false_merge = false_merge or duplicate_of != expected_rule
            if false_merge:
                false_duplicate_count += 1
                false_duplicate_cases.add(case_id)
                failures.append(
                    {
                        "code": "false_duplicate_merge_detected",
                        "case_id": case_id,
                        "finding_id": _finding_id(finding),
                        "duplicate_of": duplicate_of,
                    }
                )

    attachment_rate = (
        attachment_supported / attachment_publishable
        if attachment_publishable
        else None
    )
    attachment_unknown_rate = (
        attachment_unknown / attachment_total if attachment_total else None
    )
    conflict_rate = conflict_count / publishable_count if publishable_count else None
    remediation_rate = (
        remediation_complete_count / remediation_total if remediation_total else None
    )
    metrics: dict[str, float | int | None] = {
        "attachment_claim_support_rate": attachment_rate,
        "attachment_claim_unresolved_rate": attachment_unknown_rate,
        "internal_conflict_rate": conflict_rate,
        "false_duplicate_merge_count": false_duplicate_count,
        "p0_p1_remediation_completeness": remediation_rate,
    }
    if attachment_rate is not None and attachment_rate < _ATTACHMENT_CLAIM_SUPPORT_THRESHOLD:
        failures.append(
            {
                "code": "attachment_claim_support_rate_below_100",
                "case_id": "",
                "rate": attachment_rate,
            }
        )
    if conflict_rate is not None and conflict_rate > _INTERNAL_CONFLICT_THRESHOLD:
        failures.append(
            {
                "code": "internal_conflict_rate_above_zero",
                "case_id": "",
                "rate": conflict_rate,
            }
        )
    if remediation_rate is not None and remediation_rate < _P0_P1_REMEDIATION_THRESHOLD:
        failures.append(
            {
                "code": "p0_p1_remediation_incomplete",
                "case_id": "",
                "rate": remediation_rate,
            }
        )
    details = {
        "attachment_claim_support_rate": _metric_detail(
            attachment_rate,
            numerator=attachment_supported,
            denominator=attachment_publishable,
            threshold=_ATTACHMENT_CLAIM_SUPPORT_THRESHOLD,
            status="measured" if attachment_publishable else "not_applicable",
            failure_case_ids=attachment_failure_cases,
        ),
        "attachment_claim_unresolved_rate": _metric_detail(
            attachment_unknown_rate,
            numerator=attachment_unknown,
            denominator=attachment_total,
            threshold=None,
            status="measured" if attachment_total else "not_applicable",
        ),
        "internal_conflict_rate": _metric_detail(
            conflict_rate,
            numerator=conflict_count,
            denominator=publishable_count,
            threshold=_INTERNAL_CONFLICT_THRESHOLD,
            status="measured" if publishable_count else "not_applicable",
            failure_case_ids=conflict_failure_cases,
        ),
        "false_duplicate_merge_count": _metric_detail(
            false_duplicate_count,
            numerator=false_duplicate_count,
            denominator=duplicate_count,
            threshold=0,
            status="measured",
            failure_case_ids=false_duplicate_cases,
        ),
        "p0_p1_remediation_completeness": _metric_detail(
            remediation_rate,
            numerator=remediation_complete_count,
            denominator=remediation_total,
            threshold=_P0_P1_REMEDIATION_THRESHOLD,
            status="measured" if remediation_total else "not_applicable",
            failure_case_ids=remediation_failure_cases,
        ),
    }
    return metrics, details, failures


def evaluate_quality_cases(
    manifest: Mapping[str, Any],
    actual_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    v2_by_case: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    repeated_runs_by_case: Mapping[
        str, Sequence[Sequence[Mapping[str, Any]]]
    ]
    | None = None,
) -> dict[str, Any]:
    """Evaluate actual findings against a versioned gold-set manifest."""

    failures: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    expected_total = actual_total = matched_total = 0
    expected_with_evidence = 0
    reproduced_citations = 0
    citation_failure_cases: set[str] = set()
    expected_with_location = 0
    resolved_locations = 0
    gate_covered = 0
    duplicate_findings = 0

    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(cases, list):
        return {
            "promotion_ready": False,
            "metrics": {},
            "metric_details": {},
            "case_results": [],
            "failures": [{"code": "invalid_manifest", "case_id": ""}],
        }

    schema_v2 = str(manifest.get("schema_version", "") or "") == "review-quality/2"
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            failures.append({"code": "invalid_case", "case_id": ""})
            continue
        case_id = str(raw_case.get("case_id", "") or "").strip()
        expected = [
            item
            for item in _as_list(raw_case.get("expected_findings"))
            if isinstance(item, Mapping)
        ]
        actual = [
            item
            for item in _as_list(actual_by_case.get(case_id, []))
            if isinstance(item, Mapping)
        ]
        expected_total += len(expected)
        actual_total += len(actual)

        expected_input_sha256 = str(raw_case.get("input_sha256", "") or "").strip()
        if not expected_input_sha256:
            failures.append({"code": "missing_input_sha256", "case_id": case_id})
        for actual_finding in actual:
            actual_input_sha256 = _input_sha256_from_quality(actual_finding)
            if actual_input_sha256 != expected_input_sha256:
                failures.append(
                    {
                        "code": "input_sha256_mismatch",
                        "case_id": case_id,
                        "finding_id": str(actual_finding.get("finding_id", "") or ""),
                        "expected": expected_input_sha256,
                        "actual": actual_input_sha256,
                    }
                )

        if str(raw_case.get("adjudication_status", "") or "") != "adjudicated":
            failures.append({"code": "missing_adjudication", "case_id": case_id})

        if schema_v2:
            for field in _v2_case_contract_errors(raw_case):
                failures.append(
                    {
                        "code": "invalid_v2_case",
                        "case_id": case_id,
                        "field": field,
                    }
                )
            for expected_finding in expected:
                if not _has_controlled_match_key(expected_finding):
                    failures.append(
                        {
                            "code": "invalid_controlled_match_key",
                            "case_id": case_id,
                            "match_key": _display_match_key(expected_finding),
                        }
                    )
                for field in _v2_expected_contract_errors(expected_finding):
                    failures.append(
                        {
                            "code": "invalid_v2_expected_finding",
                            "case_id": case_id,
                            "field": field,
                            "match_key": _display_match_key(expected_finding),
                        }
                    )

        used_actual: set[int] = set()
        matched_pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for expected_finding in expected:
            match_index = next(
                (
                    index
                    for index, actual_finding in enumerate(actual)
                    if index not in used_actual
                    and _finding_matches(expected_finding, actual_finding)
                ),
                None,
            )
            if match_index is None:
                failures.append(
                    {
                        "code": "missing_finding",
                        "case_id": case_id,
                        "match_key": _display_match_key(expected_finding),
                    }
                )
                continue
            used_actual.add(match_index)
            matched_pairs.append((expected_finding, actual[match_index]))

        for index, actual_finding in enumerate(actual):
            if index not in used_actual:
                failures.append(
                    {
                        "code": "unexpected_finding",
                        "case_id": case_id,
                        "issue_type": str(actual_finding.get("issue_type", "") or ""),
                    }
                )

        matched_total += len(matched_pairs)
        for expected_finding, actual_finding in matched_pairs:
            expected_status = str(expected_finding.get("status", "") or "")
            actual_status = str(actual_finding.get("status", "") or "")
            if actual_status != expected_status:
                failures.append(
                    {
                        "code": "status_mismatch",
                        "case_id": case_id,
                        "match_key": _display_match_key(expected_finding),
                        "expected": expected_status,
                        "actual": actual_status,
                    }
                )
            expected_severity = str(expected_finding.get("severity", "") or "")
            actual_severity = str(actual_finding.get("severity", "") or "")
            if actual_severity != expected_severity:
                failures.append(
                    {
                        "code": "severity_mismatch",
                        "case_id": case_id,
                        "match_key": _display_match_key(expected_finding),
                        "expected": expected_severity,
                        "actual": actual_severity,
                    }
                )
            expected_ids = _expected_evidence_ids(expected_finding)
            actual_quality = actual_finding.get("quality")
            citation = (
                actual_quality.get("citation_validation")
                if isinstance(actual_quality, Mapping)
                else None
            )
            if expected_ids:
                expected_with_evidence += 1
                actual_ids = _evidence_ids_from_quality(actual_finding)
                if (
                    isinstance(citation, Mapping)
                    and str(citation.get("status", "") or "") == "verified"
                    and expected_ids.issubset(actual_ids)
                ):
                    reproduced_citations += 1
                else:
                    citation_failure_cases.add(case_id)
            if expected_finding.get("primary_location") is not None:
                expected_with_location += 1
                if _primary_location_matches(expected_finding, actual_finding):
                    resolved_locations += 1

        for actual_finding in actual:
            if (
                str(actual_finding.get("status", "") or "") in {"fail", "unknown"}
                and not isinstance(actual_finding.get("quality"), Mapping)
            ):
                failures.append(
                    {
                        "code": "missing_quality_envelope",
                        "case_id": case_id,
                        "finding_id": str(actual_finding.get("finding_id", "") or ""),
                    }
                )
            if _has_gate_status(actual_finding):
                gate_covered += 1
            quality = actual_finding.get("quality")
            gates = quality.get("gates") if isinstance(quality, Mapping) else None
            if isinstance(gates, Mapping):
                for gate_name, gate in gates.items():
                    if isinstance(gate, Mapping) and _not_run_encoded_as_passed(gate):
                        failures.append(
                            {
                                "code": "not_run_encoded_as_passed",
                                "case_id": case_id,
                                "gate": str(gate_name),
                            }
                        )
            quality = actual_finding.get("quality")
            grouping = quality.get("grouping") if isinstance(quality, Mapping) else None
            if isinstance(grouping, Mapping) and grouping.get("duplicate_of"):
                duplicate_findings += 1

        case_results.append(
            {
                "case_id": case_id,
                "expected": len(expected),
                "actual": len(actual),
                "matched": len(matched_pairs),
            }
        )

    metrics = {
        "finding_precision": matched_total / actual_total if actual_total else 0.0,
        "finding_recall": matched_total / expected_total if expected_total else 0.0,
        "citation_reproduction_rate": (
            reproduced_citations / expected_with_evidence
            if expected_with_evidence
            else 1.0
        ),
        "primary_location_resolvable_rate": (
            resolved_locations / expected_with_location
            if expected_with_location
            else 1.0
        ),
        "gate_status_coverage": gate_covered / actual_total if actual_total else 1.0,
        "duplicate_rate": duplicate_findings / actual_total if actual_total else 0.0,
    }
    metric_details: dict[str, dict[str, Any]] = {
        "finding_precision": _metric_detail(
            metrics["finding_precision"],
            numerator=matched_total,
            denominator=actual_total,
            threshold=None,
            status="measured" if actual_total else "not_applicable",
        ),
        "finding_recall": _metric_detail(
            metrics["finding_recall"],
            numerator=matched_total,
            denominator=expected_total,
            threshold=None,
            status="measured" if expected_total else "not_applicable",
        ),
        "citation_reproduction_rate": _metric_detail(
            metrics["citation_reproduction_rate"],
            numerator=reproduced_citations,
            denominator=expected_with_evidence,
            threshold=1.0,
            status="measured" if expected_with_evidence else "not_applicable",
            failure_case_ids=citation_failure_cases,
        ),
        "primary_location_resolvable_rate": _metric_detail(
            metrics["primary_location_resolvable_rate"],
            numerator=resolved_locations,
            denominator=expected_with_location,
            threshold=None,
            status="measured" if expected_with_location else "not_applicable",
        ),
        "gate_status_coverage": _metric_detail(
            metrics["gate_status_coverage"],
            numerator=gate_covered,
            denominator=actual_total,
            threshold=None,
            status="measured" if actual_total else "not_applicable",
        ),
        "duplicate_rate": _metric_detail(
            metrics["duplicate_rate"],
            numerator=duplicate_findings,
            denominator=actual_total,
            threshold=None,
            status="measured" if actual_total else "not_applicable",
        ),
    }
    if expected_with_evidence and metrics["citation_reproduction_rate"] < 1.0:
        failures.append(
            {
                "code": "citation_reproduction_below_100",
                "rate": metrics["citation_reproduction_rate"],
                "case_ids": sorted(citation_failure_cases),
            }
        )
    if v2_by_case is not None:
        (
            v1_precision,
            v1_correct,
            v1_actual_high,
            v1_precision_failure_cases,
        ) = _p0_p1_precision_measure(manifest, actual_by_case)
        (
            v2_precision,
            v2_correct,
            v2_actual_high,
            v2_precision_failure_cases,
        ) = _p0_p1_precision_measure(manifest, v2_by_case)
        metrics["v1_p0_p1_precision"] = v1_precision
        metrics["v2_p0_p1_precision"] = v2_precision
        metric_details["v1_p0_p1_precision"] = _metric_detail(
            v1_precision,
            numerator=v1_correct,
            denominator=v1_actual_high,
            threshold=None,
            status="measured" if v1_actual_high else "not_applicable",
            failure_case_ids=v1_precision_failure_cases,
        )
        metric_details["v2_p0_p1_precision"] = _metric_detail(
            v2_precision,
            numerator=v2_correct,
            denominator=v2_actual_high,
            threshold=v1_precision,
            status="measured" if v2_actual_high else "not_applicable",
            failure_case_ids=v2_precision_failure_cases,
        )
        if v2_precision < v1_precision:
            failures.append(
                {
                    "code": "v2_p0_p1_precision_decreased",
                    "v1_precision": v1_precision,
                    "v2_precision": v2_precision,
                    "case_ids": sorted(v2_precision_failure_cases),
                }
            )

    repeated_report: dict[str, Any] | None = None
    if not schema_v2:
        # A legacy flat result remains useful for baseline metrics, but cannot
        # prove controlled identity, repeatability, or quality-on safety.
        failures.append(
            {"code": "legacy_manifest_not_promotion_eligible", "case_id": ""}
        )
    else:
        quality_source = v2_by_case if v2_by_case is not None else actual_by_case
        if v2_by_case is None:
            failures.append({"code": "missing_v2_results", "case_id": ""})
        else:
            v2_reproduced, v2_expected, v2_citation_failure_cases = (
                _citation_reproduction_measure(manifest, v2_by_case)
            )
            v2_citation_rate = (
                v2_reproduced / v2_expected if v2_expected else None
            )
            metrics["v2_citation_reproduction_rate"] = v2_citation_rate
            metric_details["v2_citation_reproduction_rate"] = _metric_detail(
                v2_citation_rate,
                numerator=v2_reproduced,
                denominator=v2_expected,
                threshold=1.0,
                status="measured" if v2_expected else "not_applicable",
                failure_case_ids=v2_citation_failure_cases,
            )
            if v2_citation_rate is not None and v2_citation_rate < 1.0:
                failures.append(
                    {
                        "code": "v2_citation_reproduction_below_100",
                        "rate": v2_citation_rate,
                        "case_ids": sorted(v2_citation_failure_cases),
                    }
                )
        for raw_case in cases:
            if not isinstance(raw_case, Mapping):
                continue
            case_id = _text(raw_case.get("case_id"))
            expected_input_sha256 = _text(raw_case.get("input_sha256"))
            expected_input_set_sha256 = _text(raw_case.get("input_set_sha256"))
            expected_execution_sha256 = _text(raw_case.get("execution_sha256"))
            if not expected_input_set_sha256:
                failures.append(
                    {"code": "missing_input_set_sha256", "case_id": case_id}
                )
                continue
            for finding in _as_list(quality_source.get(case_id, [])):
                if not isinstance(finding, Mapping):
                    continue
                if not _has_quality_v2_envelope(finding):
                    failures.append(
                        {
                            "code": "quality_schema_not_promotion_eligible",
                            "case_id": case_id,
                            "finding_id": _finding_id(finding),
                            "schema_version": _text(
                                _quality_mapping(finding).get("schema_version")
                            ),
                        }
                    )
                gates = _quality_mapping(finding).get("gates")
                if isinstance(gates, Mapping):
                    for gate_name, gate in gates.items():
                        if isinstance(gate, Mapping) and _not_run_encoded_as_passed(
                            gate
                        ):
                            failures.append(
                                {
                                    "code": "not_run_encoded_as_passed",
                                    "case_id": case_id,
                                    "result_set": "v2",
                                    "finding_id": _finding_id(finding),
                                    "gate": _text(gate_name),
                                }
                            )
                actual_input_sha256 = _input_sha256_from_quality(finding)
                if actual_input_sha256 != expected_input_sha256:
                    failures.append(
                        {
                            "code": "input_sha256_mismatch",
                            "case_id": case_id,
                            "result_set": "v2",
                            "finding_id": _finding_id(finding),
                            "expected": expected_input_sha256,
                            "actual": actual_input_sha256,
                        }
                    )
                actual_input_set_sha256 = _input_set_sha256_from_quality(finding)
                if actual_input_set_sha256 != expected_input_set_sha256:
                    failures.append(
                        {
                            "code": "input_set_sha256_mismatch",
                            "case_id": case_id,
                            "finding_id": _finding_id(finding),
                            "expected": expected_input_set_sha256,
                            "actual": actual_input_set_sha256,
                        }
                    )
                actual_execution_sha256 = _execution_sha256_from_quality(finding)
                if actual_execution_sha256 != expected_execution_sha256:
                    failures.append(
                        {
                            "code": "execution_sha256_mismatch",
                            "case_id": case_id,
                            "result_set": "v2",
                            "finding_id": _finding_id(finding),
                            "expected": expected_execution_sha256,
                            "actual": actual_execution_sha256,
                        }
                    )

        quality_metrics, quality_details, quality_failures = _quality_gate_metrics(
            manifest, quality_source
        )
        metrics.update(quality_metrics)
        metric_details.update(quality_details)
        failures.extend(quality_failures)

        adjudicated_cases = [
            raw_case
            for raw_case in cases
            if isinstance(raw_case, Mapping)
            and _text(raw_case.get("adjudication_status")) == "adjudicated"
        ]
        adjudicated_findings = sum(
            len(
                [
                    expected
                    for expected in _as_list(raw_case.get("expected_findings"))
                    if isinstance(expected, Mapping)
                ]
            )
            for raw_case in adjudicated_cases
        )
        metrics["adjudicated_case_count"] = len(adjudicated_cases)
        metrics["adjudicated_finding_count"] = adjudicated_findings
        metric_details["adjudicated_case_count"] = _metric_detail(
            len(adjudicated_cases),
            numerator=len(adjudicated_cases),
            denominator=_MINIMUM_ADJUDICATED_CASES,
            threshold=_MINIMUM_ADJUDICATED_CASES,
        )
        metric_details["adjudicated_finding_count"] = _metric_detail(
            adjudicated_findings,
            numerator=adjudicated_findings,
            denominator=_MINIMUM_ADJUDICATED_FINDINGS,
            threshold=_MINIMUM_ADJUDICATED_FINDINGS,
        )
        if (
            len(adjudicated_cases) < _MINIMUM_ADJUDICATED_CASES
            or adjudicated_findings < _MINIMUM_ADJUDICATED_FINDINGS
        ):
            failures.append(
                {
                    "code": "insufficient_adjudicated_quality_sample",
                    "case_ids": [
                        _text(raw_case.get("case_id"))
                        for raw_case in adjudicated_cases
                    ],
                    "adjudicated_case_count": len(adjudicated_cases),
                    "adjudicated_finding_count": adjudicated_findings,
                    "minimum_case_count": _MINIMUM_ADJUDICATED_CASES,
                    "minimum_finding_count": _MINIMUM_ADJUDICATED_FINDINGS,
                }
            )

        if repeated_runs_by_case is None:
            failures.append({"code": "missing_repeated_runs", "case_id": ""})
        else:
            repeated_report = evaluate_repeated_runs(manifest, repeated_runs_by_case)
            metrics.update(repeated_report["metrics"])
            metric_details.update(repeated_report["metric_details"])
            failures.extend(repeated_report["failures"])

    return {
        "promotion_ready": bool(
            schema_v2
            and v2_by_case is not None
            and repeated_runs_by_case is not None
            and not failures
        ),
        "metrics": metrics,
        "metric_details": metric_details,
        "case_results": case_results,
        "repeated_runs": repeated_report,
        "failures": failures,
    }


def compare_v1_v2(
    v1_findings: Iterable[Mapping[str, Any]],
    v2_findings: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare findings by stable ID without fuzzy text matching."""

    v1_by_id = {
        str(item.get("finding_id", "") or ""): item
        for item in v1_findings
        if isinstance(item, Mapping) and str(item.get("finding_id", "") or "")
    }
    v2_by_id = {
        str(item.get("finding_id", "") or ""): item
        for item in v2_findings
        if isinstance(item, Mapping) and str(item.get("finding_id", "") or "")
    }
    items: list[dict[str, Any]] = []
    for finding_id in sorted(set(v1_by_id) & set(v2_by_id)):
        v1 = v1_by_id[finding_id]
        v2 = v2_by_id[finding_id]
        v1_ids = _evidence_ids_from_quality(v1)
        v2_ids = _evidence_ids_from_v2(v2)
        if str(v1.get("status", "") or "") != str(v2.get("status", "") or ""):
            category = "status_conflict"
        elif v1_ids != v2_ids:
            category = "evidence_conflict"
        else:
            category = "agreement"
        items.append(
            {
                "finding_id": finding_id,
                "category": category,
                "v1_status": v1.get("status"),
                "v2_status": v2.get("status"),
                "v1_evidence_ids": sorted(v1_ids),
                "v2_evidence_ids": sorted(v2_ids),
            }
        )
    for finding_id in sorted(set(v1_by_id) - set(v2_by_id)):
        items.append({"finding_id": finding_id, "category": "legacy_only"})
    for finding_id in sorted(set(v2_by_id) - set(v1_by_id)):
        items.append({"finding_id": finding_id, "category": "shadow_only"})

    counts = Counter(item["category"] for item in items)
    return {
        "counts": {category: int(counts.get(category, 0)) for category in _CATEGORIES},
        "items": items,
    }
