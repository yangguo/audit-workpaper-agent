"""Deterministic finding grouping and structured remediation helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from review.result_quality import canonicalize_evidence_refs, stable_legacy_finding_id


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


def _refs(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = finding.get("evidence_refs") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    return canonicalize_evidence_refs(raw if isinstance(raw, list) else [])


def _finding_id(finding: Mapping[str, Any], input_sha256: str) -> str:
    value = _text(finding.get("finding_id"))
    if value:
        return value
    quality = finding.get("quality")
    if isinstance(quality, Mapping) and _text(quality.get("finding_id")):
        return _text(quality.get("finding_id"))
    return stable_legacy_finding_id(
        input_sha256=input_sha256,
        issue_type=_text(finding.get("issue_type")),
        sheet=_text(finding.get("sheet")),
        cell=finding.get("cell"),
        status=_text(finding.get("status")),
        evidence_refs=_refs(finding),
        origin=_text(finding.get("origin")) or "legacy",
    )


def _fingerprint(finding: Mapping[str, Any]) -> str:
    material = {
        "origin": _text(finding.get("origin")) or "legacy",
        "rule_hint": _text(finding.get("rule_hint")),
        "issue_type": _text(finding.get("issue_type")),
        "risk_type": _text(finding.get("risk_type")),
        "sheet": _text(finding.get("sheet")),
        "cell": _text(finding.get("cell")),
        "status": _text(finding.get("status")),
        "severity": _text(finding.get("severity")),
        "evidence_ids": sorted(
            _text(ref.get("evidence_id"))
            for ref in _refs(finding)
            if _text(ref.get("evidence_id"))
        ),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _root_key(finding: Mapping[str, Any]) -> str | None:
    rule_hint = _text(finding.get("rule_hint"))
    if not rule_hint:
        return None
    material = {
        "origin": _text(finding.get("origin")) or "legacy",
        "rule_hint": rule_hint,
        "sheet": _text(finding.get("sheet")),
        "risk_type": _text(finding.get("risk_type")),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def annotate_finding_groups(
    findings: Iterable[Mapping[str, Any]],
    *,
    input_sha256: str = "",
) -> list[dict[str, Any]]:
    """Annotate rows without deleting raw findings or merging by cell alone."""

    rows = [dict(item) for item in findings if isinstance(item, Mapping)]
    identifiers = [_finding_id(row, input_sha256) for row in rows]
    fingerprint_first: dict[str, str] = {}
    root_members: dict[str, list[str]] = {}
    root_by_index: list[str | None] = []
    duplicate_by_index: list[str | None] = []
    for row, finding_id in zip(rows, identifiers):
        fingerprint = _fingerprint(row)
        duplicate_of = fingerprint_first.setdefault(fingerprint, finding_id)
        if duplicate_of == finding_id and fingerprint in fingerprint_first:
            # The first member is canonical; a repeated generated ID still
            # gets a deterministic duplicate marker only after the first row.
            duplicate_of = None if list(fingerprint_first.values()).count(finding_id) == 1 else finding_id
        root_key = _root_key(row)
        root_id = f"root:{root_key[:32]}" if root_key else None
        if root_id:
            root_members.setdefault(root_id, []).append(finding_id)
        root_by_index.append(root_id)
        duplicate_by_index.append(duplicate_of)

    # The setdefault trick above cannot distinguish two rows with different
    # IDs when a pre-existing ID is reused, so recompute duplicate markers by
    # stable first occurrence index for clarity.
    seen_fingerprints: dict[str, str] = {}
    for index, row in enumerate(rows):
        fingerprint = _fingerprint(row)
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
        quality["finding_id"] = quality.get("finding_id") or identifiers[index]
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
    input_sha256: str = "",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = annotate_finding_groups(findings, input_sha256=input_sha256)
    for row in rows:
        quality = dict(row.get("quality") or {})
        quality["remediation"] = build_remediation(row)
        row["quality"] = quality
    return rows, grouping_stats(rows)
