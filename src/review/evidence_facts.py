"""Immutable evidence facts and claim-support decisions.

Citation verification answers whether a quoted locator is genuine.  This
module answers the separate question of whether those verified sources can
support the controlled type of claim made by a finding.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from review.contracts import ClaimSupport, EvidenceFact
from review.evidence_provenance import EvidenceProvenanceIndex
from review.excel_utils import _normalize_sheet_id
from review.finding_taxonomy import AssertionSpec


_CONTENT_READY_STATUSES = {"ok", "ocr", "complete", "extracted"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Iterable[str]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


class EvidenceFactRegistry:
    """Read-only lookup of minimal source identities from one frozen index."""

    def __init__(self, facts: Iterable[EvidenceFact | Mapping[str, Any]]) -> None:
        self._facts: dict[str, EvidenceFact] = {}
        for raw in facts:
            fact = raw if isinstance(raw, EvidenceFact) else EvidenceFact.model_validate(raw)
            self._facts.setdefault(fact.fact_id, fact)

    @classmethod
    def from_provenance(cls, index: EvidenceProvenanceIndex) -> "EvidenceFactRegistry":
        return cls(index.snapshot_records())

    def get(self, fact_id: str) -> EvidenceFact | None:
        return self._facts.get(_text(fact_id))

    def facts(self) -> list[EvidenceFact]:
        return [self._facts[key] for key in sorted(self._facts)]


def _fact_in_sheet_scope(fact: EvidenceFact, finding: Mapping[str, Any]) -> bool:
    sheet = _text(finding.get("sheet"))
    if not sheet or not fact.sheet_scope:
        return bool(sheet) is False
    expected = _normalize_sheet_id(sheet)
    return any(_normalize_sheet_id(candidate) == expected for candidate in fact.sheet_scope)


def _attachment_fact_from_ref(
    ref: Mapping[str, Any], registry: EvidenceFactRegistry
) -> EvidenceFact | None:
    if _text(ref.get("source_kind")) != "attachment":
        return None
    fact = registry.get(_text(ref.get("evidence_id")))
    if fact is None or fact.fact_type != "attachment":
        return None
    if _text(ref.get("source_ref")) and _text(ref.get("source_ref")) != fact.source_ref:
        return None
    if _text(ref.get("content_hash")) and _text(ref.get("content_hash")) != fact.content_hash:
        return None
    if _text(ref.get("source_sha256")) and _text(ref.get("source_sha256")) != fact.source_sha256:
        return None
    return fact


def _cell_fact_from_ref(
    ref: Mapping[str, Any], registry: EvidenceFactRegistry
) -> EvidenceFact | None:
    if _text(ref.get("source_kind")) != "cell":
        return None
    fact = registry.get(_text(ref.get("evidence_id")))
    return fact if fact is not None and fact.fact_type == "cell" else None


def _support(
    *,
    status: str,
    assertion: AssertionSpec,
    supporting_ids: Iterable[str] = (),
    missing: Iterable[str] = (),
    reasons: Iterable[str] = (),
) -> ClaimSupport:
    return ClaimSupport(
        status=status,
        assertion_id=assertion.assertion_id,
        claim_type=assertion.claim_type,
        supporting_evidence_ids=_unique(supporting_ids),
        missing_requirements=_unique(missing),
        reason_codes=_unique(reasons),
    )


def _attachment_support(
    *,
    finding: Mapping[str, Any],
    assertion: AssertionSpec,
    refs: Sequence[Mapping[str, Any]],
    registry: EvidenceFactRegistry,
    content_required: bool,
) -> ClaimSupport:
    attachment_refs = [
        (ref, _attachment_fact_from_ref(ref, registry))
        for ref in refs
        if _text(ref.get("source_kind")) == "attachment"
    ]
    facts = [fact for _, fact in attachment_refs if fact is not None]
    if not facts:
        status = "partial" if refs else "unsupported"
        return _support(
            status=status,
            assertion=assertion,
            missing=["verified_attachment_evidence"],
            reasons=["cell_only_citation" if refs else "no_verified_evidence"],
        )

    in_scope = [fact for fact in facts if _fact_in_sheet_scope(fact, finding)]
    if not in_scope:
        return _support(
            status="partial",
            assertion=assertion,
            missing=["attachment_in_claim_sheet_scope"],
            reasons=["attachment_out_of_scope"],
        )
    frozen = [
        fact
        for fact in in_scope
        if fact.source_type == "directory" and bool(fact.source_sha256)
    ]
    if not frozen:
        return _support(
            status="partial",
            assertion=assertion,
            missing=["frozen_attachment_source"],
            reasons=["preview_or_unfrozen_attachment"],
        )
    if not content_required:
        return _support(
            status="supported",
            assertion=assertion,
            supporting_ids=[fact.fact_id for fact in frozen],
            reasons=["frozen_attachment_present"],
        )

    content_ready = [
        fact
        for ref, fact in attachment_refs
        if fact in frozen
        and _text(fact.extraction_status).lower() in _CONTENT_READY_STATUSES
        and bool(_text(ref.get("excerpt") or ref.get("quote")))
        and ref.get("start_offset") is not None
        and ref.get("end_offset") is not None
    ]
    if not content_ready:
        return _support(
            status="partial",
            assertion=assertion,
            missing=["attachment_content_quote"],
            reasons=["attachment_content_unavailable_or_unquoted"],
        )
    return _support(
        status="supported",
        assertion=assertion,
        supporting_ids=[fact.fact_id for fact in content_ready],
        reasons=["frozen_attachment_content_verified"],
    )


def evaluate_claim_support(
    *,
    finding: Mapping[str, Any],
    assertion: AssertionSpec,
    verified_refs: Sequence[Mapping[str, Any]],
    registry: EvidenceFactRegistry,
) -> ClaimSupport:
    """Evaluate a controlled claim using only already accepted references."""

    if _text(finding.get("status")) == "pass":
        return _support(status="not_required", assertion=assertion)

    refs = [ref for ref in verified_refs if isinstance(ref, Mapping)]
    try:
        if assertion.claim_type == "attachment_presence":
            return _attachment_support(
                finding=finding,
                assertion=assertion,
                refs=refs,
                registry=registry,
                content_required=False,
            )
        if assertion.requires_attachment_support or assertion.claim_type in {
            "attachment_content",
            "period_date",
            "configuration_value",
        }:
            return _attachment_support(
                finding=finding,
                assertion=assertion,
                refs=refs,
                registry=registry,
                content_required=True,
            )

        cells = [
            fact
            for ref in refs
            if (fact := _cell_fact_from_ref(ref, registry)) is not None
            and _fact_in_sheet_scope(fact, finding)
        ]
        attachments = [
            fact
            for ref in refs
            if (fact := _attachment_fact_from_ref(ref, registry)) is not None
            and _fact_in_sheet_scope(fact, finding)
        ]
        if cells:
            return _support(
                status="supported",
                assertion=assertion,
                supporting_ids=[fact.fact_id for fact in cells],
                reasons=["verified_cell_evidence"],
            )
        if attachments:
            return _support(
                status="supported",
                assertion=assertion,
                supporting_ids=[fact.fact_id for fact in attachments],
                reasons=["verified_attachment_evidence"],
            )
        return _support(
            status="unsupported",
            assertion=assertion,
            missing=["verified_claim_evidence"],
            reasons=["no_verified_evidence"],
        )
    except Exception:
        return _support(
            status="error",
            assertion=assertion,
            missing=["claim_support_evaluation"],
            reasons=["claim_support_error"],
        )
