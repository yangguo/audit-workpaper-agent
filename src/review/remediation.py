"""Deterministic finding grouping and structured remediation helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from review.finding_taxonomy import default_assertion_catalog
from review.result_quality import (
    canonicalize_evidence_refs,
    stable_finding_id,
    stable_legacy_finding_id,
)


_GENERIC_SUGGESTIONS = {
    "建议补充完整证据",
    "补充完整证据",
    "建议补充证据",
    "请补充相关证据",
}

_REQUIRED_BY_RISK = {
    "覆盖性": ["完整范围清单、抽样依据和执行记录"],
    "一致性": ["来源系统导出、底稿勾稽表和差异解释"],
    "证据不足": ["与该控制点直接对应的原始证据"],
    "方法性": ["审计程序、执行记录和复核痕迹"],
    "跨字段一致性": ["相关字段的来源记录和勾稽说明"],
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_controlled_component(value: Any) -> str:
    """Normalize controlled claim identifiers, never free-form display text."""

    return "".join(_text(value).split()).casefold()


def _quality_mapping(finding: Mapping[str, Any]) -> Mapping[str, Any]:
    quality = finding.get("quality")
    return quality if isinstance(quality, Mapping) else {}


def _verified_refs(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use only provenance-accepted evidence; raw V1 refs are not identity."""

    citation = _quality_mapping(finding).get("citation_validation")
    refs = citation.get("verified_refs") if isinstance(citation, Mapping) else []
    return canonicalize_evidence_refs(refs if isinstance(refs, list) else [])


def _verified_evidence_ids(finding: Mapping[str, Any]) -> list[str]:
    citation = _quality_mapping(finding).get("citation_validation")
    if not isinstance(citation, Mapping):
        return []
    ids = {
        _text(value)
        for value in citation.get("evidence_ids", [])
        if _text(value)
    }
    ids.update(
        _text(ref.get("evidence_id"))
        for ref in _verified_refs(finding)
        if _text(ref.get("evidence_id"))
    )
    return sorted(ids)


def _input_set_sha256(finding: Mapping[str, Any], fallback: str = "") -> str:
    provenance = _quality_mapping(finding).get("provenance")
    if isinstance(provenance, Mapping) and _text(provenance.get("input_set_sha256")):
        return _text(provenance.get("input_set_sha256"))
    return _text(fallback)


def _controlled_claim_ready(finding: Mapping[str, Any], input_set_sha256: str) -> bool:
    return bool(
        _text(input_set_sha256)
        and _text(finding.get("assertion_id"))
        and _text(finding.get("claim_subject"))
        and _text(finding.get("claim_value"))
        and _verified_evidence_ids(finding)
    )


def _finding_id(
    finding: Mapping[str, Any], *, input_set_sha256: str, input_sha256: str
) -> str:
    active_set = _input_set_sha256(finding, input_set_sha256)
    if _controlled_claim_ready(finding, active_set):
        return stable_finding_id(
            input_set_sha256=active_set,
            assertion_id=_text(finding.get("assertion_id")),
            claim_subject=_text(finding.get("claim_subject")),
            claim_value=_text(finding.get("claim_value")),
            status=_text(finding.get("status")),
            severity=_text(finding.get("severity")),
            verified_evidence_ids=_verified_evidence_ids(finding),
            origin=_text(finding.get("origin")) or "legacy",
        )
    value = _text(finding.get("finding_id")) or _text(
        _quality_mapping(finding).get("finding_id")
    )
    if value:
        return value
    return stable_legacy_finding_id(
        input_sha256=input_sha256,
        issue_type=_text(finding.get("issue_type")),
        sheet=_text(finding.get("sheet")),
        cell=finding.get("cell"),
        status=_text(finding.get("status")),
        evidence_refs=_verified_refs(finding),
        origin=_text(finding.get("origin")) or "legacy",
    )


