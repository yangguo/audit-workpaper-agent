"""Fail-closed, privacy-safe comparison of legacy and shadow findings."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping


_CATEGORIES = (
    "agreement",
    "legacy_only",
    "shadow_only",
    "status_conflict",
    "evidence_conflict",
    "not_comparable",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _evidence_ids(finding: Mapping[str, Any], *, shadow: bool) -> tuple[str, ...]:
    values: set[str] = set()
    if shadow:
        refs = finding.get("evidence_refs_v2")
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, Mapping) and _text(ref.get("evidence_id")):
                    values.add(_text(ref.get("evidence_id")))
    else:
        quality = finding.get("quality")
        citation = quality.get("citation_validation") if isinstance(quality, Mapping) else None
        if isinstance(citation, Mapping):
            raw_ids = citation.get("evidence_ids")
            if isinstance(raw_ids, list):
                values.update(_text(item) for item in raw_ids if _text(item))
            if not values and isinstance(citation.get("verified_refs"), list):
                values.update(
                    _text(ref.get("evidence_id"))
                    for ref in citation["verified_refs"]
                    if isinstance(ref, Mapping) and _text(ref.get("evidence_id"))
                )
    return tuple(sorted(values))


def _identity(finding: Mapping[str, Any], *, shadow: bool) -> tuple[str, ...] | None:
    """Return an exact comparison identity; never use fuzzy text matching."""

    explicit = _text(finding.get("comparison_key"))
    if explicit:
        return ("explicit", explicit)

    rule = _text(finding.get("rule_id" if shadow else "rule_hint"))
    version = _text(finding.get("rule_version")) if shadow else ""
    issue_type = _text(finding.get("issue_type"))
    risk_type = _text(finding.get("risk_type"))
    sheet = _text(finding.get("sheet"))
    cell = _text(finding.get("cell"))
    if not cell:
        quality = finding.get("quality")
        location = quality.get("primary_location") if isinstance(quality, Mapping) else None
        if isinstance(location, Mapping):
            cell = _text(location.get("cell_or_range"))

    # A rule hint is preferred when available. For legacy findings created by
    # rule branches without a hint, the exact structured issue/risk/scope tuple
    # is still deterministic; free-text similarity is never used.
    discriminator = ("rule", rule, version) if rule else ("issue", issue_type, risk_type)
    if not discriminator[1] or (not sheet and not cell):
        return None
    return (*discriminator, sheet, cell)


def _base_item(
    *,
    category: str,
    legacy: Mapping[str, Any] | None,
    shadow: Mapping[str, Any] | None,
    reason_code: str = "",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "category": category,
        "legacy_finding_id": _text(legacy.get("finding_id")) if legacy else None,
        "shadow_finding_id": _text(shadow.get("finding_id")) if shadow else None,
        "v1_status": legacy.get("status") if legacy else None,
        "v2_status": shadow.get("status") if shadow else None,
        "v1_evidence_ids": list(_evidence_ids(legacy, shadow=False)) if legacy else [],
        "v2_evidence_ids": list(_evidence_ids(shadow, shadow=True)) if shadow else [],
    }
    if reason_code:
        item["reason_code"] = reason_code
    return item


def compare_finding_sets(
    legacy_findings: Iterable[Mapping[str, Any]],
    shadow_findings: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare V1/V2 using exact structured identity and evidence IDs.

    Ambiguous identities and records without a deterministic identity are
    reported as ``not_comparable`` rather than guessed into a match.
    """

    legacy_groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    shadow_groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    items: list[dict[str, Any]] = []

    for finding in legacy_findings:
        if not isinstance(finding, Mapping):
            continue
        identity = _identity(finding, shadow=False)
        if identity is None:
            items.append(_base_item(category="not_comparable", legacy=finding, shadow=None, reason_code="missing_identity"))
        else:
            legacy_groups[identity].append(finding)
    for finding in shadow_findings:
        if not isinstance(finding, Mapping):
            continue
        identity = _identity(finding, shadow=True)
        if identity is None:
            items.append(_base_item(category="not_comparable", legacy=None, shadow=finding, reason_code="missing_identity"))
        else:
            shadow_groups[identity].append(finding)

    for identity in sorted(set(legacy_groups) | set(shadow_groups)):
        legacy = legacy_groups.get(identity, [])
        shadow = shadow_groups.get(identity, [])
        if len(legacy) > 1 or len(shadow) > 1:
            items.extend(
                _base_item(
                    category="not_comparable",
                    legacy=finding,
                    shadow=None,
                    reason_code="ambiguous_identity",
                )
                for finding in legacy
            )
            items.extend(
                _base_item(
                    category="not_comparable",
                    legacy=None,
                    shadow=finding,
                    reason_code="ambiguous_identity",
                )
                for finding in shadow
            )
            continue

        if not legacy:
            items.append(_base_item(category="shadow_only", legacy=None, shadow=shadow[0]))
            continue
        if not shadow:
            items.append(_base_item(category="legacy_only", legacy=legacy[0], shadow=None))
            continue

        legacy_finding = legacy[0]
        shadow_finding = shadow[0]
        legacy_status = _text(legacy_finding.get("status"))
        shadow_status = _text(shadow_finding.get("status"))
        legacy_evidence = _evidence_ids(legacy_finding, shadow=False)
        shadow_evidence = _evidence_ids(shadow_finding, shadow=True)
        if legacy_status != shadow_status:
            category = "status_conflict"
        elif legacy_evidence != shadow_evidence:
            category = "evidence_conflict"
        else:
            category = "agreement"
        items.append(_base_item(category=category, legacy=legacy_finding, shadow=shadow_finding))

    items.sort(
        key=lambda item: (
            _text(item.get("legacy_finding_id")) or "~",
            _text(item.get("shadow_finding_id")) or "~",
            item["category"],
        )
    )
    counts = Counter(item["category"] for item in items)
    return {
        "schema_version": "review-finding-comparison/1",
        "counts": {category: int(counts.get(category, 0)) for category in _CATEGORIES},
        "items": items,
    }
