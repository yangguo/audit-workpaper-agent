"""Immutable, additive quality metadata for legacy review findings."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from review.contracts import CitationValidationStatus, QualityGateStatus


_REF_KEYS = {
    "attachment",
    "cell_or_range",
    "content_hash",
    "end_offset",
    "evidence_id",
    "excerpt",
    "quote",
    "role",
    "sheet",
    "source_kind",
    "source_ref",
    "source_sha256",
    "start_offset",
}


class PrimaryLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: Literal["cell", "attachment", "unknown"]
    sheet: str = ""
    cell_or_range: str = ""
    source_ref: str = ""
    evidence_id: str | None = None


class CitationValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CitationValidationStatus = "not_available"
    verified_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    rejection_codes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verified_refs: list[dict[str, Any]] = Field(default_factory=list)


class GateOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: QualityGateStatus
    reason: str = ""
    issues: list[str] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)


class FindingProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_sha256: str = ""
    input_set_sha256: str = ""
    execution_sha256: str = ""
    engine_version: str = ""
    policy_pack: dict[str, str] | None = None


class FindingGrouping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root_cause_id: str | None = None
    duplicate_of: str | None = None
    related_finding_ids: list[str] = Field(default_factory=list)


class RemediationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["actionable", "needs_human_refinement", "not_available"] = (
        "not_available"
    )
    action: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class FindingQuality(BaseModel):
    """The versioned quality envelope attached to a V1 finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "review-quality/1"
    finding_id: str
    primary_location: PrimaryLocation | None = None
    citation_validation: CitationValidation = Field(
        default_factory=CitationValidation
    )
    gates: dict[str, GateOutcome] = Field(default_factory=dict)
    provenance: FindingProvenance = Field(default_factory=FindingProvenance)
    grouping: FindingGrouping = Field(default_factory=FindingGrouping)
    remediation: RemediationState = Field(default_factory=RemediationState)


def _string(value: Any) -> str:
    return str(value or "").strip()