def exact_duplicate_fingerprint(
    finding: Mapping[str, Any], *, input_set_sha256: str = ""
) -> str | None:
    """Return a duplicate key only when controlled identity is complete."""

    input_set = _input_set_sha256(finding, input_set_sha256)
    if not _controlled_claim_ready(finding, input_set):
        return None
    material = {
        "schema_version": "review-exact-duplicate/2",
        "input_set_sha256": input_set,
        "assertion_id": _normalise_controlled_component(finding.get("assertion_id")),
        "claim_subject": _normalise_controlled_component(finding.get("claim_subject")),
        "claim_value": _normalise_controlled_component(finding.get("claim_value")),
        "status": _text(finding.get("status")),
        "severity": _text(finding.get("severity")),
        "origin": _text(finding.get("origin")) or "legacy",
        "sheet": _text(finding.get("sheet")),
        "verified_evidence_ids": _verified_evidence_ids(finding),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def root_cause_key(
    finding: Mapping[str, Any], *, input_set_sha256: str = ""
) -> str | None:
    """Group only catalog-linked assertion families within one input scope."""

    assertion = default_assertion_catalog().maybe_assertion(
        _text(finding.get("assertion_id"))
    )
    input_set = _input_set_sha256(finding, input_set_sha256)
    subject = _normalise_controlled_component(finding.get("claim_subject"))
    if (
        assertion is None
        or not assertion.root_family
        or not input_set
        or not subject
        or not _verified_evidence_ids(finding)
    ):
        return None
    material = {
        "schema_version": "review-root-cause/2",
        "input_set_sha256": input_set,
        "root_family": assertion.root_family,
        "claim_subject": subject,
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def annotate_finding_groups(
    findings: Iterable[Mapping[str, Any]],
    *,
    input_set_sha256: str = "",
    input_sha256: str = "",
) -> list[dict[str, Any]]:
    """Annotate rows without deleting raw findings or merging by cell alone."""

    rows = [dict(item) for item in findings if isinstance(item, Mapping)]
    identifiers = [
        _finding_id(
            row,
            input_set_sha256=input_set_sha256,
            input_sha256=input_sha256,
        )
        for row in rows
    ]
    root_members: dict[str, list[str]] = {}
    root_by_index: list[str | None] = []
    duplicate_by_index: list[str | None] = []
    for row, finding_id in zip(rows, identifiers):
        root_key = root_cause_key(row, input_set_sha256=input_set_sha256)
        root_id = f"root:{root_key[:32]}" if root_key else None
        if root_id:
            root_members.setdefault(root_id, []).append(finding_id)
        root_by_index.append(root_id)
        duplicate_by_index.append(None)

    # Mark duplicates by stable first occurrence, rather than by a mutable
    # display field or an existing V1 identifier.
    seen_fingerprints: dict[str, str] = {}
    for index, row in enumerate(rows):
        fingerprint = exact_duplicate_fingerprint(
            row, input_set_sha256=input_set_sha256
        )
        if fingerprint is None:
            duplicate_by_index[index] = None
            continue
        duplicate_by_index[index] = seen_fingerprints.get(fingerprint)
        seen_fingerprints.setdefault(fingerprint, identifiers[index])

    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        quality = dict(row.get("quality") or {})
        root_id = root_by_index[index]
        members = root_members.get(root_id or "", [])
        grouping = dict(quality.get("grouping") or {})
        grouping.update(
            {
                "root_cause_id": root_id,
                "duplicate_of": duplicate_by_index[index],
                "related_finding_ids": sorted(
                    member for member in members if member != identifiers[index]
                ),
            }
        )
        quality["finding_id"] = identifiers[index]
        quality["grouping"] = grouping
        row["finding_id"] = row.get("finding_id") or identifiers[index]
        row["quality"] = quality
        out.append(row)
    return out


def grouping_stats(findings: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    rows = [item for item in findings if isinstance(item, Mapping)]
    duplicate_count = 0
    related_count = 0
    root_ids: set[str] = set()
    for row in rows:
        quality = row.get("quality") or {}
        grouping = quality.get("grouping") if isinstance(quality, Mapping) else None
        if not isinstance(grouping, Mapping):
            continue
        if grouping.get("duplicate_of"):
            duplicate_count += 1
        if grouping.get("related_finding_ids"):
            related_count += 1
        if grouping.get("root_cause_id"):
            root_ids.add(_text(grouping.get("root_cause_id")))
    return {
        "raw_findings": len(rows),
        "canonical_findings": len(rows) - duplicate_count,
        "duplicate_findings": duplicate_count,
        "related_findings": related_count,
        "root_cause_count": len(root_ids),
    }


def _detail(finding: Mapping[str, Any]) -> dict[str, Any]:
    value = finding.get("fix_suggestion_detail") or finding.get("fix_suggestion") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    return dict(value) if isinstance(value, Mapping) else {}


def build_remediation(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic remediation fields without inventing ownership."""

    suggestion = _text(finding.get("suggestion"))
    detail = _detail(finding)
    required_value = detail.get("required_evidence_type")
    required = [_text(required_value)] if _text(required_value) else list(
        _REQUIRED_BY_RISK.get(_text(finding.get("risk_type")), [])
    )
    required = [item for item in required if item]
    acceptance_value = detail.get("acceptance_criteria") or detail.get("acceptance")
    if isinstance(acceptance_value, list):
        acceptance = [_text(item) for item in acceptance_value if _text(item)]
    elif _text(acceptance_value):
        acceptance = [_text(acceptance_value)]
    else:
        acceptance = []
    generic = suggestion in _GENERIC_SUGGESTIONS or len(suggestion) < 8
    missing: list[str] = []
    action = "" if generic else suggestion
    if not action:
        missing.append("action")
    if not required:
        missing.append("required_evidence")
    if not acceptance:
        missing.append("acceptance_criteria")
    return {
        "status": "actionable" if not missing else "needs_human_refinement",
        "action": action,
        "required_evidence": required,
        "acceptance_criteria": acceptance,
        "missing_fields": missing,
    }


def enrich_finding_quality(
    findings: Iterable[Mapping[str, Any]],
    *,
    input_set_sha256: str = "",
    input_sha256: str = "",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = annotate_finding_groups(
        findings,
        input_set_sha256=input_set_sha256,
        input_sha256=input_sha256,
    )
    for row in rows:
        quality = dict(row.get("quality") or {})
        quality["remediation"] = build_remediation(row)
        row["quality"] = quality
    return rows, grouping_stats(rows)
