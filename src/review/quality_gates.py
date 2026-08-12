"""Trusted, assertion-selected deterministic quality gates.

The catalog decides *which* gates apply to a controlled assertion.  A gate
never rebuilds evidence provenance: when an evaluator needs frozen evidence
facts but the registry is unavailable, it reports ``not_run`` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping

from review.evidence_facts import EvidenceFactRegistry
from review.excel_utils import _normalize_sheet_id
from review.finding_taxonomy import AssertionCatalog
from review.hallucination import _cross_validate_finding
from review.result_quality import GateOutcome


_GATE_STATUSES = {"passed", "flagged", "not_run", "error"}
_SAMPLE_SIZE_LABELS = ("样本量", "样本数量", "测试期间样本")


class QualityGateConfigurationError(ValueError):
    """Raised when a catalog references a gate that is not trusted locally."""


@dataclass(frozen=True)
class QualityGateContext:
    workbook: Any
    evidence_registry: EvidenceFactRegistry | None
    assertion_catalog: AssertionCatalog


QualityGateEvaluator = Callable[
    [Mapping[str, Any], QualityGateContext], GateOutcome
]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _outcome(
    status: str,
    *,
    reason: str = "",
    issues: list[str] | None = None,
) -> GateOutcome:
    return GateOutcome(status=status, reason=reason, issues=issues or [])


def _not_run(reason: str) -> GateOutcome:
    return _outcome("not_run", reason=reason)


def _sheet(context: QualityGateContext, finding: Mapping[str, Any]):
    workbook = context.workbook
    sheet = _text(finding.get("sheet"))
    if workbook is None:
        return None, "workbook_unavailable"
    if not sheet or sheet not in workbook.sheetnames:
        return None, "finding_sheet_unavailable"
    return workbook[sheet], ""


def _attachment_from_subject(finding: Mapping[str, Any]) -> str:
    subject = _text(finding.get("claim_subject"))
    marker = "|attachment:"
    if marker not in subject:
        return ""
    return subject.split(marker, 1)[1].strip().replace("\\", "/")


def _attachment_facts(
    finding: Mapping[str, Any], context: QualityGateContext
) -> tuple[list[Any], str]:
    registry = context.evidence_registry
    if registry is None:
        return [], "quality_context_unavailable"
    attachment = _attachment_from_subject(finding)
    if not attachment or attachment == "unresolved":
        return [], "attachment_subject_unresolved"
    expected_sheet = _normalize_sheet_id(_text(finding.get("sheet")))
    expected_path = attachment.casefold()
    facts = [
        fact
        for fact in registry.facts()
        if fact.fact_type == "attachment"
        and _text(fact.source_ref).replace("\\", "/").casefold() == expected_path
        and fact.source_type == "directory"
        and bool(_text(fact.source_sha256))
        and (
            not expected_sheet
            or any(
                _normalize_sheet_id(sheet) == expected_sheet
                for sheet in fact.sheet_scope
            )
        )
    ]
    return facts, ""


def _sample_size_present(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    ws, unavailable_reason = _sheet(context, finding)
    if ws is None:
        return _not_run(unavailable_reason)
    found_sample_size = False
    for row in ws.iter_rows(
        values_only=False, min_row=1, max_row=min(80, ws.max_row or 80)
    ):
        for cell in row:
            if not cell.value:
                continue
            value = str(cell.value)
            if not any(label in value for label in _SAMPLE_SIZE_LABELS):
                continue
            for row_number in range(cell.row, min(cell.row + 5, ws.max_row + 1)):
                for column_number in range(
                    cell.column, min(cell.column + 6, ws.max_column + 1)
                ):
                    nearby = ws.cell(row=row_number, column=column_number).value
                    if (
                        nearby is not None
                        and str(nearby).strip()
                        and str(nearby).strip() not in _SAMPLE_SIZE_LABELS
                    ):
                        found_sample_size = True
                        break
                if found_sample_size:
                    break
            if found_sample_size:
                break
        if found_sample_size:
            break
    if found_sample_size:
        return _outcome("passed", reason="sample_size_present_in_frozen_workbook")
    return _outcome(
        "flagged",
        reason="sample_size_missing_in_frozen_workbook",
        issues=["coverage_claim_but_no_sample_size"],
    )


def _attachment_inventory_consistent(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    facts, unavailable_reason = _attachment_facts(finding, context)
    if unavailable_reason:
        return _not_run(unavailable_reason)
    claim_value = _text(finding.get("claim_value")).casefold()
    present = bool(facts)
    if claim_value == "present":
        if present:
            return _outcome("passed", reason="frozen_attachment_inventory_contains_subject")
        return _outcome(
            "flagged",
            reason="frozen_attachment_inventory_missing_subject",
            issues=["attachment_claim_present_but_source_missing"],
        )
    if claim_value == "absent":
        if not present:
            return _outcome("passed", reason="frozen_attachment_inventory_omits_subject")
        return _outcome(
            "flagged",
            reason="frozen_attachment_inventory_contains_claimed_absent_subject",
            issues=["attachment_claim_absent_but_source_present"],
        )
    return _not_run("claim_value_not_inventory_comparable")


def _claim_has_required_source_kind(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    assertion = context.assertion_catalog.maybe_assertion(
        _text(finding.get("assertion_id"))
    )
    if assertion is None:
        return _not_run("assertion_not_in_catalog")
    if not assertion.requires_attachment_support:
        return _not_run("assertion_does_not_require_attachment_source")
    facts, unavailable_reason = _attachment_facts(finding, context)
    if unavailable_reason:
        return _not_run(unavailable_reason)
    if facts:
        return _outcome("passed", reason="required_frozen_attachment_source_present")
    return _outcome(
        "flagged",
        reason="required_frozen_attachment_source_missing",
        issues=["required_attachment_source_missing"],
    )


def _period_date_within_scope(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    # The current controlled claim vocabulary records a date verdict (for
    # example ``date_mismatch``), not a normalized period boundary.  Do not
    # invent a pass/fail until a versioned assertion supplies those inputs.
    if context.workbook is None:
        return _not_run("workbook_unavailable")
    return _not_run("period_scope_not_structured")


def _configuration_scope_supported(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    facts, unavailable_reason = _attachment_facts(finding, context)
    if unavailable_reason:
        return _not_run(unavailable_reason)
    if facts:
        return _outcome("passed", reason="configuration_attachment_in_frozen_sheet_scope")
    return _outcome(
        "flagged",
        reason="configuration_attachment_not_in_frozen_sheet_scope",
        issues=["configuration_claim_source_out_of_scope"],
    )


def _evidence_excerpt_matches_frozen_source(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    ws, unavailable_reason = _sheet(context, finding)
    if ws is None:
        return _not_run(unavailable_reason)
    issues = _cross_validate_finding(finding, context.workbook)
    if issues:
        return _outcome(
            "flagged",
            reason="evidence_safety_check_flagged",
            issues=issues,
        )
    return _outcome("passed", reason="evidence_safety_check_completed")


def _cross_finding_consistency(
    finding: Mapping[str, Any], context: QualityGateContext
) -> GateOutcome:
    quality = finding.get("quality")
    consistency = quality.get("consistency") if isinstance(quality, Mapping) else None
    if not isinstance(consistency, Mapping):
        return _not_run("deferred_to_quality_consistency_stage")
    status = _text(consistency.get("status"))
    if status == "conflicted":
        return _outcome(
            "flagged",
            reason="cross_finding_conflict",
            issues=list(consistency.get("reason_codes") or ["cross_finding_conflict"]),
        )
    if status == "consistent":
        return _outcome("passed", reason="cross_finding_consistency_confirmed")
    return _not_run("cross_finding_consistency_not_comparable")


TRUSTED_QUALITY_GATES: Mapping[str, QualityGateEvaluator] = {
    "sample_size_present": _sample_size_present,
    "attachment_inventory_consistent": _attachment_inventory_consistent,
    "claim_has_required_source_kind": _claim_has_required_source_kind,
    "period_date_within_scope": _period_date_within_scope,
    "configuration_scope_supported": _configuration_scope_supported,
    "evidence_excerpt_matches_frozen_source": _evidence_excerpt_matches_frozen_source,
    "cross_finding_consistency": _cross_finding_consistency,
}


def build_quality_gate_context(
    *,
    workbook: Any,
    evidence_registry: EvidenceFactRegistry | None,
    assertion_catalog: AssertionCatalog,
) -> QualityGateContext:
    """Build a validated context without creating or mutating evidence state."""

    missing = sorted(
        {
            gate_id
            for assertion in assertion_catalog.assertions
            for gate_id in assertion.deterministic_gate_ids
            if gate_id not in TRUSTED_QUALITY_GATES
        }
    )
    if missing:
        raise QualityGateConfigurationError(
            "catalog references untrusted quality gates: " + ", ".join(missing)
        )
    return QualityGateContext(
        workbook=workbook,
        evidence_registry=evidence_registry,
        assertion_catalog=assertion_catalog,
    )


def run_assertion_gates(
    finding: Mapping[str, Any], context: QualityGateContext
) -> dict[str, dict[str, Any]]:
    """Run only catalog-declared gates and preserve every execution outcome."""

    assertion = context.assertion_catalog.maybe_assertion(
        _text(finding.get("assertion_id"))
    )
    if assertion is None:
        return {}
    outcomes: dict[str, dict[str, Any]] = {}
    for gate_id in assertion.deterministic_gate_ids:
        evaluator = TRUSTED_QUALITY_GATES[gate_id]
        started = perf_counter()
        try:
            outcome = evaluator(finding, context)
            if outcome.status not in _GATE_STATUSES:
                raise ValueError(f"invalid quality gate status: {outcome.status}")
        except Exception as exc:
            outcome = _outcome("error", reason=f"{type(exc).__name__}: {exc}")
        duration_ms = max(0, int((perf_counter() - started) * 1000))
        outcomes[gate_id] = outcome.model_copy(
            update={"duration_ms": duration_ms}
        ).model_dump(mode="json")
    return outcomes
