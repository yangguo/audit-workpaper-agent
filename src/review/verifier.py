"""Exact, whitelist-based verification for Stage-C judgement responses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from review.policy import JudgementDecision

if TYPE_CHECKING:
    from review.judgement import JudgementRequest, JudgementResponse


VerificationStatus = Literal[
    "supported", "contradicted", "insufficient", "invalid"
]


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    decision: JudgementDecision
    conclusion: str
    evidence_refs_v2: list[dict[str, object]] = Field(default_factory=list)
    verification_status: VerificationStatus
    unknown_reason: str = ""
    errors: list[str] = Field(default_factory=list)


def _unique_errors(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(error for error in errors if error))


def verify_judgement_response(
    request: "JudgementRequest",
    response: "JudgementResponse",
) -> VerificationResult:
    """Verify a response against the exact evidence whitelist in its request."""
    errors: list[str] = []
    if response.decision not in request.allowed_decisions:
        errors.append("decision_not_allowed")
    if response.decision == "insufficient":
        if len(response.unknown_reason.strip()) < 10:
            errors.append("unknown_reason_required")
    elif not response.evidence_refs:
        errors.append("evidence_refs_required")

    evidence_by_id = {item.evidence_id: item for item in request.evidence}
    verified_refs: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for ref in response.evidence_refs:
        if ref.evidence_id in seen_ids:
            errors.append("duplicate_evidence_id")
            continue
        seen_ids.add(ref.evidence_id)
        source = evidence_by_id.get(ref.evidence_id)
        if source is None:
            errors.append("evidence_id_not_allowed")
            continue
        if ref.start_offset >= ref.end_offset or ref.end_offset > len(source.quote):
            errors.append("offset_out_of_range")
            continue
        actual_quote = source.quote[ref.start_offset : ref.end_offset]
        if actual_quote != ref.quote:
            errors.append("quote_mismatch")
            continue
        if ref.content_hash != source.content_hash:
            errors.append("content_hash_mismatch")
            continue
        verified_refs.append(
            {
                "evidence_id": ref.evidence_id,
                "source_kind": source.source_kind,
                "source_ref": source.source_ref,
                "sheet": source.sheet,
                "cell_or_range": source.cell_or_range,
                "quote": ref.quote,
                "start_offset": ref.start_offset,
                "end_offset": ref.end_offset,
                "content_hash": ref.content_hash,
                "role": ref.role,
            }
        )

    unique_errors = _unique_errors(errors)
    if unique_errors:
        return VerificationResult(
            request_id=request.request_id,
            decision=response.decision,
            conclusion=response.conclusion,
            evidence_refs_v2=[],
            verification_status="invalid",
            unknown_reason=response.unknown_reason,
            errors=unique_errors,
        )
    return VerificationResult(
        request_id=request.request_id,
        decision=response.decision,
        conclusion=response.conclusion,
        evidence_refs_v2=verified_refs,
        verification_status=response.decision,
        unknown_reason=response.unknown_reason,
        errors=[],
    )
