"""Privacy-safe read model for Evidence-First shadow artifacts."""

from __future__ import annotations

from typing import Any

_MAX_FINDINGS = 200
_MAX_STATS = 32

def _pack_ref(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    pack_id = str(value.get("id", "") or "")
    version = str(value.get("version", "") or "")
    if not pack_id or not version:
        return None
    return {"id": pack_id, "version": version}


def _input_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    # Do not expose the server-side absolute path or snapshot location.
    return {
        key: value[key]
        for key in ("role", "filename", "sha256", "size", "media_type")
        if key in value
    }


def _evidence_ref_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in (
            "evidence_id",
            "source_kind",
            "source_ref",
            "sheet",
            "cell_or_range",
            "quote",
            "excerpt",
            "start_offset",
            "end_offset",
            "content_hash",
            "role",
        )
        if key in value
    }


def _finding_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        key: value[key]
        for key in (
            "finding_id",
            "identity_key",
            "rule_id",
            "rule_version",
            "issue_type",
            "severity",
            "risk_type",
            "sheet",
            "cell",
            "status",
            "decision",
            "verification_status",
            "conclusion",
            "basis",
            "suggestion",
            "reasons",
            "unknown_reason",
            "resolution",
            "review_scope",
        )
        if key in value
    }
    refs = value.get("evidence_refs_v2")
    if isinstance(refs, list):
        result["evidence_refs_v2"] = [
            ref for ref in (_evidence_ref_view(item) for item in refs) if ref
        ]
    return result


def _stats_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:_MAX_STATS]:
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[str(key)] = item
            continue
        if isinstance(item, dict):
            result[str(key)] = {
                str(nested_key): nested_value
                for nested_key, nested_value in list(item.items())[:_MAX_STATS]
                if isinstance(nested_value, (str, int, float, bool))
                or nested_value is None
            }
    return result


def _findings_view(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("findings"), list):
        return []
    return [
        finding
        for finding in (_finding_view(item) for item in value["findings"][:_MAX_FINDINGS])
        if finding
    ]


def _comparison_view(value: Any) -> dict[str, Any]:
    """Expose only bounded IDs/statuses from the V1/V2 comparison artifact."""
    categories = (
        "agreement",
        "legacy_only",
        "shadow_only",
        "status_conflict",
        "evidence_conflict",
        "not_comparable",
    )
    if not isinstance(value, dict):
        return {
            "status": "not_available",
            "authority": "v1",
            "candidate_source": "stage_c_shadow",
            "counts": {category: 0 for category in categories},
            "items": [],
        }

    def _count(raw: Any) -> int:
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0

    raw_counts = value.get("counts")
    counts = {
        category: _count(raw_counts.get(category, 0))
        if isinstance(raw_counts, dict)
        else 0
        for category in categories
    }
    allowed = {
        "category",
        "legacy_finding_id",
        "shadow_finding_id",
        "v1_status",
        "v2_status",
        "v1_evidence_ids",
        "v2_evidence_ids",
        "reason_code",
    }
    items: list[dict[str, Any]] = []
    raw_items = value.get("items")
    if isinstance(raw_items, list):
        for raw in raw_items[:_MAX_FINDINGS]:
            if not isinstance(raw, dict):
                continue
            item = {
                str(key): raw[key]
                for key in allowed
                if key in raw
                and isinstance(raw[key], (str, int, float, bool, list, type(None)))
            }
            if item:
                items.append(item)
    return {
        "status": "available",
        "authority": "v1",
        "candidate_source": "stage_c_shadow",
        "schema_version": value.get("schema_version", ""),
        "counts": counts,
        "items": items,
    }


def _stage_a_view(
    *,
    artifact_status: str,
    evidence: Any,
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        status = "error" if artifact_status == "error" else "running"
        return {"status": status}
    return {
        "status": "completed",
        "capture_status": evidence.get("capture_status"),
        "captured_cell_count": evidence.get("captured_cell_count", 0),
        "omitted_cell_count": evidence.get("omitted_cell_count", 0),
        "sheet_count": len(evidence.get("sheets", []))
        if isinstance(evidence.get("sheets"), list)
        else 0,
    }


def _stage_b_view(
    *,
    artifact_status: str,
    policy_pack: Any,
    plan: Any,
    findings: Any,
) -> dict[str, Any]:
    pack = _pack_ref(policy_pack)
    if pack is None:
        return {"status": "disabled", "findings": []}
    if artifact_status == "error":
        status = "error"
    elif isinstance(findings, dict) and isinstance(plan, dict):
        status = "completed"
    else:
        status = "running"

    plan_scope = plan.get("scope") if isinstance(plan, dict) else None
    plan_view = None
    if isinstance(plan, dict):
        skipped = plan.get("skipped")
        items = plan.get("items")
        plan_view = {
            "plan_id": plan.get("plan_id", ""),
            "target_sheets": (
                plan_scope.get("target_sheets", [])
                if isinstance(plan_scope, dict)
                else []
            ),
            "scope_status": (
                plan_scope.get("status", "unknown")
                if isinstance(plan_scope, dict)
                else "unknown"
            ),
            "items": len(items) if isinstance(items, list) else 0,
            "skipped": len(skipped) if isinstance(skipped, list) else 0,
        }
    return {
        "status": status,
        "policy_pack": pack,
        "plan": plan_view,
        "stats": _stats_view(findings.get("stats"))
        if isinstance(findings, dict)
        else {},
        "findings": _findings_view(findings),
    }


def _stage_c_view(
    *,
    artifact_status: str,
    judgement_policy_pack: Any,
    findings: Any,
) -> dict[str, Any]:
    pack = _pack_ref(judgement_policy_pack)
    if pack is None:
        return {"status": "disabled", "findings": []}
    if artifact_status == "error":
        status = "error"
    elif isinstance(findings, dict):
        status = "completed"
    else:
        status = "running"
    return {
        "status": status,
        "policy_pack": pack,
        "stats": _stats_view(findings.get("stats"))
        if isinstance(findings, dict)
        else {},
        "findings": _findings_view(findings),
    }


def build_artifact_view(
    *,
    review_id: str,
    manifest: dict[str, Any],
    evidence: Any = None,
    plan: Any = None,
    policy_findings: Any = None,
    v2_findings: Any = None,
    comparison: Any = None,
) -> dict[str, Any]:
    """Build the bounded payload exposed to the workbench."""
    artifact_status = str(manifest.get("artifact_status", "running"))
    return {
        "review_id": review_id,
        "artifact_status": artifact_status,
        "artifact_error": manifest.get("artifact_error"),
        "engine_version": manifest.get("engine_version", ""),
        "created_at": manifest.get("created_at"),
        "source_sha256": evidence.get("source_sha256", "")
        if isinstance(evidence, dict)
        else "",
        "requested_sheets": manifest.get("requested_sheets", []),
        "inputs": [
            item
            for item in (_input_view(value) for value in manifest.get("inputs", []))
            if item
        ],
        "comparison": _comparison_view(comparison),
        "stages": {
            "stage_a": _stage_a_view(
                artifact_status=artifact_status,
                evidence=evidence,
            ),
            "stage_b": _stage_b_view(
                artifact_status=artifact_status,
                policy_pack=manifest.get("policy_pack"),
                plan=plan,
                findings=policy_findings,
            ),
            "stage_c": _stage_c_view(
                artifact_status=artifact_status,
                judgement_policy_pack=manifest.get("judgement_policy_pack"),
                findings=v2_findings,
            ),
        },
    }
