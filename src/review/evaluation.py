"""Deterministic evaluation helpers for review-quality gold sets.

The evaluator intentionally consumes already-produced finding payloads. It
does not invoke an LLM or open a workbook, which keeps promotion decisions
reproducible and makes it safe to run in CI against redacted manifests.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


_CATEGORIES = (
    "agreement",
    "legacy_only",
    "shadow_only",
    "status_conflict",
    "evidence_conflict",
    "not_comparable",
)


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


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
        if str(actual.get(key, "") or "") != str(expected_value or ""):
            return False
    return bool(keys)


def _has_controlled_match_key(expected: Mapping[str, Any]) -> bool:
    match_key = expected.get("match_key") or {}
    return isinstance(match_key, Mapping) and bool(
        str(match_key.get("assertion_id", "") or "").strip()
        and str(match_key.get("claim_subject", "") or "").strip()
    )


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


def _p0_p1_precision(
    manifest: Mapping[str, Any],
    results_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
) -> float:
    """Calculate exact status/severity precision for high-risk findings."""
    expected_high = 0
    actual_high = 0
    correct = 0
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(cases, list):
        return 0.0
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            continue
        case_id = str(raw_case.get("case_id", "") or "").strip()
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
        actual_high += sum(
            1 for item in actual if str(item.get("severity", "") or "") in {"P0", "P1"}
        )
        used: set[int] = set()
        for expected_finding in expected:
            if str(expected_finding.get("severity", "") or "") not in {"P0", "P1"}:
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
                continue
            used.add(index)
            actual_finding = actual[index]
            if (
                str(actual_finding.get("severity", "") or "")
                == str(expected_finding.get("severity", "") or "")
                and str(actual_finding.get("status", "") or "")
                == str(expected_finding.get("status", "") or "")
            ):
                correct += 1
    if actual_high == 0:
        return 1.0 if expected_high == 0 else 0.0
    return correct / actual_high


def evaluate_quality_cases(
    manifest: Mapping[str, Any],
    actual_by_case: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    v2_by_case: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate actual findings against a versioned gold-set manifest."""

    failures: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    expected_total = actual_total = matched_total = 0
    expected_with_evidence = 0
    reproduced_citations = 0
    expected_with_location = 0
    resolved_locations = 0
    gate_covered = 0
    duplicate_findings = 0

    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(cases, list):
        return {
            "promotion_ready": False,
            "metrics": {},
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
            for expected_finding in expected:
                if not _has_controlled_match_key(expected_finding):
                    failures.append(
                        {
                            "code": "invalid_controlled_match_key",
                            "case_id": case_id,
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
            expected_ids = {
                str(item).strip()
                for item in _as_list(expected_finding.get("evidence_ids"))
                if str(item).strip()
            }
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
    if expected_with_evidence and metrics["citation_reproduction_rate"] < 1.0:
        failures.append(
            {
                "code": "citation_reproduction_below_100",
                "rate": metrics["citation_reproduction_rate"],
            }
        )
    if v2_by_case is not None:
        v1_precision = _p0_p1_precision(manifest, actual_by_case)
        v2_precision = _p0_p1_precision(manifest, v2_by_case)
        metrics["v1_p0_p1_precision"] = v1_precision
        metrics["v2_p0_p1_precision"] = v2_precision
        if v2_precision < v1_precision:
            failures.append(
                {
                    "code": "v2_p0_p1_precision_decreased",
                    "v1_precision": v1_precision,
                    "v2_precision": v2_precision,
                }
            )
    return {
        "promotion_ready": not failures,
        "metrics": metrics,
        "case_results": case_results,
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
