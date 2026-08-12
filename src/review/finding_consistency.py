"""Conservative cross-finding consistency checks for controlled claims."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from typing import Any, Literal, Mapping, Sequence

from review.contracts import FindingConflict, FindingConsistency
from review.finding_taxonomy import AssertionCatalog


_ENUM_VALUES = {
    "absent",
    "coverage_insufficient",
    "date_mismatch",
    "design_evidence_missing",
    "effectiveness_evidence_missing",
    "evidence_insufficient",
    "execution_template_unreplaced",
    "field_mismatch",
    "interview_only",
    "method_insufficient",
    "mismatch",
    "population_basis_uncertain",
    "present",
    "reference_mismatch",
    "required_evidence_missing",
    "sampling_limited",
    "unavailable",
    "unknown",
}
_BOOL_VALUES = {"true": "true", "false": "false", "yes": "true", "no": "false"}
_WHITESPACE = re.compile(r"\s+")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_subject(value: Any) -> str | None:
    subject = _WHITESPACE.sub("", _text(value)).casefold()
    if not subject or len(subject) > 500 or "|" not in subject:
        return None
    return subject


def _normalise_claim_value(value: Any) -> str | None:
    raw = _text(value).casefold()
    if raw in _ENUM_VALUES:
        return raw
    if raw in _BOOL_VALUES:
        return _BOOL_VALUES[raw]
    try:
        # Dates are an explicit controlled normalizer, never fuzzy parsed.
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _finding_id(row: Mapping[str, Any], position: int) -> str:
    quality = row.get("quality") if isinstance(row.get("quality"), Mapping) else {}
    return _text(quality.get("finding_id")) or _text(row.get("finding_id")) or f"row:{position}"


def _conflict_id(
    *,
    input_set_sha256: str,
    conflict_type: str,
    assertion_id: str,
    claim_subject: str,
    finding_ids: Sequence[str],
    values: Sequence[str],
) -> str:
    payload = {
        "schema_version": "review-finding-conflict/1",
        "input_set_sha256": _text(input_set_sha256),
        "conflict_type": conflict_type,
        "assertion_id": assertion_id,
        "claim_subject": claim_subject,
        "finding_ids": sorted(finding_ids),
        "values": sorted(values),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"conflict:{digest[:32]}"


def _make_conflict(
    *,
    input_set_sha256: str,
    conflict_type: Literal[
        "exclusive_claim_values", "status_disagreement", "support_contradiction"
    ],
    assertion_id: str,
    claim_subject: str,
    rows: Sequence[tuple[int, Mapping[str, Any], str, str]],
) -> FindingConflict:
    # Legacy V1 IDs may collide for distinct controlled claims. Preserve every
    # row occurrence here; Task 5 replaces those IDs with assertion/claim based
    # identity, but consistency must never crash or discard a conflict first.
    ids = sorted(finding_id for _, _, finding_id, _ in rows)
    values = sorted({value for _, _, _, value in rows})
    return FindingConflict(
        conflict_id=_conflict_id(
            input_set_sha256=input_set_sha256,
            conflict_type=conflict_type,
            assertion_id=assertion_id,
            claim_subject=claim_subject,
            finding_ids=ids,
            values=values,
        ),
        conflict_type=conflict_type,
        finding_ids=ids,
        assertion_id=assertion_id,
        claim_subject=claim_subject,
        values=values,
    )


def _support_contradicted(row: Mapping[str, Any]) -> bool:
    quality = row.get("quality") if isinstance(row.get("quality"), Mapping) else {}
    support = quality.get("claim_support") if isinstance(quality.get("claim_support"), Mapping) else {}
    reasons = support.get("reason_codes") if isinstance(support.get("reason_codes"), list) else []
    return any(
        _text(code) in {"fact_contradicted", "support_contradiction"}
        for code in reasons
    )


def _quality_payload(row: dict[str, Any]) -> dict[str, Any]:
    quality = row.get("quality")
    if not isinstance(quality, Mapping):
        quality = {}
    copied = copy.deepcopy(dict(quality))
    copied.setdefault("gates", {})
    copied.setdefault(
        "disposition",
        {
            "original_status": _text(row.get("status")),
            "effective_status": _text(row.get("status")),
            "original_severity": _text(row.get("severity")),
            "reason_codes": [],
        },
    )
    return copied


def annotate_finding_consistency(
    findings: Sequence[Mapping[str, Any]],
    *,
    input_set_sha256: str,
    catalog: AssertionCatalog,
    quality_mode: Literal["shadow", "on"],
) -> tuple[list[dict[str, Any]], list[FindingConflict]]:
    """Annotate only exact, catalog-controlled contradictory claim groups.

    A missing controlled field is intentionally ``not_comparable``. No natural
    language, location similarity, or LLM adjudication is used to manufacture
    a conflict.
    """

    rows = [copy.deepcopy(dict(finding)) for finding in findings]
    comparable: dict[tuple[str, str, str], list[tuple[int, Mapping[str, Any], str, str]]] = {}
    display_subjects: dict[tuple[str, str, str], str] = {}
    for index, row in enumerate(rows):
        assertion_id = _text(row.get("assertion_id"))
        assertion = catalog.maybe_assertion(assertion_id)
        subject = _normalise_subject(row.get("claim_subject"))
        value = _normalise_claim_value(row.get("claim_value"))
        claim_type = _text(row.get("claim_type"))
        if (
            assertion is None
            or not assertion.exclusive_claim
            or not subject
            or not value
            or claim_type != assertion.claim_type
        ):
            continue
        group_key = (_text(input_set_sha256), assertion_id, claim_type + "|" + subject)
        comparable.setdefault(group_key, []).append(
            (index, row, _finding_id(row, index), value)
        )
        display_subjects.setdefault(group_key, _text(row.get("claim_subject")))

    conflicts: list[FindingConflict] = []
    conflicts_by_index: dict[int, list[FindingConflict]] = {}
    comparable_indexes: set[int] = set()
    related_by_index: dict[int, list[str]] = {}
    for group_key, members in comparable.items():
        _, assertion_id, type_subject = group_key
        if len(members) < 2:
            continue
        comparable_indexes.update(index for index, _, _, _ in members)
        claim_subject = display_subjects.get(group_key) or type_subject.split("|", 1)[1]
        values = {value for _, _, _, value in members}
        statuses = {_text(row.get("status")) for _, row, _, _ in members}
        group_conflicts: list[FindingConflict] = []
        if len(values) > 1:
            group_conflicts.append(
                _make_conflict(
                    input_set_sha256=input_set_sha256,
                    conflict_type="exclusive_claim_values",
                    assertion_id=assertion_id,
                    claim_subject=claim_subject,
                    rows=members,
                )
            )
        if len(statuses) > 1:
            group_conflicts.append(
                _make_conflict(
                    input_set_sha256=input_set_sha256,
                    conflict_type="status_disagreement",
                    assertion_id=assertion_id,
                    claim_subject=claim_subject,
                    rows=members,
                )
            )
        if any(_support_contradicted(row) for _, row, _, _ in members):
            group_conflicts.append(
                _make_conflict(
                    input_set_sha256=input_set_sha256,
                    conflict_type="support_contradiction",
                    assertion_id=assertion_id,
                    claim_subject=claim_subject,
                    rows=members,
                )
            )
        conflicts.extend(group_conflicts)
        group_ids = [(member_index, finding_id) for member_index, _, finding_id, _ in members]
        for index, _, finding_id, _ in members:
            related_by_index[index] = sorted(
                other_id
                for other_index, other_id in group_ids
                if other_index != index
            )
            conflicts_by_index.setdefault(index, []).extend(group_conflicts)

    for index, row in enumerate(rows):
        quality = _quality_payload(row)
        row_conflicts = conflicts_by_index.get(index, [])
        if row_conflicts:
            consistency = FindingConsistency(
                status="conflicted",
                conflict_ids=sorted({item.conflict_id for item in row_conflicts}),
                related_finding_ids=related_by_index.get(index, []),
                reason_codes=sorted({item.conflict_type for item in row_conflicts}),
            )
            gate = {
                "status": "flagged",
                "reason": "controlled claims conflict within this execution",
                "issues": consistency.conflict_ids,
            }
            if quality_mode == "on" and _text(row.get("status")) == "fail":
                row["status"] = "unknown"
                row["severity"] = "P2"
                disposition = quality["disposition"]
                reasons = list(disposition.get("reason_codes") or [])
                if "cross_finding_conflict" not in reasons:
                    reasons.append("cross_finding_conflict")
                disposition["effective_status"] = "unknown"
                disposition["reason_codes"] = reasons
        elif index in comparable_indexes:
            consistency = FindingConsistency(
                status="consistent",
                related_finding_ids=related_by_index.get(index, []),
                reason_codes=["controlled_claim_values_agree"],
            )
            gate = {
                "status": "passed",
                "reason": "controlled claims agree within comparable group",
                "issues": [],
            }
        else:
            consistency = FindingConsistency(
                status="not_comparable",
                reason_codes=["controlled_comparison_key_unavailable"],
            )
            gate = {
                "status": "not_run",
                "reason": "controlled comparison key unavailable or has no peer",
                "issues": [],
            }
        quality["consistency"] = consistency.model_dump(mode="json")
        gates = quality["gates"] if isinstance(quality.get("gates"), dict) else {}
        gates["cross_finding_consistency"] = gate
        quality["gates"] = gates
        row["quality"] = quality

    return rows, sorted(conflicts, key=lambda item: item.conflict_id)