def _json_key(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize_evidence_refs(
    refs: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return stable, deduplicated evidence identity records.

    The function deliberately drops unbounded fields such as cached OCR full
    text. Those fields belong in the existing evidence artifact, not in a
    finding's quality envelope or report summary.
    """

    unique: dict[str, dict[str, Any]] = {}
    for raw in refs or []:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = {}
        for key in _REF_KEYS:
            value = raw.get(key)
            if value is None or value == "":
                continue
            if key in {
                "attachment",
                "cell_or_range",
                "content_hash",
                "evidence_id",
                "excerpt",
                "quote",
                "role",
                "sheet",
                "source_kind",
                "source_ref",
                "source_sha256",
            }:
                value = _string(value)
                if not value:
                    continue
            item[key] = value
        if "source_kind" not in item:
            item["source_kind"] = (
                "attachment" if item.get("attachment") else
                "cell" if item.get("cell_or_range") else "unknown"
            )
        key = _json_key(item)
        unique.setdefault(key, item)

    kind_order = {"cell": 0, "attachment": 1, "unknown": 2}
    return sorted(
        unique.values(),
        key=lambda item: (
            kind_order.get(str(item.get("source_kind", "")), 9),
            str(item.get("source_kind", "")),
            str(item.get("evidence_id", "")),
            str(item.get("sheet", "")),
            str(item.get("cell_or_range", "")),
            str(item.get("attachment", "")),
            str(item.get("content_hash", "")),
            str(item.get("excerpt", item.get("quote", ""))),
        ),
    )


def derive_primary_location(
    finding: Mapping[str, Any], refs: Sequence[Mapping[str, Any]] | None
) -> dict[str, Any] | None:
    """Choose a deterministic human-facing location from verified evidence."""

    sheet = _string(finding.get("sheet"))
    cell = _string(finding.get("cell"))
    if cell:
        matching_id = None
        for ref in refs or []:
            if (
                _string(ref.get("sheet")) == sheet
                and _string(ref.get("cell_or_range")) == cell
            ):
                matching_id = _string(ref.get("evidence_id")) or None
                break
        return {
            "source_kind": "cell",
            "sheet": sheet,
            "cell_or_range": cell,
            "source_ref": f"workpaper:{sheet}!{cell}" if sheet else f"workpaper:{cell}",
            "evidence_id": matching_id,
        }

    for ref in refs or []:
        ref_sheet = _string(ref.get("sheet"))
        ref_cell = _string(ref.get("cell_or_range"))
        if ref_cell:
            return {
                "source_kind": "cell",
                "sheet": ref_sheet,
                "cell_or_range": ref_cell,
                "source_ref": _string(ref.get("source_ref"))
                or (f"workpaper:{ref_sheet}!{ref_cell}" if ref_sheet else f"workpaper:{ref_cell}"),
                "evidence_id": _string(ref.get("evidence_id")) or None,
            }
    for ref in refs or []:
        attachment = _string(ref.get("attachment"))
        if attachment:
            return {
                "source_kind": "attachment",
                "sheet": _string(ref.get("sheet")) or sheet,
                "cell_or_range": "",
                "source_ref": _string(ref.get("source_ref"))
                or attachment,
                "evidence_id": _string(ref.get("evidence_id")) or None,
            }
    return None


def stable_legacy_finding_id(
    *,
    input_sha256: str,
    issue_type: str,
    sheet: str,
    cell: str | None,
    status: str,
    evidence_refs: Iterable[Mapping[str, Any]] | None,
    origin: str = "legacy",
) -> str:
    material = {
        "input_sha256": _string(input_sha256),
        "issue_type": _string(issue_type),
        "sheet": _string(sheet),
        "cell": _string(cell),
        "status": _string(status),
        "origin": _string(origin) or "legacy",
        "evidence_refs": canonicalize_evidence_refs(evidence_refs),
    }
    digest = hashlib.sha256(_json_key(material).encode("utf-8")).hexdigest()
    return f"legacy:{digest[:32]}"


def build_quality_envelope(
    finding: Mapping[str, Any],
    *,
    input_sha256: str = "",
    input_set_sha256: str = "",
    execution_sha256: str = "",
    engine_version: str = "",
    policy_pack: Mapping[str, str] | None = None,
    verified_refs: Iterable[Mapping[str, Any]] | None = None,
    rejected_count: int = 0,
    rejection_codes: Iterable[str] | None = None,
    citation_status: CitationValidationStatus | None = None,
    gates: Mapping[str, Mapping[str, Any]] | None = None,
    grouping: Mapping[str, Any] | None = None,
    remediation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an additive quality envelope from already verified metadata."""

    refs = canonicalize_evidence_refs(verified_refs)
    if citation_status is None:
        if refs and rejected_count:
            citation_status = "partial"
        elif refs:
            citation_status = "verified"
        elif rejected_count:
            citation_status = "invalid"
        else:
            citation_status = "not_available"
    evidence_ids = sorted(
        {
            _string(ref.get("evidence_id"))
            for ref in refs
            if _string(ref.get("evidence_id"))
        }
    )
    finding_id = stable_legacy_finding_id(
        input_sha256=input_sha256,
        issue_type=_string(finding.get("issue_type")),
        sheet=_string(finding.get("sheet")),
        cell=finding.get("cell"),
        status=_string(finding.get("status")),
        evidence_refs=refs,
        origin=_string(finding.get("origin")) or "legacy",
    )
    payload = FindingQuality(
        finding_id=finding_id,
        primary_location=derive_primary_location(finding, refs),
        citation_validation=CitationValidation(
            status=citation_status,
            verified_count=len(refs),
            rejected_count=max(0, int(rejected_count)),
            rejection_codes=sorted(
                {_string(code) for code in (rejection_codes or []) if _string(code)}
            ),
            evidence_ids=evidence_ids,
            verified_refs=refs,
        ),
        gates={
            str(name): GateOutcome.model_validate(value)
            for name, value in (gates or {}).items()
        },
        provenance=FindingProvenance(
            input_sha256=_string(input_sha256),
            input_set_sha256=_string(input_set_sha256),
            execution_sha256=_string(execution_sha256),
            engine_version=_string(engine_version),
            policy_pack=(dict(policy_pack) if policy_pack else None),
        ),
        grouping=FindingGrouping.model_validate(grouping or {}),
        remediation=RemediationState.model_validate(remediation or {}),
    )
    return payload.model_dump(mode="json")
